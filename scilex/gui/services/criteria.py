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
}
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
        seen.add(criterion.id)
    path = path_of(folder)
    path.write_text(
        yaml.safe_dump(
            [asdict(c) for c in criteria], sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
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


def cause_of(criterion: Criterion, row: dict) -> str | None:
    """Why ``criterion`` excludes the paper ``row`` (None: it passes).

    ``duplicates`` is checked on the whole corpus (see :func:`test`).
    """
    params = criterion.params or {}
    kind = criterion.kind
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
    if included:
        return "included in ③ Screen"
    if criterion.keep_types:
        from scilex.paper_types import effective_type

        kind = effective_type(row)
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
            else cause_of(criterion, row)
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
    journal.append(
        review.folder,
        "criteria",
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
