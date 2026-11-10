"""Knowledge graph of a review: Zotero export -> scilex-lpwc-ap mapping -> Turtle.

Shared by ⑧ Export and the ``scilex-build-kg`` command. The papers are read
from the review's own Zotero library / collection (``zotero_source.yml``); a
review without one uses the collection named after it in the library of the
keys file (where ⑧ Export pushes by default).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from scilex.crawlers.utils import sanitize_secrets
from scilex.gui.services import zotero_library
from scilex.gui.services.zotero_library import ZoteroSource
from scilex.kg.profile import default_base_iri, read_version, slugify
from scilex.tagging.grid import GRID_FILENAME, TAG_COLUMN, load_grid

KG_DIRNAME = "kg"


@dataclass
class KgExport:
    """What a knowledge-graph export wrote."""

    turtle: Path
    bib: Path
    report: object  # scilex.kg.build.BuildReport
    source: ZoteroSource


def missing_dependencies() -> str | None:
    """Return why the knowledge graph cannot be built here, or None."""
    missing = [m for m in ("morph_kgc", "pyoxigraph") if importlib.util.find_spec(m) is None]
    if missing:
        return (
            f"Building the knowledge graph needs {', '.join(missing)}: "
            "install SciLEx with the 'kg' extra (pip install 'scilex[kg]')."
        )
    if not read_version():
        return "The scilex-lpwc-ap profile is missing (run: python -m scilex.kg.sync_profile)."
    return None


def resolve_source(keys: dict, folder: Path, review_name: str) -> ZoteroSource:
    """Return the review's Zotero source: its own choice, else the collection named after it.

    Raises:
        ZoteroNotConfiguredError: If the Zotero key is missing.
        LookupError: If the review has no source and no collection has its name.
    """
    source = zotero_library.load_source(folder)
    if source is not None:
        return source
    api = zotero_library.client(keys)
    collection = api.find_collection_by_name(review_name)
    if not collection:
        raise LookupError(
            f"No Zotero collection named '{review_name}': choose the review's Zotero "
            "library and collection first (⑧ Export), or push the papers to Zotero."
        )
    return ZoteroSource(
        library_id=str(api.user_id),
        library_type=api.user_role,
        collection_key=collection["data"]["key"],
        collection_name=review_name,
        include_subcollections=False,
    )


def _record_kg_snapshot(folder: Path, bib: Path) -> None:
    """Record the annotation state of the exported papers (Overview history)."""
    from scilex.gui.services.overview import record_snapshot
    from scilex.kg.bib2json import convert

    tables = convert(bib)
    tags: dict[str, list[str]] = {entry["ID"]: [] for entry in tables["entries"]}
    for row in tables["lists"]:
        if row["field"] == "keywords" and row["entry"] in tags:
            tags[row["entry"]].append(row["value"])
    record_snapshot(folder, tags.values(), "kg-export")


def _profile_version() -> dict:
    """Version of the pinned scilex-lpwc-ap profile (``scilex/kg/ap/VERSION.json``)."""
    import json

    path = Path(__file__).resolve().parents[2] / "kg" / "ap" / "VERSION.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: data.get(k) for k in ("version_iri", "version_info", "commit")}


def _journal_export(folder: Path, turtle: Path, source, report) -> None:
    from scilex.gui.services import journal

    journal.append(
        folder,
        "export-kg",
        used={"zotero": journal.library_of(source), "profile": _profile_version()},
        generated={"turtle": Path(turtle).name, "valid": getattr(report, "conforms", None)},
    )


def grid_dimensions(folder: Path) -> list[str] | None:
    """Dimensions of the review's annotation grid (None: no grid)."""
    path = Path(folder) / GRID_FILENAME
    return load_grid(path)[TAG_COLUMN].tolist() if path.is_file() else None


def export_knowledge_graph(
    *,
    keys: dict,
    folder: Path,
    review_name: str,
    output_dir: Path,
    creator: str,
    base_iri: str | None = None,
    run_validation: bool = True,
    bib: Path | None = None,
    progress=lambda percent, message: None,
) -> KgExport:
    """Export the review's Zotero papers and build its knowledge graph.

    Args:
        keys: Content of the keys file (Zotero key).
        folder: Review folder (``zotero_source.yml``, ``annotation_grid.csv``).
        review_name: Review name (dataset title, default base IRI, default collection).
        output_dir: Where ``<review>.ttl`` (and the ``.bib`` it came from) go.
        creator: IRI of the user's ORCID iD.
        base_iri: Base IRI of the review's resources.
        run_validation: Validate against the profile's SHACL shapes.
        bib: A BibLaTeX export to use instead of Zotero.
        progress: ``(percent, message)`` callback.

    Raises:
        KgDependencyError, ProfileError, LookupError, ConnectionError, ZoteroNotConfiguredError.
    """
    from scilex.kg.build import build_knowledge_graph

    if not creator:
        raise ValueError("An ORCID iD is required to build a knowledge graph.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(review_name)
    turtle = output_dir / f"{slug}.ttl"
    subcorpora: dict[str, list[str]] = {}
    source = zotero_library.load_source(folder)
    if bib is None:
        progress(5, "Finding the review's Zotero library…")
        source = resolve_source(keys, folder, review_name)
        progress(15, f"Exporting {source.describe()} from Zotero…")
        api = zotero_library.client(keys, library=source)
        text, subcorpora = zotero_library.export_source_biblatex(api, source)
        if not text.strip():
            raise LookupError(f"{source.describe()} has no paper.")
        bib = output_dir / f"{slug}.bib"
        # Written next to the graph: no API key or token in it either.
        bib.write_text(sanitize_secrets(text), encoding="utf-8")
    progress(40, "Mapping with the scilex-lpwc-ap profile…")
    report = build_knowledge_graph(
        bib,
        turtle,
        review_name=review_name,
        base_iri=base_iri or default_base_iri(review_name),
        dimensions=grid_dimensions(folder),
        run_validation=run_validation,
        creator=creator,
        subcorpora=subcorpora or None,
    )
    _record_kg_snapshot(folder, Path(bib))
    _journal_export(folder, turtle, source, report)
    progress(100, "Done")
    return KgExport(turtle=turtle, bib=Path(bib), report=report, source=source)
