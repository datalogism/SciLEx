"""Citation network from the review's Zotero library: a frozen snapshot.

When SciLEx pushes papers to Zotero it attaches to each one a child note
``{'citing': [DOIs], 'cited': [DOIs]}`` (who cites the paper, what it cites).
Those notes are the citation network as it was when the corpus was built:
unlike a new fetch from Semantic Scholar / Crossref / OpenCitations, which
depends on rate limits, on which source answers and on new citing papers, it
does not change between runs. That makes the graph and the citation metrics
reproducible.

:func:`import_snapshot` reads the notes into ``zotero_citations.json`` (the
snapshot, kept as read) and merges it into the caches the graph analysis reads
(``citations_cache.json``, ``citers_cache.json``): for a paper in the snapshot
the snapshot wins; papers it lacks keep what an API fetch found.
"""

from __future__ import annotations

import ast
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scilex.constants import normalize_doi
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

SNAPSHOT_FILENAME = "zotero_citations.json"
REFERENCES_CACHE = "citations_cache.json"
CITERS_CACHE = "citers_cache.json"
PAGE = 100


@dataclass
class SnapshotReport:
    """Outcome of :func:`import_snapshot`."""

    notes: int = 0  # citation notes read
    papers: int = 0  # papers of the review with a note (by DOI)
    empty: int = 0  # notes with neither citing nor cited papers
    unreadable: int = 0
    without_doi: int = 0  # notes whose paper has no DOI (cannot be keyed)
    references: int = 0
    citers: int = 0

    def message(self) -> str:
        text = (
            f"Citation snapshot from Zotero: {self.papers} papers ({self.references} "
            f"references, {self.citers} citing papers)"
        )
        extras = []
        if self.empty:
            extras.append(f"{self.empty} empty notes")
        if self.without_doi:
            extras.append(f"{self.without_doi} papers without DOI skipped")
        if self.unreadable:
            extras.append(f"{self.unreadable} unreadable notes")
        return text + (f" ({', '.join(extras)})" if extras else "") + "."


def parse_note(note_html: str) -> dict[str, list[str]] | None:
    """``{'citing': [...], 'cited': [...]}`` from a note, or None if it is not one."""
    text = html.unescape(re.sub(r"<[^>]+>", "", note_html or "")).strip()
    if not text.startswith("{") or ("citing" not in text and "cited" not in text):
        return None
    for parse in (json.loads, ast.literal_eval):
        try:
            data = parse(text)
        except (ValueError, SyntaxError):
            continue
        if isinstance(data, dict):
            return {
                "citing": [str(d) for d in data.get("citing") or [] if d],
                "cited": [str(d) for d in data.get("cited") or [] if d],
            }
    raise ValueError("unreadable citation note")


def read_notes(api) -> tuple[dict[str, dict[str, list[str]]], int]:
    """Citation notes of the library by parent item key, and the unreadable count."""
    notes: dict[str, dict[str, list[str]]] = {}
    unreadable = 0
    start = 0
    while True:
        response = api._get(
            "/items", params={"itemType": "note", "limit": PAGE, "start": start}
        )
        if response is None:
            raise ConnectionError(
                "Zotero cannot be reached (offline, or the key was refused)."
            )
        page = response.json() or []
        for note in page:
            data = note.get("data", {})
            parent = data.get("parentItem")
            if not parent:
                continue
            try:
                parsed = parse_note(data.get("note", ""))
            except ValueError:
                unreadable += 1
                continue
            if parsed is not None:
                # Several notes on one paper: unite them.
                merged = notes.setdefault(parent, {"citing": [], "cited": []})
                for side in ("citing", "cited"):
                    merged[side] = list(dict.fromkeys(merged[side] + parsed[side]))
        if len(page) < PAGE:
            return notes, unreadable
        start += PAGE


def _dois(values) -> list[str]:
    return list(dict.fromkeys(d for d in (normalize_doi(v) for v in values) if d))


def to_caches(
    notes: dict[str, dict[str, list[str]]], items: list[dict]
) -> tuple[dict[str, list[str]], dict[str, list[str]], SnapshotReport]:
    """References and citers maps ``{doi: [dois]}`` keyed by each paper's DOI."""
    report = SnapshotReport(notes=len(notes))
    doi_of = {
        item["key"]: normalize_doi(item.get("data", {}).get("DOI") or "")
        for item in items
    }
    references: dict[str, list[str]] = {}
    citers: dict[str, list[str]] = {}
    for parent, note in notes.items():
        if not note["citing"] and not note["cited"]:
            report.empty += 1
        doi = doi_of.get(parent)
        if not doi:
            report.without_doi += parent in doi_of
            continue
        references[doi] = _dois([*references.get(doi, []), *note["cited"]])
        citers[doi] = _dois([*citers.get(doi, []), *note["citing"]])
    report.papers = len(set(references) | set(citers))
    report.references = sum(len(v) for v in references.values())
    report.citers = sum(len(v) for v in citers.values())
    return references, citers, report


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(path)


def import_snapshot(review: Review) -> SnapshotReport:
    """Read the citation notes of the review's Zotero library; see the module docstring.

    Raises:
        ZoteroNotConfiguredError, ConnectionError: Zotero cannot be read.
        ValueError: The review is not linked to a Zotero library.
    """
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None:
        raise ValueError("The review has no Zotero library: link it first (⑧ Export).")
    api = zotero_library.client(effective_keys(review.folder), library=source)
    items = zotero_library.fetch_source_papers(
        api, source, zotero_library.list_collections(api)
    )
    notes, unreadable = read_notes(api)
    keys = {item["key"] for item in items}
    notes = {parent: note for parent, note in notes.items() if parent in keys}
    references, citers, report = to_caches(notes, items)
    report.unreadable = unreadable

    folder = review.collection_dir
    folder.mkdir(parents=True, exist_ok=True)
    _write_json(
        folder / SNAPSHOT_FILENAME,
        {
            "source": f"zotero {source.library_type} {source.library_id}",
            "read_at": datetime.now().isoformat(timespec="seconds"),
            "references": references,
            "citers": citers,
        },
    )
    for name, snapshot in ((REFERENCES_CACHE, references), (CITERS_CACHE, citers)):
        path = folder / name
        cache = _read_json(path)
        cache.update(snapshot)  # the snapshot wins for the papers it has
        _write_json(path, cache)
    return report


def load_snapshot(review: Review) -> dict | None:
    """The snapshot written by :func:`import_snapshot`, if any."""
    data = _read_json(review.collection_dir / SNAPSHOT_FILENAME)
    return data or None
