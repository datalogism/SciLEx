"""Consistency checks of a review, shown on its Overview.

They compare the review's files with its workflow journal and tell what
looks broken, with a fix when one is safe:

- **results elsewhere**: the review's results folder has no results while
  another folder named after the review does (e.g. after a rename made with an
  older SciLEx) — fix: adopt that folder;
- **Zotero library changed**: the review is linked to a Zotero library other
  than the one its papers were imported from or last linked with;
- **unfinished collection**: a collection started and never finished (it can
  be resumed in ② Collect);
- **required sub-corpora**: papers in none of ``subcorpora.required``
  (fixed in Consolidate).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scilex.gui.services import journal
from scilex.gui.services.workspace import RESULTS_FILENAME, Review, results_candidates

logger = logging.getLogger(__name__)

RESULTS_ELSEWHERE = "results-elsewhere"
ZOTERO_CHANGED = "zotero-changed"
UNFINISHED_COLLECT = "unfinished-collect"
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Issue:
    """Something that looks inconsistent in a review."""

    kind: str
    message: str
    step: str | None = None  # step page that fixes it
    adopt: str | None = None  # folder to adopt as the results folder (safe fix)


def _results_issues(review: Review) -> list[Issue]:
    if review.has_results:
        return []
    candidates = results_candidates(
        review.folder, review.output_root, exclude=review.collection_dir
    )
    return [
        Issue(
            RESULTS_ELSEWHERE,
            f"No results in {review.collection_dir.name}, but {candidate.name} (a name of "
            f"this review) holds {_rows(candidate)} papers.",
            adopt=str(candidate),
        )
        for candidate in candidates
    ]


def _rows(folder) -> int:
    return journal._rows(folder / RESULTS_FILENAME) or 0


def _zotero_issues(review: Review) -> list[Issue]:
    from scilex.gui.services import zotero_library

    current = journal.library_of(zotero_library.load_source(review.folder))
    origin = None
    for event in reversed(journal.load(review.folder)):
        library = (event.get("used") or {}).get("zotero") or {}
        if event.get("activity") in ("import-zotero", "extend-zotero") and library.get(
            "library_id"
        ):
            origin = event
            break
        if event.get("activity") == "link":
            return []  # linked on purpose after the import
    if not current or origin is None:
        return []
    imported = origin["used"]["zotero"]
    if (imported.get("library_type"), imported.get("library_id")) == (
        current.get("library_type"),
        current.get("library_id"),
    ):
        return []
    return [
        Issue(
            ZOTERO_CHANGED,
            f"The papers came from Zotero library "
            f"{imported.get('library_name') or imported.get('library_id')} "
            f"({str(origin.get('at', ''))[:10]}), but the review is now linked to "
            f"{current.get('library_name') or current.get('library_id')}. Add the papers "
            "of the new library in ⑤ Extend (linking it) to match them with its items.",
            step="extend",
        )
    ]


def _collect_issues(review: Review) -> list[Issue]:
    from scilex.gui.services.collect_summary import detect_resume

    info = detect_resume(review.collection_dir)
    if info is None:
        return []
    return [
        Issue(
            UNFINISHED_COLLECT,
            f"A collection stopped after {info.done} of {info.total} queries. Resume it "
            "in ② Collect, or start over.",
            step="collect",
        )
    ]


def _subcorpus_issues(review: Review, main_config: dict | None) -> list[Issue]:
    required = list((main_config or {}).get("required_subcorpora") or [])
    if not required or not review.has_results:
        return []
    from scilex.gui.services.consolidate import unclassified_papers
    from scilex.gui.services.extend import read_results

    data = read_results(review.results_path)
    missing = unclassified_papers(data, required) if data is not None else []
    if not missing:
        return []
    return [
        Issue(
            UNCLASSIFIED,
            f"{len(missing)} papers are in none of the required sub-corpora "
            f"({', '.join(required)}). Classify them in Consolidate.",
            step="consolidate",
        )
    ]


def check(review: Review, main_config: dict | None = None) -> list[Issue]:
    """Every issue found in ``review`` (a failing check is skipped, not raised)."""
    issues: list[Issue] = []
    for checker in (
        _results_issues,
        _zotero_issues,
        _collect_issues,
        lambda r: _subcorpus_issues(r, main_config),
    ):
        try:
            issues.extend(checker(review))
        except Exception:
            logger.warning("Consistency check failed", exc_info=True)
    return issues
