"""Eligibility criteria of a systematic review: formal, testable filters.

A systematic literature review states its criteria as a table: for each
criterion (C1 publication period, C2 coherence, C3 language…) an exclusion
criterion (EC), an inclusion criterion (IC) and its exceptions (Ex). Here each
criterion is also a **rule** SciLEx can check on every paper:

- **test** a criterion: which papers it would exclude, why, and which ones an
  exception keeps;
- **apply** the criteria: each excluded paper gets ``DELETED_BY:filter:<id>
  <cause>`` (kept in the corpus, left out of the analyses, shared through
  Zotero); applying again re-evaluates (a paper that passes now loses the tag).

Exceptions: a person tags a paper ``KEEP:<id>`` (e.g. ``KEEP:C1``, a dataset
paper published before the period but still relevant); a criterion can also
spare some paper types automatically; papers included in ③ Screen are never
excluded. The criteria are saved in ``criteria.yml`` (review folder); the
defaults follow a common SLR table and the review's ``scilex.yml``.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from scilex import review_tags
from scilex.constants import extract_year, is_valid, normalize_doi

FILENAME = "criteria.yml"
KEEP = review_tags.KEEP  # KEEP:<criterion id>: a person's exception
KINDS = {
    "period": "Publication period (years)",
    "coherence": "Terms in the title or abstract",
    "language": "Language",
    "access": "Access (open / paywall)",
    "peer_review": "Publication process (peer review)",
    "doi": "Referenceability (DOI)",
    "duplicates": "Duplicates (a more recent version exists)",
    "text": "Custom: title or abstract matches a pattern",
    "quality": "Quality filters of scilex.yml (abstract, type, authors…)",
    "metric": "Metrics: citations, PageRank, quality, venue rank…",
}
# Rules judged on the whole corpus (a row alone cannot tell).
CORPUS_KINDS = {"duplicates", "metric"}

# Metrics a ``metric`` criterion can test: label, and the columns read in turn
# (the first one set wins). Citation metrics come from Enrich › Citation
# metrics (``metric_*``) or from the collection (``nb_citation``…).
METRICS = {
    "citations": (
        "Citations",
        (
            "canonical_citation_count",
            "nb_citation",
            "metric_citations",
            "ss_citation_count",
        ),
    ),
    "citations_year": ("Citations per year", ("metric_citations_year",)),
    "cited_in_corpus": ("Citations from the corpus", ("metric_cited_in_corpus",)),
    "pagerank": ("PageRank (citation graph)", ("metric_pagerank", "pagerank")),
    "quality": ("Quality score", ("metric_quality", "quality_score")),
    "venue_rank": (
        "Venue rank (A*=10, A=8, B=6, C=4; Q1=10 … Q4=2.5)",
        ("metric_venue_rank", "venue_rank", "core_rank", "sjr_quartile"),
    ),
    "relevance": ("Relevance score", ("relevance_score",)),
    "column": ("Another numeric column", ()),
}
OPERATORS = {
    ">=": "at least",
    "<=": "at most",
    "top_percent": "in the top % of the corpus",
    "top_n": "in the top N of the corpus",
    "age_aware": "enough for its age (time-aware citations)",
}
RANK_OPERATORS = {"top_percent", "top_n"}
PREPRINT_TYPES = {"preprint", "report", "manuscript", "thesis", "webpage", "blogpost"}
_ENGLISH = re.compile(
    r"\b(the|and|of|for|with|this|that|we|is|are|on|in|to|from|by)\b", re.I
)


@dataclass
class Criterion:
    """One row of the criteria table, and its rule."""

    id: str
    name: str
    kind: str
    exclusion: str = ""
    inclusion: str = ""
    exceptions: str = ""
    enabled: bool = True
    params: dict = field(default_factory=dict)
    # Paper types an exception keeps automatically (PAPER_TYPE, e.g. Dataset).
    keep_types: list[str] = field(default_factory=list)

    @property
    def tag_prefix(self) -> str:
        return review_tags.filter_tag(self.id)


@dataclass
class Excluded:
    """A paper a criterion excludes."""

    index: int
    paper_key: str
    title: str
    cause: str


@dataclass
class TestResult:
    """What a criterion does on the corpus."""

    criterion: Criterion
    checked: int = 0
    excluded: list[Excluded] = field(default_factory=list)
    spared: list[Excluded] = field(default_factory=list)  # kept by an exception
    notes: list[str] = field(default_factory=list)  # e.g. metric coverage

    def message(self) -> str:
        text = (
            f"{self.criterion.id}: {len(self.excluded)} of {self.checked} papers "
            "excluded"
        )
        if self.spared:
            text += f", {len(self.spared)} kept by an exception"
        return text + "."


# -- defaults and storage ------------------------------------------------------


def defaults(main: dict | None = None) -> list[Criterion]:
    """The usual SLR criteria, set from ``scilex.yml`` (years, keywords)."""
    main = main or {}
    years = sorted(int(y) for y in main.get("years") or [] if str(y).isdigit())
    start, end = (years[0], years[-1]) if years else (2019, dt.date.today().year)
    groups = [[str(t) for t in group] for group in main.get("keywords") or [] if group]
    return [
        Criterion(
            "C1",
            "Publication period",
            "period",
            f"Not published between {start} and {end}",
            f"Published between {start} and {end}",
            "Inclusion: published before but still relevant (often dataset papers)",
            params={"start": start, "end": end},
            keep_types=["Dataset"],
        ),
        Criterion(
            "C2",
            "Coherence",
            "coherence",
            "Contains no term of a keyword group in the title or abstract",
            "Contains at least one term of each keyword group in the title or abstract",
            "Inclusion: no term found but related to the research questions "
            "(then add the new terms)",
            params={"groups": groups},
        ),
        Criterion(
            "C3",
            "Language",
            "language",
            "Written in a language other than English",
            "Written in English",
            "",
            params={"languages": ["en"]},
        ),
        Criterion(
            "C4",
            "Access",
            "access",
            "Not freely accessible",
            "Readable without a paywall",
            "Inclusion: partially open access",
            enabled=False,  # access metadata is often missing: enable after Crossref
            params={"exclude_unknown": False},
        ),
        Criterion(
            "C5",
            "Publication process",
            "peer_review",
            "Not peer-reviewed",
            "Peer-reviewed",
            "Inclusion: not peer-reviewed but highly relevant. Exclusion: "
            "peer-reviewed but not yet accessible",
            enabled=False,
        ),
        Criterion(
            "C6",
            "Referenceability",
            "doi",
            "No associated DOI",
            "Has an associated DOI",
            "Inclusion: no DOI but highly relevant",
        ),
        Criterion(
            "C7",
            "Duplicates",
            "duplicates",
            "A more recent version exists",
            "Last published version",
            "A paper presenting both a model and a dataset is annotated twice",
        ),
        Criterion(
            "C8",
            "Quality",
            "quality",
            "Fails a quality filter of scilex.yml (no abstract, item type, "
            "authors, abstract length…)",
            "Passes the quality filters of scilex.yml",
            "",
            enabled=bool(main.get("quality_filters")),
            params={"quality_filters": dict(main.get("quality_filters") or {})},
        ),
        Criterion(
            "C9",
            "Impact",
            "metric",
            "Too few citations for its age",
            "Cited enough for its age (none required in its first 18 months)",
            "Inclusion: little cited but central in the corpus (PageRank top 10 %)",
            enabled=False,  # needs citation counts: enable after Enrich
            params={
                "match": "any",
                "missing": "keep",
                "conditions": [
                    {"metric": "citations", "op": "age_aware"},
                    {"metric": "pagerank", "op": "top_percent", "value": 10},
                ],
            },
        ),
    ]


def path_of(folder: Path) -> Path:
    return Path(folder) / FILENAME


def load(folder: Path, main: dict | None = None) -> list[Criterion]:
    """The review's criteria (the defaults when none is saved)."""
    path = path_of(folder)
    if not path.is_file():
        return defaults(main)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    names = set(Criterion.__dataclass_fields__)
    return [Criterion(**{k: v for k, v in item.items() if k in names}) for item in raw]


