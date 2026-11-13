"""Analysis of the annotation tags (``DIMENSION:value``) of the papers.

Annotators tag papers in Zotero with ``DIMENSION:value`` tags (see
:mod:`scilex.tagging.grid`). This module turns those tags into statistics:

1. **Clean values.** Values that differ only by case, spaces or punctuation
   (``CIDOC-CRM``, ``CIDOC CRM``, ``CidocCrm``) are one value, shown with its
   most frequent spelling. A synonyms table (``tag_synonyms.csv``: columns
   ``dimension``, ``value``, ``merge_into``; ``*`` as dimension for all) merges
   further values, and close spellings are proposed as merges.
2. **Coverage per dimension.** Papers with a value, with an explicit "none"
   (``None``, ``N/A``...), still to fill in (``DIM:?``) or without the
   dimension; the frequency of each value, and per year.
3. **Crossing two dimensions.** For each pair of the most used dimensions, the
   number of papers per pair of values: empty cells are the gaps of the corpus.

Tags SciLEx writes itself (keywords, scores, presence flags) are ignored.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from scilex.constants import extract_year, split_semicolon_field  # noqa: E402
from scilex.tagging.grid import is_automation_tag  # noqa: E402

OUTPUT_DIRNAME = "annotation_analysis"
REPORT_FILENAME = "annotation_report.md"
SYNONYMS_FILENAME = "tag_synonyms.csv"
VALUES_CSV = "tag_values.csv"
SUGGESTIONS_CSV = "tag_merge_suggestions.csv"
COOCCURRENCE_CSV = "tag_cooccurrence.csv"
COVERAGE_PNG = "coverage.png"

# Values meaning "the paper has none" (an answer, unlike "?" = not filled in yet).
NONE_VALUES = frozenset({"none", "na", "n/a", "null", "nil", "-", "aucun", "aucune"})
NONE_KEYS = frozenset(k for k in (re.sub(r"[\W_]+", "", v) for v in NONE_VALUES) if k)
TOP_VALUES = 15
MIN_COMMON_PAPERS = 2  # a crossing needs this many papers with both dimensions
DEFAULT_SIMILARITY = 88
MAX_SUGGESTIONS = 200

COLOURS = {
    "value": "#4C72B0",
    "none": "#8C8C8C",
    "pending": "#DD8452",
    "absent": "#E5E5E5",
}


def value_key(value: str) -> str:
    """Comparison key of a value: lower case, letters and digits only."""
    return re.sub(r"[\W_]+", "", str(value).casefold())


def dimension_name(raw: str) -> str:
    """Normalized dimension name (``LifecycleStep`` and ``LIFECYCLESTEP`` are one)."""
    return raw.strip().upper()


def parse_annotation(tag: str) -> tuple[str, str] | None:
    """Return ``(DIMENSION, value)`` of an annotation tag, None for other tags."""
    tag = str(tag).strip()
    if not tag or is_automation_tag(tag):
        return None
    dimension, sep, value = tag.partition(":")
    dimension = dimension.strip()
    if not sep or not dimension or " " in dimension:
        return None
    return dimension_name(dimension), value.strip()


def _safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower() or "dimension"


# ---------------------------------------------------------------------------
# Synonyms
# ---------------------------------------------------------------------------


def load_synonyms(path: Path | None) -> dict[tuple[str, str], str]:
    """Read ``tag_synonyms.csv``: ``{(DIMENSION or "*", value key): target}``.

    A missing file means no synonym. Rows without a value or a target are skipped.
    """
    if path is None or not Path(path).is_file():
        return {}
    frame = pd.read_csv(path, dtype=str, sep=None, engine="python").fillna("")
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = {"value", "merge_into"} - set(frame.columns)
    if missing:
        raise ValueError(
            f"{Path(path).name} needs the columns dimension, value, merge_into "
            f"(missing: {', '.join(sorted(missing))})."
        )
    synonyms: dict[tuple[str, str], str] = {}
    for row in frame.to_dict("records"):
        value, target = row["value"].strip(), row["merge_into"].strip()
        if not value or not target:
            continue
        dimension = dimension_name(row.get("dimension", "") or "*")
        synonyms[(dimension, value_key(value))] = target
    return synonyms


MERGE_COLUMNS = ["dimension", "value", "merge_into"]


def write_synonyms_template(path: Path) -> Path:
    """Create an empty synonyms table with its header (does not overwrite)."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(",".join(MERGE_COLUMNS) + "\n", encoding="utf-8")
    return path


