"""Screening decisions of a review, kept in ``output/<name>/screening.csv``.

Decisions live in their own file so that re-running the aggregation never
erases them. A paper is identified by :func:`paper_key`: its normalised DOI,
otherwise its normalised title plus year. Decisions whose paper disappeared
from the results are kept and reported as orphans.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from scilex.constants import extract_year, is_valid, normalize_doi
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

SCREENING_FILENAME = "screening.csv"
INCLUDE, EXCLUDE, MAYBE = "include", "exclude", "maybe"
DECISIONS = (INCLUDE, EXCLUDE, MAYBE)
FIELDS = ("paper_key", "decision", "note", "updated_at")


@dataclass
class Decision:
    """Screening decision on one paper."""

    paper_key: str
    decision: str
    note: str = ""
    updated_at: str = ""


def paper_key(row) -> str:
    """Stable key of a paper (a results row or a mapping with DOI/title/date)."""
    doi = row.get("DOI")
    if is_valid(doi):
        normalised = normalize_doi(doi)
        if normalised:
            return f"doi:{normalised}"
    raw_title = row.get("title")
    title = str(raw_title).lower() if is_valid(raw_title) else ""
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    if not title:
        # Without DOI or title, a NaN title would give every such paper the
        # same "title:nan" key and merge them into one screening decision.
        for field in ("archiveID", "url"):
            if is_valid(row.get(field)):
                return f"{field}:{row.get(field)}"
    year = extract_year(row.get("date")) if is_valid(row.get("date")) else None
    return f"title:{title}|{year or ''}"


def screening_path(review: Review) -> Path:
    """Path of the review's screening file."""
    return review.collection_dir / SCREENING_FILENAME


class ReviewFileError(ValueError):
    """A file of the review is damaged; the message names it and the fix."""


def load_results(review: Review) -> pd.DataFrame:
    """Load the aggregated results with a ``paper_key`` column added."""
    from scilex.io_utils import load_aggregated_data

    try:
        data = load_aggregated_data(
            {"collect_name": review.name}, collect_dir=str(review.collection_dir)
        )
    except ValueError as exc:  # pandas ParserError, UnicodeDecodeError
        raise ReviewFileError(
            f"{review.results_path} is damaged ({exc}).\nRun 'Aggregate existing "
            "results' in ② Collect to write it again."
        ) from exc
    data = data.loc[:, [c for c in data.columns if not str(c).startswith("Unnamed")]]
    data["paper_key"] = [paper_key(record) for record in data.to_dict("records")]
    return data


def _read_file(review: Review) -> tuple[dict[str, Decision], list[dict]]:
    """Read the screening file: (valid decisions, rows kept untouched).

    Rows with an unknown decision or without a paper key are not decisions the
    GUI understands, but they are never dropped: they come back as raw rows so
    the next write puts them back.
    """
    path = screening_path(review)
    if not path.is_file():
        return {}, []
    decisions: dict[str, Decision] = {}
    untouched: list[dict] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("paper_key") and row.get("decision") in DECISIONS:
                    decisions[row["paper_key"]] = Decision(
                        **{f: row.get(f, "") or "" for f in FIELDS}
                    )
                else:
                    untouched.append({f: row.get(f) or "" for f in FIELDS})
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ReviewFileError(
            f"{path} cannot be read ({exc}).\nYour screening decisions are stored "
            "in this file: repair it, or move it away to start screening again."
        ) from exc
    return decisions, untouched


def load_decisions(review: Review) -> dict[str, Decision]:
    """Read the screening file; returns an empty dict if there is none."""
    return _read_file(review)[0]


def _write_file(
    review: Review, decisions: dict[str, Decision], untouched: list[dict]
) -> None:
    path = screening_path(review)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for decision in decisions.values():
            writer.writerow(decision.__dict__)
        writer.writerows(untouched)
    tmp.replace(path)


