"""Exports of a review: BibTeX, CSV, RDF/Turtle and Zotero.

The functions here are UI-independent. File exports are written to
``<collection_dir>/exports/<name>-<scope>-<YYYYmmdd-HHMM>.<ext>``.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from scilex.config import SciLExConfig
from scilex.gui.services import screening
from scilex.gui.services.workspace import Review

EXPORTS_DIRNAME = "exports"
SCOPE_INCLUDED, SCOPE_ALL = "included", "all"
SCOPES = (SCOPE_INCLUDED, SCOPE_ALL)
BIBTEX, CSV, TURTLE, ZOTERO = "bibtex", "csv", "turtle", "zotero"
EXTENSIONS = {BIBTEX: "bib", CSV: "csv", TURTLE: "ttl"}


@dataclass(frozen=True)
class ZoteroSettings:
    """Zotero credentials read from keys.yml."""

    api_key: str
    user_id: str
    user_mode: str = "user"


def exports_dir(review: Review) -> Path:
    """Folder holding the review's exported files."""
    return review.collection_dir / EXPORTS_DIRNAME


def select_papers(review: Review, scope: str) -> pd.DataFrame:
    """Rows of the results for ``scope`` (``paper_key`` column kept)."""
    results = screening.load_results(review)
    if scope == SCOPE_INCLUDED:
        return screening.included_results(review, results)
    if scope == SCOPE_ALL:
        return results
    raise ValueError(f"Unknown scope {scope!r}")


def scope_counts(review: Review) -> tuple[int, int]:
    """Return ``(included, total)`` paper counts."""
    results = screening.load_results(review)
    return len(screening.included_results(review, results)), len(results)


def export_path(review: Review, name: str, scope: str, extension: str) -> Path:
    """Output path of a new export (the folder is created)."""
    folder = exports_dir(review)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{name}-{scope}-{stamp}.{extension}"
    counter = 2
    while path.exists():
        path = folder / f"{name}-{scope}-{stamp}-{counter}.{extension}"
        counter += 1
    return path


def list_exports(review: Review) -> list[Path]:
    """Previous exports, newest first."""
    folder = exports_dir(review)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _plain(data: pd.DataFrame) -> pd.DataFrame:
    return data.drop(columns=["paper_key"], errors="ignore")


def write_bibtex(data: pd.DataFrame, target: Path) -> Path:
    """Write ``data`` as BibTeX with the project exporter."""
    from scilex.export_to_bibtex import export_to_bibtex

    # The exporter writes at a fixed place; let it work in a scratch folder.
    with tempfile.TemporaryDirectory() as scratch:
        scratch_collect = Path(scratch) / "export"
        scratch_collect.mkdir()
        generated = export_to_bibtex(
            _plain(data), {"output_dir": scratch, "collect_name": "export"}
        )
        target.write_text(Path(generated).read_text(encoding="utf-8"), encoding="utf-8")
    return target


def write_csv(review: Review, data: pd.DataFrame, target: Path) -> Path:
    """Write ``data`` as ``;``-separated CSV plus decision and note columns."""
    decisions = screening.load_decisions(review)
    table = data.copy()
    table["screening_decision"] = [
        decisions[k].decision if k in decisions else "" for k in table["paper_key"]
    ]
    table["screening_note"] = [
        decisions[k].note if k in decisions else "" for k in table["paper_key"]
    ]
    _plain(table).to_csv(target, sep=";", index=False)
    return target


def write_turtle(review: Review, data: pd.DataFrame, target: Path) -> Path:
    """Write ``data`` as RDF/Turtle (BibTeX is generated then converted)."""
    from scilex.export_to_turtle import DEFAULT_BASE_URI
    from scilex.rdf import convert_to_string

    with tempfile.TemporaryDirectory() as scratch:
        bib_path = write_bibtex(data, Path(scratch) / "papers.bib")
        rdf = convert_to_string(
            str(bib_path),
            base_uri=DEFAULT_BASE_URI,
            fmt="turtle",
            collect_name=review.name,
        )
    target.write_text(rdf, encoding="utf-8")
    return target


