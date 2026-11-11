"""Generate visual charts from an aggregated_results.csv file."""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import (
    extract_year,
    is_missing,
    normalize_path_component,
    parse_archive_apis,
)

CHART_DIR_NAME = "chart_aggregated_papers"
CSV_NAMES = ("aggregated_results.csv", "aggregation_results.csv")

ITEMTYPE_LABELS = {
    "journalArticle": "Journal Article",
    "conferencePaper": "Conference Paper",
    "preprint": "Preprint",
    "book": "Book",
    "bookSection": "Book Section",
    "thesis": "Thesis",
    "report": "Report",
}

PALETTE = [
    "#4C72B0",
    "#DD8452",
    "#55A868",
    "#C44E52",
    "#8172B3",
    "#937860",
    "#DA8BC3",
    "#8C8C8C",
    "#CCB974",
    "#64B5CD",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _find_csv(collect_dir: Path) -> Path:
    for name in CSV_NAMES:
        p = collect_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No aggregation CSV found in {collect_dir}. "
        f"Expected one of: {', '.join(CSV_NAMES)}"
    )


def _parse_keywords(kw_str: str) -> dict[str, str]:
    """Parse 'Collect_KW1:Value;Collect_KW2:Other' → {'Collect_KW1': 'Value', ...}."""
    result: dict[str, str] = {}
    if is_missing(kw_str):
        return result
    for part in kw_str.split(";"):
        part = part.strip()
        if ":" in part:
            key, _, val = part.partition(":")
            result[key.strip()] = val.strip()
    return result


def load_data(collect_dir: Path) -> pd.DataFrame:
    csv_path = _find_csv(collect_dir)
    df = pd.read_csv(csv_path, sep=";", dtype=str, on_bad_lines="skip")
    df.fillna("NA", inplace=True)

    df["_apis"] = df["archive"].apply(lambda value: set(parse_archive_apis(value)))
    df["_keywords"] = df["collect_keywords"].apply(_parse_keywords)
    df["_year"] = df["date"].apply(extract_year)
    df["_itemtype"] = df["itemType"].str.strip()

    return df


# ---------------------------------------------------------------------------
# Chart 1 – Chord diagram (papers by API source pairs)
# ---------------------------------------------------------------------------