def _check_conditions(criterion: Criterion) -> None:
    """Refuse a ``metric`` condition SciLEx cannot check."""
    for condition in (criterion.params or {}).get("conditions") or []:
        metric, op = condition.get("metric"), condition.get("op", ">=")
        where = f"{criterion.id}: "
        if metric not in METRICS:
            raise ValueError(f"{where}unknown metric {metric!r}")
        if op not in OPERATORS:
            raise ValueError(f"{where}unknown operator {op!r}")
        if metric == "column" and not str(condition.get("column") or "").strip():
            raise ValueError(f"{where}name the column to test")
        if op == "age_aware" and metric != "citations":
            raise ValueError(f"{where}'enough for its age' applies to citations")
        if op != "age_aware" and _number(condition.get("value")) is None:
            raise ValueError(f"{where}a value is needed for {_label(condition)}")


def save(folder: Path, criteria: list[Criterion]) -> Path:
    """Write ``criteria.yml`` (refuses duplicate or empty ids, unknown kinds)."""
    seen = set()
    for criterion in criteria:
        if not criterion.id.strip() or ";" in criterion.id or " " in criterion.id:
            raise ValueError(f"Invalid criterion id {criterion.id!r} (no space or ';')")
        if criterion.id in seen:
            raise ValueError(f"Two criteria are named {criterion.id}.")
        if criterion.kind not in KINDS:
            raise ValueError(f"Unknown kind {criterion.kind!r}")
        if criterion.kind == "metric":
            _check_conditions(criterion)
        seen.add(criterion.id)
    path = path_of(folder)
    rows = [asdict(c) for c in criteria]
    text = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    from scilex.gui.services import versions

    versions.record_criteria(folder, text, rows)  # criteria_history/<sha256>.yml
    return path