def save_decisions(review: Review, decisions: dict[str, Decision]) -> None:
    """Write all decisions atomically; rows the GUI does not understand stay."""
    _write_file(review, decisions, _read_file(review)[1])


def _apply_decision(
    review: Review, key: str, decision: str | None, note: str = ""
) -> dict[str, Decision]:
    """Re-read the file, change only ``key``, write atomically; return the result."""
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}")
    decisions, untouched = _read_file(review)
    if decision is None:
        decisions.pop(key, None)
    else:
        decisions[key] = Decision(
            key, decision, note, datetime.now().isoformat(timespec="seconds")
        )
    _write_file(review, decisions, untouched)
    return decisions


def set_decision(
    review: Review, key: str, decision: str | None, note: str = ""
) -> None:
    """Record (or clear, with ``decision=None``) the decision on one paper."""
    _apply_decision(review, key, decision, note)


def orphan_keys(review: Review, results: pd.DataFrame) -> list[str]:
    """Decisions whose paper is no longer in the results."""
    present = set(results["paper_key"])
    return [key for key in load_decisions(review) if key not in present]


def included_results(
    review: Review, results: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Rows of the results marked as included."""
    results = load_results(review) if results is None else results
    included = {k for k, d in load_decisions(review).items() if d.decision == INCLUDE}
    return results[results["paper_key"].isin(included)]


# --- In-memory session used by the Screen page -------------------------------

FILTER_ALL, FILTER_UNDECIDED = "all", "undecided"
DECISION_LABELS = {INCLUDE: "Include", EXCLUDE: "Exclude", MAYBE: "Maybe"}

# Filters on paper properties ("facets"): key -> label, in display order.
# Values are OR-ed within a facet and facets are AND-ed.
FACETS = {
    "item_type": "Document type",
    "origin": "Origin",
    "imported": "Imported on",
    "source": "Source API",
    "collection": "Zotero collection",
    "collect_keywords": "Collect keywords",
    "tags": "Tags",
    "lpwc_tasks": "Tasks (LPWC)",
    "lpwc_datasets": "Datasets (LPWC)",
    "orkg_problems": "Research problems (ORKG)",
    "orkg_fields": "Research fields (ORKG)",
}
NONE_VALUE = "(none)"
BEFORE_TRACKING = "Before tracking"
# Facet -> results column holding ";"-separated values.
_LIST_COLUMNS = {
    "collection": "zotero_collections",
    "tags": "tags",
    "lpwc_tasks": "lpwc_tasks",
    "lpwc_datasets": "lpwc_datasets",
    "orkg_problems": "orkg_research_problems",
    "orkg_fields": "orkg_research_fields",
}
_COLLECT_KW_PREFIX = re.compile(r"^Collect_KW\d+:", re.IGNORECASE)


def _text(value) -> str:
    return str(value) if is_valid(value) else ""


def _split(value) -> set[str]:
    """Values of a ";"-separated cell."""
    return {part.strip() for part in _text(value).split(";") if part.strip()}


def item_type_label(item_type: str) -> str:
    """Readable Zotero item type: ``journalArticle`` gives "Journal article"."""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", item_type).lower()
    return words[:1].upper() + words[1:]


def _facet_values(record: dict, logged: dict | None) -> dict[str, set[str]]:
    """Facet values of one results row (``logged``: its paper log entry)."""
    from scilex.gui.services.paper_log import origin_of

    item_type = _text(record.get("itemType"))
    values = {
        "item_type": {item_type_label(item_type)} if item_type else set(),
        "origin": {(logged or {}).get("origin") or origin_of(record)},
        "imported": {(logged or {}).get("imported_at") or BEFORE_TRACKING},
        # "OpenAlex*;SemanticScholar": the star marks a merged duplicate.
        "source": {v.rstrip("*") for v in _split(record.get("archive"))},
        "collect_keywords": {
            _COLLECT_KW_PREFIX.sub("", v).strip()
            for v in _split(record.get("collect_keywords"))
        }
        - {""},
    }
    for facet, column in _LIST_COLUMNS.items():
        values[facet] = _split(record.get(column))
    return {facet: found or {NONE_VALUE} for facet, found in values.items()}


def _paper_log(review: Review, results: pd.DataFrame) -> dict[str, dict]:
    """Paper log of the review, completed with papers written by untracked tools."""
    from scilex.gui.services import paper_log

    try:
        return paper_log.update(
            review.folder,
            results,
            # Papers the log misses were written since its last update: date
            # them with the last change of the results file.
            when=paper_log.mtime_date(review.results_path),
        )
    except Exception:  # the filters must never prevent screening
        logger.warning("Cannot read the paper log", exc_info=True)
        return {}


def _number(value) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)


class ScreeningSession:
    """Results and decisions of a review, kept in memory while screening.

    The results are loaded once. Each decision re-reads ``screening.csv``,
    changes only that paper's row and writes it back atomically, so two
    windows on the same review do not overwrite each other.
    """

    def __init__(self, review: Review, results: pd.DataFrame | None = None):
        """Load the results (unless given) and the existing decisions."""
        self.review = review
        results = load_results(review) if results is None else results
        results = results.drop_duplicates("paper_key")
        self.decisions = load_decisions(review)
        present = set(results["paper_key"])
        self._present = present
        self.orphans = [k for k in self.decisions if k not in present]
        self._details: dict[str, dict] = {}
        self._search: dict[str, str] = {}
        self._facets: dict[str, dict[str, set[str]]] = {}
        self._records: dict[str, dict] = {}  # raw results rows (Explore notice)
        self.rows: list[dict] = []
        log = _paper_log(review, results)
        for record in results.to_dict("records"):
            key = record["paper_key"]
            self._records[key] = record
            venue = _text(record.get("journalAbbreviation")) or _text(
                record.get("publisher")
            )
            citations = _number(record.get("nb_citation"))
            if citations is None:
                citations = _number(record.get("canonical_citation_count"))
            year = (
                extract_year(record["date"]) if is_valid(record.get("date")) else None
            )
            score = _number(record.get("relevance_score"))
            facets = _facet_values(record, log.get(key))
            self._facets[key] = facets
            imported = next(iter(facets["imported"]))
            imported = "" if imported == BEFORE_TRACKING else imported
            item_type = next(iter(facets["item_type"]))
            item_type = "" if item_type == NONE_VALUE else item_type
            self.rows.append(
                {
                    "paper_key": key,
                    "title": _text(record.get("title")),
                    "year": year,
                    "venue": venue,
                    "score": None if score is None else round(score, 2),
                    "citations": None if citations is None else int(citations),
                    "item_type": item_type,
                    "imported": imported,
                    "decision": self._label(key),
                }
            )
            self._details[key] = {
                "title": _text(record.get("title")),
                "authors": _text(record.get("authors")).replace(";", ", "),
                "year": year,
                "venue": venue,
                "abstract": _text(record.get("abstract")),
                "doi": _text(record.get("DOI")),
                "item_type": _text(record.get("itemType")),
                "tags": _text(record.get("tags")),
                "origin": next(iter(facets["origin"])),
                "imported": imported,
            }
            self._search[key] = (
                f"{_text(record.get('title'))} {_text(record.get('abstract'))}".lower()
            )
        self.rows.sort(key=lambda r: -(r["score"] if r["score"] is not None else -1))
        self._row_by_key = {r["paper_key"]: r for r in self.rows}

    def _label(self, key: str) -> str:
        decision = self.decisions.get(key)
        return DECISION_LABELS[decision.decision] if decision else ""

    def detail(self, key: str) -> dict:
        """Display fields of one paper."""
        return self._details[key]

    def row(self, key: str) -> dict:
        """Grid row of one paper (shared with the grid data)."""
        return self._row_by_key[key]

    def record(self, key: str) -> dict:
        """Every column of one paper, as in ``aggregated_results.csv``."""
        return self._records[key]

    def facets_of(self, key: str) -> dict[str, set[str]]:
        """Facet values of one paper (see :data:`FACETS`)."""
        return self._facets[key]

    def facet_counts(self, keys: list[str], facet: str) -> list[tuple[str, int]]:
        """Values of ``facet`` among the papers ``keys``, most frequent first."""
        counts: dict[str, int] = {}
        for key in keys:
            for value in self._facets[key][facet]:
                counts[value] = counts.get(value, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def decision_of(self, key: str) -> Decision | None:
        """Current decision on ``key``, if any."""
        return self.decisions.get(key)

    def decide(self, key: str, decision: str | None, note: str = "") -> dict:
        """Record or clear (``None``) a decision, save it, return the updated row."""
        self._refresh(_apply_decision(self.review, key, decision, note))
        return self._row_by_key[key]

    def _refresh(self, decisions: dict[str, Decision]) -> None:
        """Adopt the decisions just read from disk (they include other windows')."""
        self.decisions = decisions
        for row_key, row in self._row_by_key.items():
            row["decision"] = self._label(row_key)
        self.orphans = [k for k in decisions if k not in self._present]

    def update_note(self, key: str, note: str) -> bool:
        """Change the note of an already decided paper; False if undecided/unchanged."""
        current = self.decisions.get(key)
        if current is None or current.note == note:
            return False
        self.decide(key, current.decision, note)
        return True

    def counts(self) -> dict[str, int]:
        """Number of papers per decision, undecided and total."""
        counts = dict.fromkeys(DECISIONS, 0)
        for key in self._row_by_key:
            decision = self.decisions.get(key)
            if decision:
                counts[decision.decision] += 1
        total = len(self.rows)
        counts["undecided"] = total - sum(counts[d] for d in DECISIONS)
        counts["total"] = total
        return counts

    def facet_options(self) -> dict[str, list[tuple[str, int]]]:
        """Values of each facet with their paper counts, most frequent first.

        A facet is left out when no paper has a value for it (e.g. no
        enrichment run, no Zotero collection), or when all papers share one
        value, since filtering on it would change nothing.
        """
        options = {}
        total = len(self._facets)
        for facet in FACETS:
            counts: dict[str, int] = {}
            for values in self._facets.values():
                for value in values[facet]:
                    counts[value] = counts.get(value, 0) + 1
            real = [value for value in counts if value != NONE_VALUE]
            if not real or (len(counts) == 1 and counts[real[0]] == total):
                continue
            if facet == "imported":  # chronological, newest first
                ordered = sorted(counts.items(), reverse=True)
            else:
                ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
            options[facet] = ordered
        return options

    def visible_rows(
        self,
        decision_filter: str = FILTER_ALL,
        query: str = "",
        facets: dict[str, set[str]] | None = None,
    ) -> list[dict]:
        """Rows matching a decision filter, a title/abstract search and facets."""
        needle = query.strip().lower()
        active = {
            facet: set(chosen) for facet, chosen in (facets or {}).items() if chosen
        }
        selected = []
        for row in self.rows:
            key = row["paper_key"]
            values = self._facets[key]
            if any(not values[facet] & chosen for facet, chosen in active.items()):
                continue
            decision = self.decisions.get(key)
            if decision_filter == FILTER_UNDECIDED:
                if decision:
                    continue
            elif decision_filter in DECISIONS and (
                decision is None or decision.decision != decision_filter
            ):
                continue
            if needle and needle not in self._search[key]:
                continue
            selected.append(row)
        return selected

    def next_undecided(self, order: list[str], current: str | None) -> str | None:
        """First undecided key after ``current`` in ``order`` (wrapping around)."""
        start = order.index(current) + 1 if current in order else 0
        for key in order[start:] + order[:start]:
            if key != current and key not in self.decisions:
                return key
        return None

    def forget(self, key: str) -> None:
        """Drop the decision of an orphan paper."""
        self._refresh(_apply_decision(self.review, key, None))