def _build_api_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Build a symmetric co-occurrence matrix for APIs."""
    all_apis: set[str] = set()
    for apis in df["_apis"]:
        all_apis |= apis
    api_list = sorted(all_apis)
    idx = {a: i for i, a in enumerate(api_list)}
    n = len(api_list)
    matrix = np.zeros((n, n), dtype=int)

    for apis in df["_apis"]:
        apis = list(apis)
        if len(apis) == 1:
            i = idx[apis[0]]
            matrix[i, i] += 1
        else:
            for a in apis:
                for b in apis:
                    if a != b:
                        matrix[idx[a], idx[b]] += 1

    return matrix, api_list


def _bezier(
    p0: np.ndarray, p1: np.ndarray, ctrl: np.ndarray, steps: int = 60
) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0, 1, steps)
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ctrl[0] + t**2 * p1[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ctrl[1] + t**2 * p1[1]
    return x, y


def _draw_chord_diagram(ax: plt.Axes, matrix: np.ndarray, labels: list[str]) -> None:
    n = len(labels)
    colors = [PALETTE[i % len(PALETTE)] for i in range(n)]

    row_totals = matrix.sum(axis=1).astype(float)
    grand_total = row_totals.sum()
    if grand_total == 0:
        ax.text(0, 0, "No data", ha="center", va="center")
        return

    gap = 0.03 * 2 * np.pi
    total_arc = 2 * np.pi - n * gap
    spans = row_totals / grand_total * total_arc

    # Start at top (π/2), go clockwise (subtract angles)
    starts = np.zeros(n)
    starts[0] = np.pi / 2
    for i in range(1, n):
        starts[i] = starts[i - 1] - spans[i - 1] - gap

    # Sub-arc allocation within each segment for each connection
    sub_s = np.full((n, n), np.nan)
    sub_e = np.full((n, n), np.nan)
    for i in range(n):
        pos = starts[i]
        for j in range(n):
            val = matrix[i, j]
            if val > 0:
                width = val / grand_total * total_arc
                sub_s[i, j] = pos
                sub_e[i, j] = pos - width
                pos -= width

    ctrl = np.array([0.0, 0.0])

    # Draw chords (ribbons) first so arcs overlay them
    for i in range(n):
        for j in range(i + 1, n):
            val = matrix[i, j]
            if val == 0:
                continue

            s1, e1 = sub_s[i, j], sub_e[i, j]
            s2, e2 = sub_s[j, i], sub_e[j, i]

            arc1 = np.linspace(s1, e1, 40)
            arc2 = np.linspace(s2, e2, 40)

            p1e = np.array([np.cos(e1), np.sin(e1)])
            p2s = np.array([np.cos(s2), np.sin(s2)])
            p2e = np.array([np.cos(e2), np.sin(e2)])
            p1s = np.array([np.cos(s1), np.sin(s1)])

            bx1, by1 = _bezier(p1e, p2s, ctrl)
            bx2, by2 = _bezier(p2e, p1s, ctrl)

            x = np.concatenate([np.cos(arc1), bx1, np.cos(arc2[::-1]), bx2])
            y = np.concatenate([np.sin(arc1), by1, np.sin(arc2[::-1]), by2])

            # Blend the two API colors
            c1 = np.array(matplotlib.colors.to_rgb(colors[i]))
            c2 = np.array(matplotlib.colors.to_rgb(colors[j]))
            blend = (c1 + c2) / 2

            ax.fill(x, y, color=blend, alpha=0.38, zorder=2)
            ax.plot(
                np.append(x, x[0]),
                np.append(y, y[0]),
                color=blend,
                alpha=0.55,
                lw=0.6,
                zorder=3,
            )

            # Chord label
            lx = 0.45 * np.cos((s1 + e1 + s2 + e2) / 4)
            ly = 0.45 * np.sin((s1 + e1 + s2 + e2) / 4)
            ax.text(
                lx,
                ly,
                str(val),
                ha="center",
                va="center",
                fontsize=7,
                color="dimgray",
                zorder=6,
            )

    # Draw outer arcs
    for i in range(n):
        theta = np.linspace(starts[i], starts[i] - spans[i], 300)
        ax.plot(
            np.cos(theta),
            np.sin(theta),
            lw=22,
            color=colors[i],
            solid_capstyle="butt",
            zorder=5,
        )

        mid = starts[i] - spans[i] / 2
        r = 1.32
        ax.text(
            r * np.cos(mid),
            r * np.sin(mid),
            f"{labels[i]}\n({int(row_totals[i])})",
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
            color=colors[i],
            zorder=7,
        )


def plot_chord_diagram(df: pd.DataFrame, out_dir: Path) -> None:
    matrix, api_list = _build_api_matrix(df)
    if not api_list:
        print("  [chord] No API data found, skipping.")
        return

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-1.6, 1.6)

    _draw_chord_diagram(ax, matrix, api_list)
    ax.set_title(
        "Papers by API Source (co-occurrences)", fontsize=13, fontweight="bold", pad=20
    )

    fig.tight_layout()
    fig.savefig(out_dir / "chord_api_sources.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [chord] chord_api_sources.png")


# ---------------------------------------------------------------------------
# Chart 2 – Pie chart: publication type
# ---------------------------------------------------------------------------


def plot_itemtype_pie(df: pd.DataFrame, out_dir: Path) -> None:
    counts = df["_itemtype"].value_counts()
    counts = counts[counts > 0]

    labels = [ITEMTYPE_LABELS.get(k, k) for k in counts.index]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(counts))]

    fig, ax = plt.subplots(figsize=(7, 6))
    wedges, texts, autotexts = ax.pie(
        counts.values,
        labels=None,
        autopct=lambda p: f"{p:.1f}%\n({int(round(p * counts.sum() / 100))})",
        colors=colors,
        startangle=140,
        pctdistance=0.75,
        wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
    )
    for at in autotexts:
        at.set_fontsize(8)

    ax.legend(
        wedges,
        labels,
        title="Publication Type",
        loc="lower center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=2,
        fontsize=9,
    )
    ax.set_title(
        f"Publication Type Distribution (n={counts.sum()})",
        fontsize=13,
        fontweight="bold",
    )

    fig.tight_layout()
    fig.savefig(out_dir / "pie_publication_type.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [pie]   pie_publication_type.png")


# ---------------------------------------------------------------------------
# Chart 3 – Stacked horizontal bar: year × publication type
# ---------------------------------------------------------------------------


def plot_year_stacked_bar(df: pd.DataFrame, out_dir: Path) -> None:
    sub = df[df["_year"].notna()].copy()
    if sub.empty:
        print("  [bar]   No year data found, skipping year chart.")
        return

    sub["_year"] = sub["_year"].astype(int)
    item_types = sub["_itemtype"].value_counts().index.tolist()
    years = sorted(sub["_year"].unique())

    pivoted = (
        sub.groupby(["_year", "_itemtype"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=item_types, fill_value=0)
    )

    type_labels = [ITEMTYPE_LABELS.get(t, t) for t in item_types]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(item_types))]

    fig_height = max(5, len(years) * 0.45)
    fig, ax = plt.subplots(figsize=(10, fig_height))

    lefts = np.zeros(len(years))
    bar_patches = []
    for col_i, (col, label) in enumerate(zip(item_types, type_labels, strict=False)):
        vals = pivoted.get(col, pd.Series(0, index=pivoted.index)).values
        bars = ax.barh(
            [str(y) for y in pivoted.index],
            vals,
            left=lefts,
            color=colors[col_i],
            label=label,
            height=0.7,
        )
        bar_patches.append(bars)
        lefts += vals

    ax.set_xlabel("Number of Publications", fontsize=10)
    ax.set_ylabel("Year", fontsize=10)
    ax.set_title("Publications per Year by Type", fontsize=13, fontweight="bold")
    ax.legend(title="Type", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9)
    ax.xaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(out_dir / "bar_year_by_type.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [bar]   bar_year_by_type.png")


# ---------------------------------------------------------------------------
# Chart 4 – Bar charts: papers per keyword, one chart per KW group
# ---------------------------------------------------------------------------


def plot_keyword_bars(df: pd.DataFrame, out_dir: Path) -> None:
    # Collect counts per group → keyword value
    group_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for kw_dict in df["_keywords"]:
        for group, value in kw_dict.items():
            group_counts[group][value] += 1

    if not group_counts:
        print("  [kw]    No keyword data found, skipping.")
        return

    for group_name in sorted(group_counts.keys()):
        counts = group_counts[group_name]
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        labels, values = zip(*sorted_items, strict=False)

        fig_height = max(4, len(labels) * 0.45)
        fig, ax = plt.subplots(figsize=(9, fig_height))

        bars = ax.barh(
            list(reversed(labels)),
            list(reversed(values)),
            color=[PALETTE[i % len(PALETTE)] for i in range(len(labels))],
            height=0.65,
        )

        # Value labels on bars
        for bar, val in zip(bars, reversed(values), strict=False):
            ax.text(
                bar.get_width() + 0.3,
                bar.get_y() + bar.get_height() / 2,
                str(val),
                va="center",
                fontsize=8,
            )

        ax.set_xlabel("Number of Papers", fontsize=10)
        ax.set_title(
            f"Papers by Keyword — {group_name}  (n={sum(values)})",
            fontsize=12,
            fontweight="bold",
        )
        ax.xaxis.grid(True, linestyle="--", alpha=0.5)
        ax.set_axisbelow(True)
        ax.margins(x=0.12)

        fig.tight_layout()
        slug = re.sub(r"[^\w]", "_", group_name).lower()
        filename = f"bar_keywords_{slug}.png"
        fig.savefig(out_dir / filename, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  [kw]    {filename}")


# ---------------------------------------------------------------------------
# Chart 5 – Heatmap: KW1 × KW2 combinations
# ---------------------------------------------------------------------------


def plot_keyword_heatmap(df: pd.DataFrame, out_dir: Path) -> None:
    kw1_col = "Collect_KW1"
    kw2_col = "Collect_KW2"

    rows = []
    for kw_dict in df["_keywords"]:
        kw1 = kw_dict.get(kw1_col)
        kw2 = kw_dict.get(kw2_col)
        if kw1 and kw2:
            rows.append((kw1, kw2))

    if not rows:
        print("  [heatmap] No KW1×KW2 combinations found, skipping.")
        return

    combo_df = pd.DataFrame(rows, columns=["KW1", "KW2"])
    pivot = combo_df.groupby(["KW1", "KW2"]).size().unstack(fill_value=0)

    # Sort KW1 by total descending, KW2 by total descending
    kw1_order = pivot.sum(axis=1).sort_values(ascending=False).index
    kw2_order = pivot.sum(axis=0).sort_values(ascending=False).index
    pivot = pivot.loc[kw1_order, kw2_order]

    n_kw1, n_kw2 = pivot.shape
    fig_w = max(6, n_kw2 * 1.1 + 2)
    fig_h = max(5, n_kw1 * 0.5 + 1.5)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    data = pivot.values.astype(float)
    # Use 0 as transparent (white) so empty cells are clearly blank
    masked = np.ma.masked_where(data == 0, data)

    cmap = plt.cm.YlOrRd.copy()
    cmap.set_bad("whitesmoke")

    im = ax.imshow(masked, aspect="auto", cmap=cmap, interpolation="nearest")

    # Axis ticks
    ax.set_xticks(range(n_kw2))
    ax.set_xticklabels(pivot.columns, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(n_kw1))
    ax.set_yticklabels(pivot.index, fontsize=8)

    ax.set_xlabel("Collect KW2", fontsize=10, labelpad=8)
    ax.set_ylabel("Collect KW1", fontsize=10)
    ax.set_title(
        "Papers per Keyword Combination (KW1 × KW2)", fontsize=12, fontweight="bold"
    )

    # Annotate each cell
    vmax = data.max()
    for r in range(n_kw1):
        for c in range(n_kw2):
            val = int(pivot.iloc[r, c])
            if val == 0:
                continue
            text_color = "white" if val > vmax * 0.6 else "black"
            ax.text(
                c,
                r,
                str(val),
                ha="center",
                va="center",
                fontsize=7.5,
                color=text_color,
                fontweight="bold",
            )

    # Grid lines between cells
    ax.set_xticks(np.arange(-0.5, n_kw2, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_kw1, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", length=0)

    cbar = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cbar.set_label("Number of Papers", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_dir / "heatmap_kw1_kw2.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  [heatmap] heatmap_kw1_kw2.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _configured_collect_dir() -> Path:
    """Collection folder of the current configuration (``output_dir/name``)."""
    from scilex.settings.resolve import resolve_main_config

    config = resolve_main_config()
    return Path(
        config.get("output_dir", DEFAULT_OUTPUT_DIR)
    ) / normalize_path_component(config["collect_name"])


@exit_on_config_error
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate charts from an aggregated_results.csv collect directory.",
    )
    parser.add_argument(
        "collect_dir",
        type=Path,
        nargs="?",
        help="Collect directory containing aggregated_results.csv "
        "(default: output_dir/name from scilex.yml, like the other commands)",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    collect_dir: Path = (args.collect_dir or _configured_collect_dir()).resolve()
    if not collect_dir.is_dir():
        print(f"Error: '{collect_dir}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    out_dir = collect_dir / CHART_DIR_NAME
    out_dir.mkdir(exist_ok=True)

    print(f"Loading data from: {collect_dir}")
    try:
        df = load_data(collect_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(df)} papers loaded.")
    print(f"Output directory: {out_dir}\n")

    print("Generating charts...")
    plot_chord_diagram(df, out_dir)
    plot_itemtype_pie(df, out_dir)
    plot_year_stacked_bar(df, out_dir)
    plot_keyword_bars(df, out_dir)
    plot_keyword_heatmap(df, out_dir)

    print(f"\nDone. Charts saved to: {out_dir}")


if __name__ == "__main__":
    main()
