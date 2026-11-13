"""Annotation grid: the dimensions annotators tag papers with in Zotero.

A grid is a CSV with one row per dimension (``tag`` column, e.g. ``SAT_TASK``)
and one column per paper type (``datasets``, ``surveys``, ``models``) marked
``X`` when the dimension applies to that type. Other columns (``detail`` = the
question to answer, comments, counts...) are kept as they are.

In Zotero, a paper is annotated with ``DIMENSION:Value`` tags; ``DIMENSION:?``
marks a dimension still to fill in. Tags written by SciLEx itself (keywords,
scores, presence flags) are "automation" tags, never part of a grid.

Used by the ``init_annotation_grid`` / ``report_annotations`` commands and by
the desktop app's Annotate step.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

PAPER_TYPES: tuple[str, ...] = ("datasets", "surveys", "models")
ALL_TYPES = "all"  # pseudo type: every dimension of the grid
TAG_COLUMN = "tag"
DETAIL_COLUMN = "detail"
PLACEHOLDER = "?"
GRID_FILENAME = "annotation_grid.csv"
DEFAULT_GRID_PATH = Path(__file__).with_name("TAG_LIST_FINAL - DIM_ANNOTATIONS.csv")

# Tags written by SciLEx when pushing to Zotero (see Zotero/zotero_api.py and
# crawlers/aggregate_parallel.py). Edit if the push logic grows new families.
AUTOMATION_EXACT_TAGS = frozenset(
    {"HavePDF", "HaveHF", "HavePWC", "HaveGithub", "SciLexCollected"}
)
# Workflow tags (scilex.review_tags), screening decisions pushed by the Zotero
# sync, and citation metrics (scilex.citation_metrics): written by SciLEx, so
# never annotation codes (grid deduction, tag analysis, Overview, knowledge graph).
WORKFLOW_TAG_PREFIXES = (
    "ANNOT:",
    "ANNOT_VALID_BY:",
    "DELETED_BY:",
    "AGREEMENT_COPY:",
    "SCREEN:",
    "KEEP:",  # exception to an eligibility criterion (KEEP:C1)
)
METRIC_TAG_PREFIXES = (
    "CITATIONS:",
    "REFERENCES:",
    "CITATIONS_PER_YEAR:",
    "CITED_IN_CORPUS:",
    "PAGERANK:",
    "QUALITY:",
    "VENUE_RANK:",
)
AUTOMATION_PREFIXES = (
    "QUALI_SCORE:",
    "REL_SCORE:",
    "CITAT:",
    "BK:",  # bonus keywords found in the title/abstract (pipeline.bonus_keywords)
    "GITHUB_STARS:",  # Papers with Code enrichment (PapersWithCode.tag_formatter)
    "CITED_BY_DATASET:",
    *WORKFLOW_TAG_PREFIXES,
    *METRIC_TAG_PREFIXES,
)
AUTOMATION_REGEXES = (
    re.compile(r"^Collect_KW\d*:"),
    # LLM proposals waiting for a person (scilex.tagging.auto_tags): never codes.
    re.compile(r"^[^:\s]+-AUTO:", re.IGNORECASE),
)
COLLECT_KEYWORD_TAG = re.compile(r"^Collect_KW(\d+):(.+)$")


def is_automation_tag(tag: str) -> bool:
    """Return True for a tag SciLEx writes itself (never an annotation)."""
    if tag in AUTOMATION_EXACT_TAGS:
        return True
    if tag.startswith(AUTOMATION_PREFIXES):
        return True
    return any(rx.match(tag) for rx in AUTOMATION_REGEXES)


# ---------------------------------------------------------------------------
# Grid files
# ---------------------------------------------------------------------------


def empty_grid() -> pd.DataFrame:
    """Return a grid with the standard columns and no dimension."""
    return pd.DataFrame(columns=[TAG_COLUMN, DETAIL_COLUMN, *PAPER_TYPES])


def normalize_grid(grid: pd.DataFrame) -> pd.DataFrame:
    """Return ``grid`` cleaned: upper-case unique tags, standard columns present.

    Raises:
        ValueError: If there is no ``tag`` column.
    """
    if TAG_COLUMN not in grid.columns:
        raise ValueError(f"An annotation grid needs a '{TAG_COLUMN}' column")
    grid = grid.copy().fillna("")
    for column in (DETAIL_COLUMN, *PAPER_TYPES):
        if column not in grid.columns:
            grid[column] = ""
    grid[TAG_COLUMN] = grid[TAG_COLUMN].astype(str).str.strip().str.upper()
    grid = grid[grid[TAG_COLUMN] != ""]
    grid = grid.drop_duplicates(subset=TAG_COLUMN, keep="first")
    return grid.reset_index(drop=True)


def load_grid(path: str | Path) -> pd.DataFrame:
    """Read a grid CSV (any of ``,`` ``;`` or tab as separator)."""
    grid = pd.read_csv(path, sep=None, engine="python", dtype=str)
    return normalize_grid(grid)


def dimension_values(grid: pd.DataFrame, dimension: str) -> list[str]:
    """Values a grid lists for ``dimension`` (``Allowed values`` column, else
    the ``Values: a, b`` end of its detail); none for an unknown dimension."""
    rows = grid[grid[TAG_COLUMN].astype(str).str.upper() == dimension.upper()]
    if rows.empty:
        return []
    row = rows.iloc[0]
    text = str(row.get("Allowed values", "") or "").strip()
    if not text:
        found = re.search(r"Values:\s*(.+)$", str(row.get(DETAIL_COLUMN, "")))
        text = found.group(1) if found else ""
    return [v.strip() for v in re.split(r"[,·]", text) if v.strip()]


def save_grid(grid: pd.DataFrame, path: str | Path) -> Path:
    """Write ``grid`` as a comma-separated CSV and return its path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_grid(grid).to_csv(path, index=False)
    return path