# -- rules ----------------------------------------------------------------------


def _text(row: dict, column: str) -> str:
    value = row.get(column)
    return str(value) if is_valid(value) else ""


def _title_key(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", title.lower()).strip()


def _duplicates_causes(data: pd.DataFrame) -> dict[int, str]:
    """Older versions of a paper (same title): row index -> cause.

    Copies kept on purpose in different Zotero collections (e.g. once as a
    model, once as a dataset) are not duplicates.
    """
    groups: dict[str, list[tuple[int, int, str]]] = {}
    for index, row in zip(data.index, data.to_dict("records"), strict=True):
        key = _title_key(_text(row, "title"))
        if len(key) < 12:  # too short to be sure
            continue
        year = extract_year(row.get("date")) or 0
        corpus = ";".join(sorted(review_tags.split_tags(row.get("zotero_collections"))))
        groups.setdefault(f"{key}|{corpus}", []).append(
            (index, year, _text(row, "DOI"))
        )
    causes = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        # The latest version wins; a DOI breaks ties (the published one).
        latest = max(members, key=lambda m: (m[1], bool(m[2])))
        for index, year, _ in members:
            if index != latest[0]:
                causes[index] = (
                    f"older version ({year or '?'}) of a paper of {latest[1] or '?'}"
                )
    return causes


def metric_value(row: dict, metric: str, column: str = "") -> float | None:
    """The value of ``metric`` for the paper ``row`` (None: unknown)."""
    from scilex.pipeline.venue_ranking import RANK_SCORES

    columns = (column,) if metric == "column" else METRICS.get(metric, ("", ()))[1]
    for name in columns:
        value = row.get(name) if name else None
        if not is_valid(value):
            continue
        if metric == "venue_rank":
            score = RANK_SCORES.get(str(value).strip().upper())
            if score is not None:
                return score
            continue
        number = _number(value)
        if number is not None:
            return number
    return None


def _label(condition: dict) -> str:
    metric = condition.get("metric", "")
    if metric == "column":
        return str(condition.get("column") or "column")
    return METRICS.get(metric, (metric,))[0].split(" (")[0]


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(number) else float(number)


def _fmt(value: float) -> str:
    return f"{value:g}" if abs(value) >= 0.01 or value == 0 else f"{value:.2e}"


def metric_cutoffs(criterion: Criterion, data: pd.DataFrame) -> dict[int, float]:
    """For each ranking condition (top % / top N), the lowest value it keeps.

    Computed over the papers whose metric is known: ``{condition index: value}``.
    """
    cutoffs = {}
    conditions = (criterion.params or {}).get("conditions") or []
    records = data.to_dict("records")
    for i, condition in enumerate(conditions):
        if condition.get("op") not in RANK_OPERATORS:
            continue
        metric, column = condition.get("metric", ""), condition.get("column", "")
        values = sorted(
            (
                v
                for row in records
                if (v := metric_value(row, metric, column)) is not None
            ),
            reverse=True,
        )
        size = _number(condition.get("value")) or 0
        if not values or size <= 0:
            continue
        keep = (
            math.ceil(len(values) * min(size, 100) / 100)
            if condition["op"] == "top_percent"
            else int(size)
        )
        cutoffs[i] = values[min(max(keep, 1), len(values)) - 1]
    return cutoffs


UNKNOWN_VALUE = object()  # the paper has no value for the metric
UNDECIDED = object()  # a ranking condition judged on one paper alone


def _condition_failure(condition: dict, row: dict, cutoff: float | None):
    """Why the paper fails ``condition`` (a text), None when it passes, or
    :data:`UNKNOWN_VALUE` / :data:`UNDECIDED`."""
    op = condition.get("op", ">=")
    label = _label(condition)
    value = metric_value(row, condition.get("metric", ""), condition.get("column", ""))
    if value is None:
        return UNKNOWN_VALUE
    threshold = _number(condition.get("value"))
    if op == "age_aware":
        from scilex.pipeline.citation_filter import (
            calculate_paper_age_months,
            calculate_required_citations,
        )

        months = calculate_paper_age_months(row.get("date"))
        required = calculate_required_citations(months)
        if value < required:
            age = f"{months} months old" if months is not None else "age unknown"
            return f"{label} {_fmt(value)} < {required} required ({age})"
        return None
    if op in RANK_OPERATORS:
        if cutoff is None:
            return UNDECIDED
        if value < cutoff:
            where = (
                f"top {_fmt(threshold or 0)} %"
                if op == "top_percent"
                else f"top {int(threshold or 0)}"
            )
            return f"{label} {_fmt(value)} not in the {where} (>= {_fmt(cutoff)})"
        return None
    if threshold is None:
        return None
    if op == ">=" and value < threshold:
        return f"{label} {_fmt(value)} < {_fmt(threshold)}"
    if op == "<=" and value > threshold:
        return f"{label} {_fmt(value)} > {_fmt(threshold)}"
    return None


def _metric_cause(
    criterion: Criterion, row: dict, cutoffs: dict[int, float] | None
) -> str | None:
    """``match: all`` excludes when one condition fails; ``any`` when all fail.

    A paper whose metric is unknown passes that condition unless
    ``missing: exclude``. Without ``cutoffs`` (one paper alone), ranking
    conditions are not judged (they pass).
    """
    params = criterion.params or {}
    conditions = params.get("conditions") or []
    exclude_unknown = params.get("missing") == "exclude"
    match_any = params.get("match", "all") == "any"
    failures = []
    for i, condition in enumerate(conditions):
        if not condition.get("metric"):
            continue
        failure = _condition_failure(condition, row, (cutoffs or {}).get(i))
        if failure is UNKNOWN_VALUE:
            failure = f"{_label(condition)} unknown" if exclude_unknown else None
        elif failure is UNDECIDED:
            failure = None
        if match_any:
            if failure is None:
                return None
            failures.append(failure)
        elif failure is not None:
            return failure
    return " and ".join(failures) if match_any and failures else None


def cause_of(
    criterion: Criterion, row: dict, context: dict | None = None
) -> str | None:
    """Why ``criterion`` excludes the paper ``row`` (None: it passes).

    ``duplicates`` is checked on the whole corpus (see :func:`test`); the
    ranking conditions of ``metric`` (top % / top N) need ``context``
    (:func:`metric_cutoffs`), else they are not judged.
    """
    params = criterion.params or {}
    kind = criterion.kind
    if kind == "metric":
        return _metric_cause(criterion, row, context)
    if kind == "period":
        year = extract_year(row.get("date"))
        start, end = params.get("start"), params.get("end")
        if year is None:
            return None if not params.get("exclude_unknown") else "no year"
        if (start and year < int(start)) or (end and year > int(end)):
            return f"published in {year}, outside {start}-{end}"
        return None
    text = f"{_text(row, 'title')} {_text(row, 'abstract')}"
    if kind == "coherence":
        lowered = text.lower()
        for group in params.get("groups") or []:
            terms = [str(t).lower() for t in group if str(t).strip()]
            if terms and not any(t in lowered for t in terms):
                return f"no term of ({' OR '.join(group)}) in the title or abstract"
        return None
    if kind == "language":
        allowed = {str(lang).lower()[:2] for lang in params.get("languages") or ["en"]}
        language = _text(row, "language").lower()[:2]
        if language:
            return None if language in allowed else f"written in {language}"
        if "en" in allowed and text.strip():
            words = len(text.split())
            hits = len(_ENGLISH.findall(text))
            if words >= 8 and hits / words < 0.04:
                return "not written in English (guessed from the text)"
        return None
    if kind == "access":
        from scilex.gui.services.coverage import RESTRICTED, UNKNOWN, access_of

        access = access_of(row)
        if access == RESTRICTED:
            return "behind a paywall"
        if access == UNKNOWN and params.get("exclude_unknown"):
            return "access unknown"
        return None
    if kind == "peer_review":
        item_type = _text(row, "itemType").lower()
        doi = _text(row, "DOI").lower()
        if item_type in PREPRINT_TYPES or "10.48550/arxiv" in doi:
            return f"not peer-reviewed ({item_type or 'arXiv preprint'})"
        return None
    if kind == "doi":
        doi = _text(row, "DOI")
        return None if doi and normalize_doi(doi) else "no DOI"
    if kind == "quality":
        from scilex.gui.services.consolidate import filter_reasons

        rules = dict(params.get("quality_filters") or {})
        # The year range is criterion C1's job: only the quality rules here.
        rules["validate_year_range"] = False
        reasons = filter_reasons(row, {"quality_filters": rules})
        return "; ".join(reasons) if reasons else None
    if kind == "text":
        pattern = str(params.get("pattern") or "")
        if pattern and re.search(pattern, text, re.IGNORECASE):
            return f"matches {pattern!r}"
        return None
    return None


def exception_of(criterion: Criterion, row: dict, included: bool) -> str | None:
    """Why the paper is kept despite the criterion (None: no exception)."""
    tags = review_tags.split_tags(row.get("tags"))
    if f"{KEEP}:{criterion.id}".casefold() in {t.casefold() for t in tags}:
        return f"{KEEP}:{criterion.id} tag"
    if review_tags.SCREENED_KEEP.casefold() in {t.casefold() for t in tags}:
        return "in a screened-results collection"
    if included:
        return "included in ③ Screen"
    if criterion.keep_types:
        from scilex.paper_types import effective_types

        for kind in effective_types(row):
            if kind in criterion.keep_types:
                return f"{kind} paper"
    return None


def test(
    criterion: Criterion, data: pd.DataFrame, included: set[str] | None = None
) -> TestResult:
    """What ``criterion`` would exclude in ``data`` (people's discards left out)."""
    from scilex.gui.services.screening import paper_key

    included = included or set()
    result = TestResult(criterion)
    duplicates = _duplicates_causes(data) if criterion.kind == "duplicates" else {}
    cutoffs = metric_cutoffs(criterion, data) if criterion.kind == "metric" else None
    if criterion.kind == "metric":
        result.notes = coverage_notes(criterion, data)
    for index, row in zip(data.index, data.to_dict("records"), strict=True):
        state = review_tags.workflow(row.get("tags"))
        if any(
            not who.startswith(review_tags.FILTER_PREFIX) for who in state.deleted_by
        ):
            continue  # discarded by a person: not ours to judge
        result.checked += 1
        cause = (
            duplicates.get(index)
            if criterion.kind == "duplicates"
            else cause_of(criterion, row, cutoffs)
        )
        if cause is None:
            continue
        key = paper_key(row)
        paper = Excluded(index, key, _text(row, "title"), cause)
        if exception_of(criterion, row, key in included):
            result.spared.append(paper)
        else:
            result.excluded.append(paper)
    return result


PASS, EXCLUDED, KEPT = "pass", "excluded", "kept"


def eligibility(
    criteria: list[Criterion], data: pd.DataFrame, included: set[str] | None = None
) -> dict[str, dict[str, tuple[str, str]]]:
    """Each paper's verdict for each enabled criterion, judged on the corpus.

    ``{paper key: {criterion id: (state, cause)}}``, state ``excluded`` or
    ``kept`` (by an exception); a criterion the paper passes is absent.
    Papers discarded by a person are not judged.
    """
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for criterion in criteria:
        if not criterion.enabled:
            continue
        try:
            result = test(criterion, data, included)
        except Exception:  # a broken rule (bad pattern…): not judged
            continue
        for state, papers in ((EXCLUDED, result.excluded), (KEPT, result.spared)):
            for paper in papers:
                verdicts.setdefault(paper.paper_key, {})[criterion.id] = (
                    state,
                    paper.cause,
                )
    return verdicts


def coverage_notes(criterion: Criterion, data: pd.DataFrame) -> list[str]:
    """How many papers have each metric of a ``metric`` criterion."""
    notes = []
    records = data.to_dict("records")
    seen = set()
    for condition in (criterion.params or {}).get("conditions") or []:
        key = (condition.get("metric"), condition.get("column", ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        known = sum(metric_value(row, key[0], key[1]) is not None for row in records)
        note = f"{_label(condition)}: known for {known} of {len(records)} papers"
        if known < len(records) and key[0] != "column":
            note += " (Enrich › Citation metrics computes citations, PageRank…)"
        notes.append(note + ".")
    return notes


def _criterion_tags(tags, criterion_id: str) -> list[str]:
    prefix = review_tags.filter_tag(criterion_id).casefold()
    return [
        t
        for t in review_tags.split_tags(tags)
        if t.casefold() == prefix or t.casefold().startswith(prefix + " ")
    ]


def apply(review, criteria: list[Criterion]) -> dict[str, int]:
    """Tag the papers the enabled criteria exclude; untag those that pass now.

    Returns ``{criterion id: papers excluded}``.
    """
    from scilex.gui.services import journal, results_store, screening
    from scilex.gui.services.extend import read_results

    data = read_results(review.results_path)
    if data is None:
        raise ValueError("The review has no papers yet.")
    included = {
        key
        for key, decision in screening.load_decisions(review).items()
        if decision.decision == screening.INCLUDE
    }
    before = data.copy()
    if "tags" not in data.columns:
        data["tags"] = ""
        before["tags"] = ""
    data["tags"] = data["tags"].astype(object)
    counts = {}
    for criterion in criteria:
        result = test(criterion, data, included) if criterion.enabled else None
        excluded = {p.index: p.cause for p in result.excluded} if result else {}
        counts[criterion.id] = len(excluded)
        for index in data.index:
            old = _criterion_tags(data.at[index, "tags"], criterion.id)
            new = (
                [review_tags.filter_tag(f"{criterion.id} {excluded[index]}")]
                if index in excluded
                else []
            )
            if old != new:
                data.at[index, "tags"] = review_tags.with_tags(
                    data.at[index, "tags"], new, old
                )
    results_store.write_changes(review.results_path, before, data)
    from scilex.gui.services import versions

    journal.append(
        review.folder,
        "criteria",
        # the criteria version applied: DELETED_BY:filter:<C> tags point to it (SX-8)
        used={
            "criteria.yml sha256": versions.ensure_current(review.folder, "criteria")
        },
        params={
            "category": "filtering",
            "criteria": [c.id for c in criteria if c.enabled],
        },
        generated={"excluded": counts},
        message="Eligibility criteria applied: "
        + ", ".join(f"{cid} {n}" for cid, n in counts.items())
        + ".",
    )
    return counts


def markdown_table(criteria: list[Criterion]) -> str:
    """The criteria table, as written in the review's protocol."""
    lines = [
        "| Criteria | Exclusion (EC) | Inclusion (IC) | Exceptions (Ex) |",
        "|---|---|---|---|",
    ]
    for c in criteria:
        if c.enabled:
            cells = [
                f"{c.id} – {c.name}",
                c.exclusion,
                c.inclusion,
                c.exceptions or "/",
            ]
            lines.append("| " + " | ".join(x.replace("|", "/") for x in cells) + " |")
    return "\n".join(lines) + "\n"


def excluded_by_criterion(tags_column) -> dict[str, int]:
    """Papers excluded per criterion id, from ``DELETED_BY:filter:<id> …`` tags."""
    counts: dict[str, int] = {}
    prefix = review_tags.filter_tag("").casefold()
    for value in tags_column:
        ids = set()
        for tag in review_tags.split_tags(value):
            if tag.casefold().startswith(prefix):
                reason = tag[len(prefix) :].strip()
                ids.add(reason.split(" ")[0] if reason else "?")
        for cid in ids:
            counts[cid] = counts.get(cid, 0) + 1
    return counts


# Metric -> word of an impact-filter code (``IF-Citation``).
_METRIC_WORDS = {"citations": "citation", "cited_in_corpus": "citation"}


def exclusion_codes(criteria: list[Criterion], values: list[str]) -> dict[str, str]:
    """Criterion id -> exclusion code of the annotation grid.

    ``values`` are the grid's ``EXCLUSION`` values (``C3-Language``,
    ``IF-Citation``…). A criterion takes the value starting with its id
    (``C3`` -> ``C3-Language``); a metric criterion the ``IF-`` value naming its
    metric (citations -> ``IF-Citation``). Others keep their id.
    """
    codes: dict[str, str] = {}
    for criterion in criteria:
        prefix = f"{criterion.id}-".casefold()
        code = next((v for v in values if v.casefold().startswith(prefix)), None)
        if code is None and criterion.kind == "metric":
            words = {
                _METRIC_WORDS.get(c.get("metric", ""), c.get("metric", ""))
                for c in criterion.params.get("conditions", [])
                if isinstance(c, dict)
            } - {""}
            code = next(
                (
                    v
                    for v in values
                    if v.casefold().startswith("if-")
                    and any(v[3:].casefold().startswith(w.casefold()) for w in words)
                ),
                None,
            )
        codes[criterion.id] = code or criterion.id
    return codes


def review_codes(folder: Path) -> tuple[dict[str, str], list[str]]:
    """Exclusion codes (:func:`exclusion_codes`) and protocol order of a review.

    The codes come from the ``EXCLUSION`` dimension of the review's annotation
    grid; without one, the criterion ids are the codes.
    """
    from scilex.tagging.grid import dimension_values, load_grid

    try:
        criteria = load(Path(folder))
    except Exception:  # an unreadable criteria.yml: ids only
        return {}, []
    values: list[str] = []
    grid = Path(folder) / "annotation_grid.csv"
    if grid.is_file():
        try:
            values = dimension_values(load_grid(grid), "EXCLUSION")
        except Exception:
            values = []
    return exclusion_codes(criteria, values), [c.id for c in criteria]
