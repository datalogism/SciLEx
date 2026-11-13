"""Compare the papers of a review by paper type or by Zotero collection.

Shared by every tab of ⑦ Analyses ("Compare by" option): the groups of a
paper are its type (``PAPER_TYPE`` tag, else its default type, see
:mod:`scilex.paper_types`) or its Zotero collections (sub-corpora; a paper in
several collections counts in each). The functions here draw the comparison
charts of the Charts, Annotations and Summaries tabs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scilex import review_tags
from scilex.constants import extract_year, is_valid, normalize_doi

NONE, PAPER_TYPE, COLLECTION = "none", "paper_type", "collection"
COMPARE_BY = {
    NONE: "Nothing (whole corpus)",
    PAPER_TYPE: "Paper type (Benchmark, Review, Dataset, Model)",
    COLLECTION: "Zotero collection (sub-corpus)",
}
LABELS = {PAPER_TYPE: "paper type", COLLECTION: "Zotero collection"}
NO_GROUP = "(none)"
MAX_GROUPS = 12  # more groups are unreadable in one chart


def groups_of(row, compare_by: str) -> list[str]:
    """The groups of one paper (``[]`` when not comparing)."""
    if compare_by == PAPER_TYPE:
        from scilex.paper_types import effective_types

        return effective_types(row)  # a paper can have several types
    if compare_by == COLLECTION:
        found = review_tags.split_tags(row.get("zotero_collections"))
        return sorted({g for g in found if g}) or [NO_GROUP]
    return []


def exploded(data: pd.DataFrame, compare_by: str) -> pd.DataFrame:
    """``data`` with a ``_group`` column, one row per (paper, group)."""
    groups = [groups_of(row, compare_by) for row in data.to_dict("records")]
    return data.assign(_group=groups).explode("_group").dropna(subset=["_group"])


def top_groups(frame: pd.DataFrame, limit: int = MAX_GROUPS) -> list[str]:
    """The most frequent groups of an exploded frame."""
    return list(frame["_group"].value_counts().index[:limit])


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _heatmap(table: pd.DataFrame, title: str, path: Path, fmt: str = "{:.0f}") -> Path:
    """Draw ``table`` (rows × columns, numbers) as an annotated heatmap."""
    plt = _plt()
    rows, cols = table.shape
    fig, ax = plt.subplots(
        figsize=(max(6, 1.1 * cols + 3), max(2.5, 0.45 * rows + 1.5))
    )
    image = ax.imshow(table.to_numpy(dtype=float), cmap="Blues", aspect="auto")
    ax.set_xticks(range(cols))
    ax.set_xticklabels([str(c)[:28] for c in table.columns], rotation=35, ha="right")
    ax.set_yticks(range(rows))
    ax.set_yticklabels([str(r)[:40] for r in table.index])
    peak = float(table.to_numpy(dtype=float).max() or 1)
    for i in range(rows):
        for j in range(cols):
            value = float(table.iat[i, j])
            ax.text(
                j,
                i,
                fmt.format(value),
                ha="center",
                va="center",
                fontsize=8,
                color="white" if value > peak * 0.6 else "black",
            )
    fig.colorbar(image, ax=ax, fraction=0.03)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _stacked(table: pd.DataFrame, title: str, path: Path, xlabel: str) -> Path:
    """Stacked bars: one bar per row of ``table``, one colour per column."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(max(7, 0.5 * len(table) + 4), 4.5))
    table.plot(kind="bar", stacked=True, ax=ax, width=0.8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Papers")
    ax.set_title(title)
    ax.legend(fontsize="small", ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


# -- Charts tab -------------------------------------------------------------


def report_charts(data: pd.DataFrame, out_dir: Path, compare_by: str) -> list[Path]:
    """Years, sources, keywords and types × collections, compared by group."""
    if compare_by not in LABELS or data.empty:
        return []
    label = LABELS[compare_by]
    frame = exploded(data, compare_by)
    keep = top_groups(frame)
    frame = frame[frame["_group"].isin(keep)]
    files = []

    years = frame.assign(_year=frame["date"].map(extract_year)).dropna(subset=["_year"])
    if not years.empty:
        table = pd.crosstab(years["_year"].astype(int), years["_group"])[keep]
        files.append(
            _stacked(
                table,
                f"Papers per year, by {label}",
                out_dir / f"compare_{compare_by}_years.png",
                "Year",
            )
        )
    if "archive" in frame.columns:
        sources = frame.assign(
            _source=frame["archive"].map(
                lambda v: str(v).split(";")[0].split("*")[0].strip()
                if is_valid(v)
                else "?"
            )
        )
        table = pd.crosstab(sources["_source"], sources["_group"])
        table = table[[g for g in keep if g in table.columns]]
        files.append(
            _heatmap(
                table,
                f"Papers per source and {label}",
                out_dir / f"compare_{compare_by}_sources.png",
            )
        )
    if "collect_keywords" in frame.columns:
        rows = []
        for _, row in frame.iterrows():
            for tag in review_tags.split_tags(row.get("collect_keywords")):
                term = tag.split(":", 1)[-1].strip()
                if term:
                    rows.append((term, row["_group"]))
        if rows:
            pairs = pd.DataFrame(rows, columns=["keyword", "_group"])
            table = pd.crosstab(pairs["keyword"], pairs["_group"])
            table = table.loc[table.sum(axis=1).sort_values(ascending=False).index[:20]]
            table = table[[g for g in keep if g in table.columns]]
            files.append(
                _heatmap(
                    table,
                    f"Search keywords per {label}",
                    out_dir / f"compare_{compare_by}_keywords.png",
                )
            )
    # Paper types inside each collection (whatever the choice): the two views met.
    crossed = exploded(data, COLLECTION)
    crossed = crossed.assign(
        _type=[groups_of(r, PAPER_TYPE)[0] for r in crossed.to_dict("records")]
    )
    if crossed["_group"].nunique() > 1 or NO_GROUP not in set(crossed["_group"]):
        table = pd.crosstab(crossed["_group"], crossed["_type"])
        table = table.loc[
            table.sum(axis=1).sort_values(ascending=False).index[:MAX_GROUPS]
        ]
        files.append(
            _heatmap(
                table,
                "Paper types per Zotero collection",
                out_dir / "compare_types_per_collection.png",
            )
        )
    return files


# -- Annotations tab --------------------------------------------------------


def annotation_pairs(tags) -> list[tuple[str, str]]:
    """``(DIMENSION, value)`` of the annotation tags of a cell (not PAPER_TYPE)."""
    from scilex.tag_analysis import parse_annotation

    found = []
    for tag in review_tags.split_tags(tags):
        if review_tags.is_workflow_tag(tag):
            continue
        parsed = parse_annotation(tag)
        if parsed and parsed[0] != "PAPER_TYPE" and parsed[1] not in ("", "?"):
            found.append(parsed)
    return found


def annotation_comparison(
    frame: pd.DataFrame, out_dir: Path, compare_by: str, max_dimensions: int = 5
) -> list[Path]:
    """Coverage of each dimension per group, and the top values per group."""
    if compare_by not in LABELS or frame.empty or "tags" not in frame.columns:
        return []
    label = LABELS[compare_by]
    data = exploded(frame, compare_by)
    keep = top_groups(data)
    data = data[data["_group"].isin(keep)]
    sizes = data["_group"].value_counts()
    coded: dict[tuple[str, str], int] = {}
    values: dict[tuple[str, str], dict[str, int]] = {}
    for _, row in data.iterrows():
        pairs = annotation_pairs(row.get("tags"))
        for dimension in {d for d, _ in pairs}:
            coded[(dimension, row["_group"])] = (
                coded.get((dimension, row["_group"]), 0) + 1
            )
        for dimension, value in pairs:
            counts = values.setdefault((dimension, row["_group"]), {})
            counts[value] = counts.get(value, 0) + 1
    if not coded:
        return []
    dimensions = sorted(
        {d for d, _ in coded},
        key=lambda d: -sum(n for (dim, _), n in coded.items() if dim == d),
    )
    table = pd.DataFrame(
        [[100 * coded.get((d, g), 0) / sizes[g] for g in keep] for d in dimensions],
        index=dimensions,
        columns=keep,
    )
    files = [
        _heatmap(
            table,
            f"% of papers coded per dimension, by {label}",
            out_dir / f"compare_{compare_by}_coverage.png",
        )
    ]
    lines = [
        f"# Annotations compared by {label}",
        "",
        "Papers per group: " + ", ".join(f"{g} ({sizes[g]})" for g in keep),
        "",
    ]
    for dimension in dimensions[:max_dimensions]:
        lines += [
            f"## {dimension}",
            "",
            "| " + label.capitalize() + " | Most frequent values |",
            "|---|---|",
        ]
        for group in keep:
            counts = values.get((dimension, group), {})
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
            text = ", ".join(f"{v} ({n})" for v, n in top) or "—"
            lines.append(f"| {group} | {text} |")
        lines.append("")
    report = out_dir / f"compare_{compare_by}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return [report, *files]


# -- Summaries tab ----------------------------------------------------------


def community_composition(
    clusters: pd.DataFrame, data: pd.DataFrame, out_dir: Path, compare_by: str
) -> tuple[str, list[Path]]:
    """Share of each group in each community: Markdown section and heatmap."""
    if compare_by not in LABELS or clusters.empty or data.empty:
        return "", []
    label = LABELS[compare_by]
    by_doi: dict[str, list[str]] = {}
    for row in data.to_dict("records"):
        doi = normalize_doi(row.get("DOI")) if is_valid(row.get("DOI")) else None
        if doi:
            by_doi[doi] = groups_of(row, compare_by)
    rows = []
    for row in clusters.to_dict("records"):
        doi = normalize_doi(row.get("DOI")) if is_valid(row.get("DOI")) else None
        for group in by_doi.get(doi or "", [NO_GROUP]):
            rows.append((int(row.get("cluster_id", -1)), group))
    pairs = pd.DataFrame(rows, columns=["community", "_group"])
    sizes = pairs.groupby("community").size()
    pairs = pairs[pairs["community"].isin(sizes[sizes > 1].index)]
    if pairs.empty:
        return "", []
    table = pd.crosstab(pairs["community"], pairs["_group"])
    table = table.loc[table.sum(axis=1).sort_values(ascending=False).index[:20]]
    keep = list(table.sum().sort_values(ascending=False).index[:MAX_GROUPS])
    share = (100 * table[keep].div(table.sum(axis=1), axis=0)).round(0)
    share.index = [f"Community {c}" for c in share.index]
    path = _heatmap(
        share,
        f"Share of each {label} in each community (%)",
        out_dir / f"summary_compare_{compare_by}.png",
    )
    lines = [
        f"## Communities by {label}",
        "",
        "| Community | " + " | ".join(keep) + " |",
        "|---|" + "---|" * len(keep),
    ]
    for community, row in share.iterrows():
        lines.append(f"| {community} | " + " | ".join(f"{v:.0f} %" for v in row) + " |")
    return "\n".join(lines) + "\n", [path]