def tags_for_type(grid: pd.DataFrame, paper_type: str) -> list[str]:
    """Return the dimensions that apply to ``paper_type`` (``"all"``: every one)."""
    grid = normalize_grid(grid)
    if paper_type == ALL_TYPES:
        return grid[TAG_COLUMN].tolist()
    if paper_type not in grid.columns:
        raise ValueError(f"Unknown paper type: {paper_type}")
    marked = grid[paper_type].astype(str).str.upper().str.contains("X")
    return grid.loc[marked, TAG_COLUMN].tolist()


def load_tags_from_csv(csv_path: str) -> dict[str, list[str]]:
    """Return ``{paper type: [dimension, ...]}`` for the grid at ``csv_path``."""
    grid = load_grid(csv_path)
    return {paper_type: tags_for_type(grid, paper_type) for paper_type in PAPER_TYPES}


def merge_grids(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Return ``base`` plus the dimensions of ``extra`` it does not have yet."""
    base, extra = normalize_grid(base), normalize_grid(extra)
    new_rows = extra[~extra[TAG_COLUMN].isin(base[TAG_COLUMN])]
    return normalize_grid(pd.concat([base, new_rows], ignore_index=True))


# ---------------------------------------------------------------------------
# Tags of one paper
# ---------------------------------------------------------------------------


def normalize_tag_value(value: str) -> str:
    """Normalize a tag value: title case without spaces (``deep learning`` -> ``DeepLearning``)."""
    return "".join(x for x in value.title() if not x.isspace())


def process_paper_tags(
    paper: dict, expected_tags: list[str], keep_other_tags: bool = False
) -> list[str]:
    """Return the tags of ``paper`` once the grid ``expected_tags`` is applied.

    Grid dimensions are normalized (``DIM:value``), and every dimension the
    paper lacks gets a ``DIM:?`` placeholder.

    Args:
        paper: Zotero item (``{"data": {"tags": [{"tag": ...}]}}``).
        expected_tags: Dimensions of the grid for this paper type.
        keep_other_tags: Keep tags outside the grid (SciLEx tags, free
            keywords, other dimensions). When False, only grid tags remain,
            as the original ``init_annotation_grid`` command does.
    """
    expected = {tag.upper() for tag in expected_tags}
    corrected: list[str] = []
    others: list[str] = []
    for tag_entry in paper.get("data", {}).get("tags", []):
        tag = str(tag_entry.get("tag", "")).strip()
        if not tag:
            continue
        dimension, sep, value = tag.partition(":")
        if sep and dimension.strip().upper() in expected:
            if PLACEHOLDER in value:
                continue  # re-added below if the dimension is still empty
            new_tag = (
                f"{dimension.strip().upper()}:{normalize_tag_value(value)}".strip()
            )
            if new_tag not in corrected:
                corrected.append(new_tag)
        elif keep_other_tags and tag not in others:
            others.append(tag)

    filled = {tag.partition(":")[0] for tag in corrected}
    for dimension in expected_tags:
        if dimension.upper() not in filled:
            corrected.append(f"{dimension.upper()}:{PLACEHOLDER}")
    return others + corrected if keep_other_tags else corrected


def is_paper(item: dict) -> bool:
    """Return True for a Zotero item that is a paper (not an attachment or note)."""
    data = item.get("data", {})
    return data.get("itemType") not in ("attachment", "note") and "title" in data


def plan_grid_updates(
    items: Iterable[dict], expected_tags: list[str], keep_other_tags: bool = True
) -> dict[str, tuple[int, list[str]]]:
    """Return ``{item key: (version, new tags)}`` for the papers whose tags change."""
    updates: dict[str, tuple[int, list[str]]] = {}
    for item in items:
        if not is_paper(item):
            continue
        current = [t.get("tag", "") for t in item["data"].get("tags", [])]
        new_tags = process_paper_tags(item, expected_tags, keep_other_tags)
        if sorted(new_tags) != sorted(current):
            version = item.get("version", item["data"].get("version", 0))
            updates[item["key"]] = (version, new_tags)
    return updates


# ---------------------------------------------------------------------------
# Deduce a grid and keywords from an annotated library
# ---------------------------------------------------------------------------


def annotation_dimensions(items: Iterable[dict]) -> dict[str, Counter]:
    """Return ``{dimension: Counter(values)}`` of the structured annotation tags."""
    dimensions: dict[str, Counter] = defaultdict(Counter)
    for item in items:
        if not is_paper(item):
            continue
        for tag_entry in item["data"].get("tags", []):
            tag = str(tag_entry.get("tag", "")).strip()
            if not tag or is_automation_tag(tag):
                continue
            dimension, sep, value = tag.partition(":")
            dimension = dimension.strip().upper()
            if sep and dimension and " " not in dimension:
                dimensions[dimension][value.strip()] += 1
    return dimensions


def deduce_grid(items: Iterable[dict], min_papers: int = 1) -> pd.DataFrame:
    """Build a grid from the ``DIMENSION:Value`` annotations of ``items``.

    Each dimension used on at least ``min_papers`` papers becomes a row that
    applies to every paper type; ``detail`` lists its most frequent values.
    """
    rows = []
    for dimension, values in annotation_dimensions(items).items():
        filled = {v: n for v, n in values.items() if v and v != PLACEHOLDER}
        uses = sum(values.values())
        if uses < min_papers:
            continue
        examples = ", ".join(v for v, _ in Counter(filled).most_common(5))
        rows.append(
            {
                TAG_COLUMN: dimension,
                DETAIL_COLUMN: f"Values seen: {examples}" if examples else "",
                **dict.fromkeys(PAPER_TYPES, "X"),
                "nb": uses,
            }
        )
    if not rows:
        return empty_grid()
    grid = pd.DataFrame(rows).sort_values("nb", ascending=False)
    return normalize_grid(grid)


def deduce_keyword_groups(items: Iterable[dict]) -> list[list[str]]:
    """Return the keyword groups SciLEx collected with, from ``Collect_KW<n>:term`` tags.

    Group ``n`` holds the distinct terms of ``Collect_KW<n>`` in order of
    frequency; an empty list means the papers were not collected by SciLEx.
    """
    groups: dict[int, Counter] = defaultdict(Counter)
    for item in items:
        if not is_paper(item):
            continue
        for tag_entry in item["data"].get("tags", []):
            match = COLLECT_KEYWORD_TAG.match(str(tag_entry.get("tag", "")).strip())
            if match:
                groups[int(match.group(1))][match.group(2).strip()] += 1
    return [
        [term for term, _ in groups[index].most_common()]
        for index in sorted(groups)
        if groups[index]
    ]
