"""Overview of a review: papers, sub-corpora, screening, enrichment, annotation history.

Zotero keeps no history of tags, so the annotation history is built from
snapshots SciLEx records each time it reads the annotations (import from
Zotero, the Annotate report, a knowledge-graph export): one JSON line per
snapshot in ``annotation_history.jsonl`` next to ``scilex.yml``.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from scilex.constants import extract_year, is_valid
from scilex.tagging.grid import PLACEHOLDER, is_automation_tag

logger = logging.getLogger(__name__)

HISTORY_FILENAME = "annotation_history.jsonl"
MISSING = ("", "NA", "nan", "None")

# Enrichment sources and the column showing a paper was enriched by them.
ENRICHMENT_COLUMNS = {
    "Crossref": "crossref_type",
    "Linked Papers With Code": "lpwc_paper",
    "ORKG": "orkg_paper",
    "Papers with Code": "pwc_url",
}


@dataclass
class Snapshot:
    """The annotation state of a review at one moment."""

    at: str  # ISO timestamp
    origin: str  # "import", "annotate", "kg-export"
    papers: int
    annotated: int  # papers with at least one DIMENSION:value
    pending: int  # papers with at least one DIMENSION:? left
    values: int  # DIMENSION:value tags
    by_dimension: dict[str, int] = field(default_factory=dict)  # papers coded per dimension


@dataclass
class Overview:
    """What the Overview page shows."""

    papers: int = 0
    by_year: dict[int, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_collection: dict[str, int] = field(default_factory=dict)
    screening: dict[str, int] = field(default_factory=dict)
    enrichment: dict[str, int] = field(default_factory=dict)
    history: list[Snapshot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Annotation snapshots
# ---------------------------------------------------------------------------


def _annotation_tags(tags: Iterable[str]) -> list[tuple[str, str]]:
    found = []
    for tag in tags:
        tag = str(tag).strip()
        if not tag or is_automation_tag(tag):
            continue
        dimension, sep, value = tag.partition(":")
        dimension = dimension.strip().upper()
        if sep and dimension and " " not in dimension:
            found.append((dimension, value.strip()))
    return found


def snapshot_of(papers_tags: Iterable[Iterable[str]], origin: str) -> Snapshot:
    """Summarize the annotation tags of each paper (one tag list per paper)."""
    papers = annotated = pending = values = 0
    by_dimension: Counter = Counter()
    for tags in papers_tags:
        papers += 1
        pairs = _annotation_tags(tags)
        coded = {d for d, v in pairs if v and v != PLACEHOLDER}
        values += sum(1 for d, v in pairs if v and v != PLACEHOLDER)
        annotated += bool(coded)
        pending += any(v == PLACEHOLDER for _, v in pairs)
        by_dimension.update(coded)
    return Snapshot(
        at=datetime.now().isoformat(timespec="seconds"),
        origin=origin,
        papers=papers,
        annotated=annotated,
        pending=pending,
        values=values,
        by_dimension=dict(by_dimension),
    )


def zotero_tags(items: Iterable[dict]) -> list[list[str]]:
    """Tag lists of Zotero items (papers only)."""
    from scilex.tagging.grid import is_paper

    return [
        [str(t.get("tag", "")) for t in item.get("data", {}).get("tags", [])]
        for item in items
        if is_paper(item)
    ]


def record_snapshot(folder: Path, papers_tags: Iterable[Iterable[str]], origin: str) -> Snapshot | None:
    """Append a snapshot to the review's history; never fails the caller."""
    try:
        snapshot = snapshot_of(papers_tags, origin)
        path = Path(folder) / HISTORY_FILENAME
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot.__dict__, ensure_ascii=False) + "\n")
        return snapshot
    except OSError as exc:
        logger.warning("Cannot record the annotation snapshot: %s", exc)
        return None


def load_history(folder: Path) -> list[Snapshot]:
    """Return the review's snapshots, oldest first (unreadable lines skipped)."""
    path = Path(folder) / HISTORY_FILENAME
    if not path.is_file():
        return []
    snapshots = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            snapshots.append(Snapshot(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return sorted(snapshots, key=lambda s: s.at)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _filled(value) -> bool:
    return is_valid(value) and str(value).strip() not in MISSING


def compute(review) -> Overview:
    """Compute the overview of ``review`` (empty when it has no results yet)."""
    from scilex.gui.services import screening

    overview = Overview(history=load_history(review.folder))
    if not review.has_results:
        return overview
    data = screening.load_results(review)
    overview.papers = len(data)
    rows = data.to_dict("records")

    years = Counter(
        year for row in rows if (year := extract_year(row.get("date"))) is not None
    )
    overview.by_year = dict(sorted(years.items()))
    overview.by_source = dict(
        Counter(str(r.get("archive")) for r in rows if _filled(r.get("archive"))).most_common()
    )
    collections: Counter = Counter()
    for row in rows:
        if _filled(row.get("zotero_collections")):
            collections.update(p for p in str(row["zotero_collections"]).split(";") if p)
    overview.by_collection = dict(collections.most_common())

    decisions = screening.load_decisions(review)
    counts = Counter(
        decisions[key].decision if key in decisions else "undecided"
        for key in data["paper_key"]
    )
    overview.screening = {
        "Included": counts.get(screening.INCLUDE, 0),
        "Maybe": counts.get(screening.MAYBE, 0),
        "Excluded": counts.get(screening.EXCLUDE, 0),
        "Not screened": counts.get("undecided", 0),
    }
    overview.enrichment = {
        label: sum(_filled(row.get(column)) for row in rows)
        for label, column in ENRICHMENT_COLUMNS.items()
        if column in data.columns
    }
    citations = review.collection_dir / "citations_cache.json"
    if citations.is_file():
        try:
            cache = json.loads(citations.read_text(encoding="utf-8"))
            dois = {str(d).lower() for d in data.get("DOI", []) if _filled(d)}
            overview.enrichment["Citations"] = sum(
                1 for doi, refs in cache.items() if refs and doi.lower() in dois
            )
        except (OSError, ValueError):
            pass
    return overview