def read_merge_table(path: Path | None) -> pd.DataFrame:
    """Read a ``dimension,value,merge_into`` table (synonyms or rejected merges)."""
    if path is None or not Path(path).is_file():
        return pd.DataFrame(columns=MERGE_COLUMNS)
    frame = pd.read_csv(path, dtype=str, sep=None, engine="python").fillna("")
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    for column in MERGE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[MERGE_COLUMNS]


def _row_id(row: dict) -> tuple[str, str]:
    return dimension_name(row.get("dimension") or "*"), value_key(row.get("value", ""))


def add_merge_rows(path: Path, rows: list[dict]) -> int:
    """Add ``rows`` to a merge table, replacing a row for the same value.

    Returns the number of rows added or changed.
    """
    table = read_merge_table(path)
    new = {
        _row_id(row): {
            "dimension": dimension_name(row.get("dimension") or "*"),
            "value": str(row.get("value", "")).strip(),
            "merge_into": str(row.get("merge_into", "")).strip(),
        }
        for row in rows
        if str(row.get("value", "")).strip() and str(row.get("merge_into", "")).strip()
    }
    kept = [r for r in table.to_dict("records") if _row_id(r) not in new]
    out = pd.DataFrame([*kept, *new.values()], columns=MERGE_COLUMNS)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return len(new)


def remove_merge_rows(path: Path, rows: list[dict]) -> int:
    """Remove the rows for the values of ``rows`` from a merge table."""
    table = read_merge_table(path)
    gone = {_row_id(row) for row in rows}
    kept = [r for r in table.to_dict("records") if _row_id(r) not in gone]
    pd.DataFrame(kept, columns=MERGE_COLUMNS).to_csv(path, index=False)
    return len(table) - len(kept)