def run_file_export(review: Review, fmt: str, scope: str) -> Path:
    """Export the papers of ``scope`` in ``fmt``; returns the written file."""
    data = select_papers(review, scope)
    if data.empty:
        raise ValueError("There is no paper to export for this scope.")
    target = export_path(review, "papers", scope, EXTENSIONS[fmt])
    writers = {
        BIBTEX: lambda: write_bibtex(data, target),
        CSV: lambda: write_csv(review, data, target),
        TURTLE: lambda: write_turtle(review, data, target),
    }
    if fmt not in writers:
        raise ValueError(f"Unknown format {fmt!r}")
    written = writers[fmt]()
    from scilex.gui.services import journal

    journal.append(
        review.folder,
        "export-file",
        params={"format": fmt, "scope": scope},
        generated={"file": Path(written).name, "papers": len(data)},
    )
    return written


def zotero_settings(config: SciLExConfig) -> ZoteroSettings | None:
    """Zotero credentials from the config, or None without a key.

    The global key is enough: ``user_id`` is "" when the keys file has no
    library id (the review's own group is used).
    """
    block = config.api.get("Zotero") or config.api.get("zotero") or {}
    api_key, user_id = block.get("api_key"), block.get("user_id")
    if isinstance(api_key, list):
        api_key = api_key[0] if api_key else None
    if not api_key:
        return None
    return ZoteroSettings(
        str(api_key), str(user_id or ""), block.get("user_mode") or "user"
    )


def push_to_zotero(
    review: Review, config: SciLExConfig, scope: str, zotero_api=None
) -> dict[str, int]:
    """Push the papers of ``scope`` to the review's Zotero library and collection.

    The review's own choice (``zotero_source.yml``: a user or group library and
    a collection) wins; without one, or with a whole library chosen, the papers
    go to a collection named after the review (created if needed) in that
    library, else in the library of keys.yml.

    ``zotero_api`` is injectable for tests. Returns the exporter's counts
    (``success``, ``failed``, ``skipped``, ``skipped_for_incompatibility``).
    """
    from scilex.gui.services.zotero_library import load_source
    from scilex.push_to_zotero import prefetch_templates, push_new_items_to_zotero

    source = load_source(review.folder)
    if zotero_api is None:
        settings = zotero_settings(config)
        if settings is None:
            raise ValueError("The global Zotero key is missing (API keys page).")
        if source is None and not settings.user_id:
            raise ValueError(
                "The review has no Zotero group: choose it on its Zotero group page."
            )
        from scilex.Zotero.zotero_api import ZoteroAPI

        library_id, library_type = (
            (source.library_id, source.library_type)
            if source is not None
            else (settings.user_id, settings.user_mode)
        )
        zotero_api = ZoteroAPI(library_id, library_type, settings.api_key)
    data = _plain(select_papers(review, scope))
    if data.empty:
        raise ValueError("There is no paper to export for this scope.")
    if source is not None and source.collection_key:
        key = source.collection_key
    else:
        collection = zotero_api.get_or_create_collection(review.name)
        if not collection:
            raise RuntimeError(
                f"Could not get or create the collection {review.name!r}."
            )
        key = collection["data"]["key"]
    existing_urls = zotero_api.get_existing_item_urls(key)
    templates = prefetch_templates(data)
    push_config = {
        "output_dir": str(review.output_root),
        "collect_name": review.name,
        "_collect_dir": str(review.collection_dir),
    }
    return push_new_items_to_zotero(
        data, zotero_api, key, existing_urls, templates, push_config
    )


def reveal_command(path: Path, platform: str | None = None) -> list[str]:
    """Command showing ``path`` in the system file manager."""
    platform = platform or sys.platform
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform.startswith("win"):
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path if path.is_dir() else path.parent)]


def reveal_in_folder(path: Path) -> None:
    """Show ``path`` in the file manager (call only on a user click)."""
    subprocess.Popen(reveal_command(path))  # noqa: S603