def load_rejected(path: Path | None) -> set[tuple[str, str, str]]:
    """Merges the user refused: ``{(DIMENSION, value key, target key)}``."""
    return {
        (
            dimension_name(r["dimension"] or "*"),
            value_key(r["value"]),
            value_key(r["merge_into"]),
        )
        for r in read_merge_table(path).to_dict("records")
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass
class DimensionStats:
    """Use of one dimension over the papers."""

    name: str
    with_value: int = 0
    with_none: int = 0
    pending: int = 0
    absent: int = 0
    values: Counter = field(default_factory=Counter)  # label -> papers
    variants: dict[str, Counter] = field(default_factory=dict)  # label -> spellings
    by_year: dict[str, Counter] = field(default_factory=dict)  # label -> year -> papers
    in_grid: bool = False

    @property
    def answered(self) -> int:
        """Papers with a value or an explicit none."""
        return self.with_value + self.with_none


@dataclass
class MergeSuggestion:
    """Two spellings of a dimension that are probably the same value."""

    dimension: str
    value: str
    merge_into: str
    similarity: float
    papers: int


@dataclass
class TagAnalysis:
    """Result of :func:`analyse_tags`."""

    papers: int
    annotated: int
    dimensions: dict[str, DimensionStats]
    paper_values: list[dict[str, set[str]]]  # per paper: dimension -> labels
    suggestions: list[MergeSuggestion]
    synonyms_used: int = 0

    def ranked(self) -> list[DimensionStats]:
        """Dimensions by number of papers answered, most used first."""
        return sorted(
            self.dimensions.values(),
            key=lambda d: (-d.answered, -d.pending, d.name),
        )


def _resolve(
    dimension: str, raw: str, synonyms: dict[tuple[str, str], str]
) -> tuple[str, bool]:
    """Return the comparison key of ``raw`` once synonyms are applied."""
    key = value_key(raw)
    for scope in (dimension, "*"):
        target = synonyms.get((scope, key))
        if target is not None:
            return value_key(target), True
    return key, False


def analyse_tags(
    frame: pd.DataFrame,
    synonyms: dict[tuple[str, str], str] | None = None,
    grid_dimensions: list[str] | None = None,
    similarity: float = DEFAULT_SIMILARITY,
    rejected: set[tuple[str, str, str]] | None = None,
) -> TagAnalysis:
    """Analyse the ``tags`` column of an aggregated-results table.

    Args:
        frame: Results table; its ``tags`` column holds ``;``-separated tags
            and its ``date`` column the publication date.
        synonyms: From :func:`load_synonyms`.
        grid_dimensions: Dimensions of the annotation grid, listed even when
            no paper uses them yet.
        similarity: Minimal similarity (0-100) of two spellings proposed as a merge.
    """
    synonyms = synonyms or {}
    tags_column = frame["tags"] if "tags" in frame.columns else pd.Series(dtype=str)
    dates = frame["date"] if "date" in frame.columns else pd.Series(dtype=str)

    # First pass: dimension -> key -> spelling counts; per paper the keys.
    spellings: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    papers_raw: list[tuple[str | None, dict[str, set[str]], set[str], set[str]]] = []
    synonyms_used: set[tuple[str, str]] = set()
    for index in range(len(frame)):
        values: dict[str, set[str]] = defaultdict(set)
        nones: set[str] = set()
        pending: set[str] = set()
        for tag in split_semicolon_field(
            tags_column.iloc[index] if len(tags_column) else None
        ):
            parsed = parse_annotation(tag)
            if parsed is None:
                continue
            dimension, raw = parsed
            if not value_key(raw) and raw not in NONE_VALUES:
                pending.add(dimension)  # "DIM:?" or "DIM:" (still to fill in)
                continue
            if raw.casefold() in NONE_VALUES or value_key(raw) in NONE_KEYS:
                nones.add(dimension)
                continue
            key, replaced = _resolve(dimension, raw, synonyms)
            if not key:
                continue
            if replaced:
                synonyms_used.add((dimension, value_key(raw)))
            spellings[dimension][key][raw] += 1
            values[dimension].add(key)
        year = extract_year(dates.iloc[index]) if len(dates) else None
        papers_raw.append((str(year) if year else None, dict(values), nones, pending))

    # Labels: a synonym target, else the most frequent spelling.
    targets = {value_key(t): t for t in synonyms.values()}
    labels: dict[str, dict[str, str]] = {
        dimension: {
            key: targets.get(key)
            or sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            for key, counts in keys.items()
        }
        for dimension, keys in spellings.items()
    }

    names = set(spellings) | {
        d for _, _, nones, pending in papers_raw for d in nones | pending
    }
    grid = [dimension_name(d) for d in grid_dimensions or []]
    names |= set(grid)
    dimensions = {name: DimensionStats(name, in_grid=name in grid) for name in names}

    paper_values: list[dict[str, set[str]]] = []
    annotated = 0
    for year, values, nones, pending in papers_raw:
        labelled = {
            dimension: {labels[dimension][key] for key in keys}
            for dimension, keys in values.items()
        }
        paper_values.append(labelled)
        annotated += bool(labelled or nones)
        for name, stats in dimensions.items():
            if name in labelled:
                stats.with_value += 1
                for label in labelled[name]:
                    stats.values[label] += 1
                    if year:
                        stats.by_year.setdefault(label, Counter())[year] += 1
            elif name in nones:
                stats.with_none += 1
            elif name in pending:
                stats.pending += 1
            else:
                stats.absent += 1
    for dimension, keys in spellings.items():
        stats = dimensions[dimension]
        for key, counts in keys.items():
            label = labels[dimension][key]
            stats.variants.setdefault(label, Counter()).update(counts)

    return TagAnalysis(
        papers=len(frame),
        annotated=annotated,
        dimensions=dimensions,
        paper_values=paper_values,
        suggestions=[
            s
            for s in suggest_merges(dimensions, similarity)
            if not _is_rejected(s, rejected or set())
        ],
        synonyms_used=len(synonyms_used),
    )


def _is_rejected(
    suggestion: MergeSuggestion, rejected: set[tuple[str, str, str]]
) -> bool:
    a, b = value_key(suggestion.value), value_key(suggestion.merge_into)
    return any(
        (scope, x, y) in rejected
        for scope in (suggestion.dimension, "*")
        for x, y in ((a, b), (b, a))
    )


# ---------------------------------------------------------------------------
# Cleaning the Zotero tags
# ---------------------------------------------------------------------------


@dataclass
class TagCleanPlan:
    """Tag changes that write every value with its canonical spelling."""

    updates: dict[str, tuple[int, list[str]]]  # item key -> (version, new tags)
    renames: Counter  # (old tag, new tag) -> papers
    papers: int


def canonical_spellings(analysis: TagAnalysis) -> dict[tuple[str, str], str]:
    """``{(DIMENSION, spelling): canonical value}`` for every merged spelling."""
    mapping: dict[tuple[str, str], str] = {}
    for stats in analysis.dimensions.values():
        for label, variants in stats.variants.items():
            for spelling in variants:
                if spelling != label:
                    mapping[(stats.name, spelling)] = label
    return mapping


def plan_tag_cleaning(items: list[dict], analysis: TagAnalysis) -> TagCleanPlan:
    """Plan the Zotero tag changes merging the spellings of ``analysis``.

    ``analysis`` must come from the same items (with the synonyms applied). The
    dimension keeps the spelling of the tag (``Tool:Metashape`` becomes
    ``Tool:MetaShape``); a paper never gets the same tag twice.
    """
    mapping = canonical_spellings(analysis)
    updates: dict[str, tuple[int, list[str]]] = {}
    renames: Counter = Counter()
    papers = 0
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") in ("attachment", "note") or "title" not in data:
            continue
        papers += 1
        current = [str(t.get("tag", "")) for t in data.get("tags", [])]
        new_tags: list[str] = []
        changed = False
        for tag in current:
            parsed = parse_annotation(tag)
            new = tag
            if parsed is not None and (target := mapping.get(parsed)) is not None:
                prefix = tag.partition(":")[0].strip()
                new = f"{prefix}:{target}"
                renames[(tag, new)] += 1
                changed = True
            if new not in new_tags:
                new_tags.append(new)
            else:
                changed = True
        if changed:
            version = item.get("version", data.get("version", 0))
            updates[item["key"]] = (version, new_tags)
    return TagCleanPlan(updates, renames, papers)


def suggest_merges(
    dimensions: dict[str, DimensionStats], similarity: float = DEFAULT_SIMILARITY
) -> list[MergeSuggestion]:
    """Propose merging close spellings of a dimension (the rarer into the more used)."""
    from rapidfuzz import fuzz

    found: list[MergeSuggestion] = []
    for stats in dimensions.values():
        labels = sorted(stats.values, key=lambda v: (-stats.values[v], v))
        keys = {label: value_key(label) for label in labels}
        for more, less in itertools.combinations(labels, 2):
            a, b = keys[more], keys[less]
            if min(len(a), len(b)) < 3:
                continue  # "3" and "4", "AI" and "AR": not spellings of one value
            score = fuzz.ratio(a, b)
            # One key inside the other ("oais" / "oaisrefmodel") is close too.
            if score < similarity and not (
                len(a) >= 4 and len(b) >= 4 and (a in b or b in a)
            ):
                continue
            found.append(
                MergeSuggestion(
                    stats.name, less, more, round(float(score), 1), stats.values[less]
                )
            )
    found.sort(key=lambda s: (-s.similarity, s.dimension, s.value))
    return found[:MAX_SUGGESTIONS]


def cooccurrence(
    analysis: TagAnalysis, first: str, second: str
) -> tuple[pd.DataFrame, int]:
    """Papers per pair of values of two dimensions, and the papers having both."""
    counts: Counter = Counter()
    common = 0
    for values in analysis.paper_values:
        if first in values and second in values:
            common += 1
            for a, b in itertools.product(values[first], values[second]):
                counts[(a, b)] += 1
    if not counts:
        return pd.DataFrame(), common
    frame = (
        pd.Series(counts).rename_axis([first, second]).unstack(fill_value=0).astype(int)
    )
    return frame, common


def crossing_pairs(
    analysis: TagAnalysis, max_dimensions: int
) -> list[tuple[str, str, pd.DataFrame, int]]:
    """Crossings of the ``max_dimensions`` most used dimensions with several values."""
    usable = [d.name for d in analysis.ranked() if len(d.values) >= 2][:max_dimensions]
    pairs = []
    for first, second in itertools.combinations(usable, 2):
        frame, common = cooccurrence(analysis, first, second)
        if common >= MIN_COMMON_PAPERS and not frame.empty:
            pairs.append((first, second, frame, common))
    return pairs


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def plot_coverage(analysis: TagAnalysis, path: Path) -> Path | None:
    """Stacked bars: per dimension, papers with a value / none / pending / absent."""
    ranked = analysis.ranked()
    if not ranked:
        return None
    names = [d.name + ("" if d.values or not d.in_grid else " (grid)") for d in ranked]
    parts = [
        ("with a value", "value", [d.with_value for d in ranked]),
        ("explicitly none", "none", [d.with_none for d in ranked]),
        ("to fill in (?)", "pending", [d.pending for d in ranked]),
        ("not tagged", "absent", [d.absent for d in ranked]),
    ]
    fig, ax = plt.subplots(figsize=(9, max(2.5, 0.38 * len(ranked) + 1.4)))
    left = np.zeros(len(ranked))
    positions = np.arange(len(ranked))
    for label, colour, counts in parts:
        ax.barh(positions, counts, left=left, color=COLOURS[colour], label=label)
        left += np.array(counts)
    ax.set_yticks(positions)
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, max(analysis.papers, 1))
    ax.set_xlabel("Papers")
    ax.set_title(
        f"Coverage of each dimension ({analysis.papers} papers)",
        fontsize=11,
        fontweight="bold",
    )
    ax.legend(fontsize=8, loc="lower right", frameon=False, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _heatmap(ax, frame: pd.DataFrame, cmap_name: str = "YlOrRd") -> None:
    data = frame.values.astype(float)
    masked = np.ma.masked_where(data == 0, data)
    cmap = plt.get_cmap(cmap_name).copy()
    cmap.set_bad("whitesmoke")
    ax.imshow(masked, aspect="auto", cmap=cmap, interpolation="nearest")
    ax.set_xticks(range(frame.shape[1]))
    ax.set_xticklabels(frame.columns, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(frame.shape[0]))
    ax.set_yticklabels(frame.index, fontsize=7)
    vmax = data.max() if data.size else 0
    for r in range(frame.shape[0]):
        for c in range(frame.shape[1]):
            value = int(data[r, c])
            if value:
                ax.text(
                    c,
                    r,
                    str(value),
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white" if value > vmax * 0.6 else "black",
                )
    ax.set_xticks(np.arange(-0.5, frame.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, frame.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1)
    ax.tick_params(which="minor", length=0)


def plot_dimension(
    stats: DimensionStats, path: Path, top: int = TOP_VALUES
) -> Path | None:
    """Most frequent values of a dimension and, when dated, their use per year."""
    if not stats.values:
        return None
    shown = [v for v, _ in sorted(stats.values.items(), key=lambda i: (-i[1], i[0]))][
        :top
    ]
    others = len(stats.values) - len(shown)
    years = sorted({y for v in shown for y in stats.by_year.get(v, {})})
    with_years = len(years) >= 2
    width = 12 if with_years else 7
    height = max(2.5, 0.32 * len(shown) + 1.6)
    if with_years:
        fig, (ax, ax_years) = plt.subplots(
            1, 2, figsize=(width, height), gridspec_kw={"width_ratios": [1, 1.4]}
        )
    else:
        fig, ax = plt.subplots(figsize=(width, height))
    counts = [stats.values[v] for v in shown]
    ax.barh(range(len(shown)), counts, color=COLOURS["value"])
    ax.set_yticks(range(len(shown)))
    ax.set_yticklabels(shown, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Papers")
    ax.spines[["top", "right"]].set_visible(False)
    for i, count in enumerate(counts):
        ax.text(count, i, f" {count}", va="center", fontsize=7)
    title = f"{stats.name}: {len(stats.values)} values on {stats.with_value} papers"
    if others > 0:
        title += f" (top {len(shown)} shown)"
    ax.set_title(title, fontsize=10, fontweight="bold", loc="left")
    if with_years:
        frame = pd.DataFrame(
            [[stats.by_year.get(v, {}).get(y, 0) for y in years] for v in shown],
            index=shown,
            columns=years,
        )
        _heatmap(ax_years, frame, "Blues")
        ax_years.set_yticklabels([])
        ax_years.set_title("Papers per year", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_crossing(
    first: str,
    second: str,
    frame: pd.DataFrame,
    common: int,
    path: Path,
    top: int = TOP_VALUES,
) -> Path:
    """Heatmap of the papers per pair of values of two dimensions."""
    rows = frame.sum(axis=1).sort_values(ascending=False).index[:top]
    columns = frame.sum(axis=0).sort_values(ascending=False).index[:top]
    shown = frame.loc[rows, columns]
    fig, ax = plt.subplots(
        figsize=(max(6, 0.5 * len(columns) + 3), max(4, 0.4 * len(rows) + 2))
    )
    _heatmap(ax, shown)
    ax.set_xlabel(second, fontsize=9)
    ax.set_ylabel(first, fontsize=9)
    empty = int((shown.values == 0).sum())
    ax.set_title(
        f"{first} × {second}: {common} papers with both "
        f"({empty} empty combinations shown)",
        fontsize=10,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Tables and report
# ---------------------------------------------------------------------------


def values_table(analysis: TagAnalysis) -> pd.DataFrame:
    """One row per dimension and value, with its spellings."""
    rows = []
    for stats in analysis.ranked():
        for label, papers in sorted(stats.values.items(), key=lambda i: (-i[1], i[0])):
            variants = stats.variants.get(label, Counter())
            rows.append(
                {
                    "dimension": stats.name,
                    "value": label,
                    "papers": papers,
                    "spellings": "; ".join(
                        f"{v} ({n})" for v, n in variants.most_common()
                    ),
                }
            )
    return pd.DataFrame(rows, columns=["dimension", "value", "papers", "spellings"])


def suggestions_table(analysis: TagAnalysis) -> pd.DataFrame:
    """The merge suggestions, in the columns of ``tag_synonyms.csv`` (plus info)."""
    return pd.DataFrame(
        [
            {
                "dimension": s.dimension,
                "value": s.value,
                "merge_into": s.merge_into,
                "similarity": s.similarity,
                "papers": s.papers,
            }
            for s in analysis.suggestions
        ],
        columns=["dimension", "value", "merge_into", "similarity", "papers"],
    )


def cooccurrence_table(pairs: list[tuple[str, str, pd.DataFrame, int]]) -> pd.DataFrame:
    """Long table of every non-empty pair of values of the crossed dimensions."""
    rows = []
    for first, second, frame, _ in pairs:
        for value_a, row in frame.iterrows():
            for value_b, papers in row.items():
                if papers:
                    rows.append(
                        {
                            "dimension_a": first,
                            "value_a": value_a,
                            "dimension_b": second,
                            "value_b": value_b,
                            "papers": int(papers),
                        }
                    )
    rows.sort(key=lambda r: -r["papers"])
    return pd.DataFrame(
        rows, columns=["dimension_a", "value_a", "dimension_b", "value_b", "papers"]
    )


def _md_cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_report(
    analysis: TagAnalysis,
    pairs: list[tuple[str, str, pd.DataFrame, int]],
    source: str,
    synonyms_path: Path | None,
) -> str:
    """Markdown summary of the analysis."""
    lines = [
        "# Annotation analysis",
        "",
        f"{analysis.annotated} of {analysis.papers} papers carry at least one "
        f"annotation; {sum(1 for d in analysis.dimensions.values() if d.values)} "
        f"dimensions have values. Tags read from {source}.",
        "",
        "## Coverage per dimension",
        "",
        "| Dimension | With a value | Explicitly none | To fill in (?) | Not tagged "
        "| Distinct values | Most used values |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for stats in analysis.ranked():
        top = ", ".join(
            f"{_md_cell(v)} ({n})"
            for v, n in sorted(stats.values.items(), key=lambda i: (-i[1], i[0]))[:5]
        )
        name = stats.name + (
            " *(grid, unused)*" if stats.in_grid and not stats.answered else ""
        )
        lines.append(
            f"| {name} | {stats.with_value} | {stats.with_none} | {stats.pending} "
            f"| {stats.absent} | {len(stats.values)} | {top} |"
        )

    merged = [
        (stats.name, label, variants)
        for stats in analysis.ranked()
        for label, variants in stats.variants.items()
        if len(variants) > 1
    ]
    lines += ["", "## Cleaning", ""]
    if merged:
        lines.append(
            f"{len(merged)} values were written in several ways and counted once "
            "(same letters and digits, or a synonym):"
        )
        lines.append("")
        for name, label, variants in merged[:30]:
            spelled = ", ".join(_md_cell(v) for v in variants)
            lines.append(f"- **{name}** {_md_cell(label)}: {spelled}")
        if len(merged) > 30:
            lines.append(f"- … {len(merged) - 30} more in `{VALUES_CSV}`")
    else:
        lines.append("No value was written in several ways.")
    lines.append("")
    if analysis.suggestions:
        lines += [
            f"{len(analysis.suggestions)} close spellings may be the same value "
            f"(all in `{SUGGESTIONS_CSV}`). Accept or reject them under "
            "**Merge suggestions** below (they go to "
            f"`{SYNONYMS_FILENAME}`"
            + (f", `{synonyms_path}`" if synonyms_path else "")
            + "), then run the analysis again.",
            "",
            "| Dimension | Value | Probably the same as | Similarity | Papers |",
            "|---|---|---|---:|---:|",
        ]
        for s in analysis.suggestions[:20]:
            lines.append(
                f"| {s.dimension} | {_md_cell(s.value)} | {_md_cell(s.merge_into)} "
                f"| {s.similarity:g} | {s.papers} |"
            )
    else:
        lines.append("No close spellings to merge.")
    if analysis.synonyms_used:
        lines += [
            "",
            f"{analysis.synonyms_used} spellings were merged by the synonyms table.",
        ]

    lines += ["", "## Crossing dimensions", ""]
    if pairs:
        lines.append(
            "Papers per pair of values of two dimensions (charts `cross_*.png`, "
            f"all pairs in `{COOCCURRENCE_CSV}`). Empty cells are combinations "
            "no paper covers."
        )
        lines.append("")
        lines += [
            "| Dimensions | Papers with both | Most frequent combinations |",
            "|---|---:|---|",
        ]
        for first, second, frame, common in pairs:
            stacked = frame.stack()
            best = stacked[stacked > 0].sort_values(ascending=False).head(3)
            combos = ", ".join(
                f"{_md_cell(a)} + {_md_cell(b)} ({int(n)})"
                for (a, b), n in best.items()
            )
            lines.append(f"| {first} × {second} | {common} | {combos} |")
    else:
        lines.append(
            "No two dimensions share enough annotated papers "
            f"(at least {MIN_COMMON_PAPERS}) to be crossed."
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Whole run
# ---------------------------------------------------------------------------


def write_outputs(
    analysis: TagAnalysis,
    out_dir: Path,
    source: str,
    synonyms_path: Path | None = None,
    max_dimensions: int = 5,
    progress=None,
    cancelled=None,
) -> list[Path]:
    """Write the report, charts and tables of ``analysis`` into ``out_dir``.

    Old charts are removed first so the folder only shows this run.
    Returns the report and the charts (the CSV tables are listed by the report).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    def step(percent: int, message: str) -> bool:
        if progress:
            progress(percent, message)
        return bool(cancelled and cancelled())

    files: list[Path] = []
    if step(10, "Drawing the coverage…"):
        return files
    if (path := plot_coverage(analysis, out_dir / COVERAGE_PNG)) is not None:
        files.append(path)

    with_values = [d for d in analysis.ranked() if d.values]
    for index, stats in enumerate(with_values):
        if step(
            15 + int(45 * index / max(len(with_values), 1)), f"Drawing {stats.name}…"
        ):
            return files
        path = plot_dimension(
            stats, out_dir / f"dimension_{_safe_name(stats.name)}.png"
        )
        if path is not None:
            files.append(path)

    if step(60, "Crossing dimensions…"):
        return files
    pairs = crossing_pairs(analysis, max_dimensions)
    for index, (first, second, frame, common) in enumerate(pairs):
        if step(
            60 + int(30 * index / max(len(pairs), 1)), f"Drawing {first} × {second}…"
        ):
            return files
        name = f"cross_{_safe_name(first)}_x_{_safe_name(second)}.png"
        files.append(plot_crossing(first, second, frame, common, out_dir / name))

    step(92, "Writing the tables…")
    values_table(analysis).to_csv(out_dir / VALUES_CSV, index=False)
    suggestions_table(analysis).to_csv(out_dir / SUGGESTIONS_CSV, index=False)
    cooccurrence_table(pairs).to_csv(out_dir / COOCCURRENCE_CSV, index=False)
    report = out_dir / REPORT_FILENAME
    report.write_text(
        render_report(analysis, pairs, source, synonyms_path), encoding="utf-8"
    )
    return [report, *files]
