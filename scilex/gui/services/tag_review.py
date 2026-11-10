"""Annotations analysis of a review: tags, merges, crossings and Zotero cleaning.

The review folder (next to ``scilex.yml``) keeps the user's decisions:
``tag_synonyms.csv`` (accepted merges) and ``tag_merges_rejected.csv`` (merges
never to suggest again). Outputs go to ``<collection dir>/annotation_analysis``;
``tags_source.csv`` there keeps the tags the last run read (from the aggregated
results or live from Zotero), so a crossing asked later uses the same data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from scilex import tag_analysis as tags

SOURCE_CSV = "tags_source.csv"
REJECTED_FILENAME = "tag_merges_rejected.csv"
SOURCE_COLUMNS = ["title", "DOI", "date", "tags", "zotero_key", "archiveID", "url"]
FROM_CSV = "aggregated_results.csv (tags as of the last Zotero import)"


class TagReviewError(Exception):
    """A user-facing problem (no Zotero collection, nothing annotated...)."""


@dataclass(frozen=True)
class TagPaths:
    """Files of the Annotations analysis of one review."""

    out_dir: Path
    synonyms: Path
    rejected: Path
    grid: Path

    @property
    def source(self) -> Path:
        return self.out_dir / SOURCE_CSV

    @property
    def suggestions(self) -> Path:
        return self.out_dir / tags.SUGGESTIONS_CSV

    @property
    def values(self) -> Path:
        return self.out_dir / tags.VALUES_CSV


def paths_of(collect_dir: Path, review_folder: Path | None) -> TagPaths:
    """Files of the analysis; without a review folder, decisions stay in ``out_dir``."""
    out_dir = collect_dir / tags.OUTPUT_DIRNAME
    folder = review_folder or out_dir
    return TagPaths(
        out_dir=out_dir,
        synonyms=folder / tags.SYNONYMS_FILENAME,
        rejected=folder / REJECTED_FILENAME,
        grid=(review_folder or collect_dir.parent.parent) / "annotation_grid.csv",
    )


def grid_dimensions(paths: TagPaths) -> list[str]:
    """Dimensions of the review's annotation grid (none without a grid)."""
    if not paths.grid.is_file():
        return []
    from scilex.tagging.grid import TAG_COLUMN, load_grid

    return [str(t) for t in load_grid(paths.grid)[TAG_COLUMN].dropna()]


def analyse(frame: pd.DataFrame, paths: TagPaths, similarity: float) -> tags.TagAnalysis:
    """Analyse ``frame`` with the review's synonyms, rejected merges and grid."""
    try:
        synonyms = tags.load_synonyms(paths.synonyms)
    except ValueError as exc:
        raise TagReviewError(str(exc)) from exc
    return tags.analyse_tags(
        frame,
        synonyms,
        grid_dimensions(paths),
        similarity,
        tags.load_rejected(paths.rejected),
    )


# --- Zotero -------------------------------------------------------------------


def _zotero_api(review_folder: Path):
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review_folder)
    if source is None:
        raise TagReviewError(
            "This review has no Zotero collection to read the tags from: create it "
            "from a Zotero collection, or choose one in ⑧ Export."
        )
    try:
        api = zotero_library.client(effective_keys(review_folder), library=source)
    except zotero_library.ZoteroNotConfiguredError as exc:
        raise TagReviewError(str(exc)) from exc
    return api, source


def fetch_zotero_items(review_folder: Path) -> list[dict]:
    """Read the review's papers from Zotero now (with their current tags)."""
    from scilex.gui.services import zotero_library

    api, source = _zotero_api(review_folder)
    try:
        return zotero_library.fetch_source_papers(api, source)
    except ConnectionError as exc:
        raise TagReviewError(f"Cannot read the Zotero collection: {exc}") from exc


def items_frame(items: list[dict]) -> pd.DataFrame:
    """Results table of Zotero ``items`` (papers only)."""
    from scilex.gui.services.zotero_library import items_to_results

    return items_to_results(items)


# --- run ----------------------------------------------------------------------


def run(
    collect_dir: Path,
    review_folder: Path | None,
    progress: Callable[[int, str], None],
    *,
    from_zotero: bool = False,
    row_filter: Callable | None = None,
    max_dimensions: int = 5,
    similarity: float = tags.DEFAULT_SIMILARITY,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[str, list[Path]]:
    """Analyse the tags and write the outputs; returns ``(message, files)``."""
    from scilex.gui.services.analyses import read_result_csv

    paths = paths_of(collect_dir, review_folder)
    if from_zotero:
        if review_folder is None:
            raise TagReviewError("Reading Zotero needs the review folder.")
        progress(2, "Reading the tags from Zotero…")
        frame = items_frame(fetch_zotero_items(review_folder))
        source = "Zotero (read now)"
    else:
        results = collect_dir / "aggregated_results.csv"
        if not results.is_file():
            raise TagReviewError(
                "Run the collection first (step Collect): no aggregated results."
            )
        progress(2, "Reading the tags…")
        frame = read_result_csv(results)
        source = FROM_CSV
    if row_filter is not None:
        frame = row_filter(frame)
    if frame.empty:
        raise TagReviewError("No paper to analyse.")

    analysis = analyse(frame, paths, similarity)
    if not any(d.answered or d.pending for d in analysis.dimensions.values()):
        raise TagReviewError(
            "No DIMENSION:value annotation tag in these papers. Annotate them in "
            "Zotero (see ④ Annotate)"
            + (", then tick \"Read the tags from Zotero now\"." if not from_zotero else ".")
        )
    paths.out_dir.mkdir(parents=True, exist_ok=True)
    frame.reindex(columns=SOURCE_COLUMNS).to_csv(paths.source, index=False)
    tags.write_synonyms_template(paths.synonyms)
    files = tags.write_outputs(
        analysis,
        paths.out_dir,
        source,
        paths.synonyms,
        max_dimensions,
        progress,
        cancelled,
    )
    used = sum(1 for d in analysis.dimensions.values() if d.values)
    return (
        f"{analysis.annotated} of {analysis.papers} papers annotated, {used} "
        f"dimensions, {len(analysis.suggestions)} merges suggested "
        f"(tags from {source.split(' (')[0]}).",
        files,
    )


# --- merge decisions ------------------------------------------------------------


def pending_suggestions(paths: TagPaths) -> pd.DataFrame:
    """Suggestions of the last run not yet accepted or rejected."""
    if not paths.suggestions.is_file():
        return pd.DataFrame(columns=["dimension", "value", "merge_into", "similarity", "papers"])
    frame = pd.read_csv(paths.suggestions, dtype=str).fillna("")
    decided = {
        (tags.dimension_name(r["dimension"] or "*"), tags.value_key(r["value"]))
        for table in (paths.synonyms, paths.rejected)
        for r in tags.read_merge_table(table).to_dict("records")
    }
    keep = [
        (tags.dimension_name(r["dimension"]), tags.value_key(r["value"])) not in decided
        and ("*", tags.value_key(r["value"])) not in decided
        for r in frame.to_dict("records")
    ]
    # A boolean Series: an empty list would select no column instead of no row.
    return frame[pd.Series(keep, index=frame.index, dtype=bool)].reset_index(drop=True)


def accept(paths: TagPaths, rows: list[dict]) -> int:
    """Merge ``rows`` from now on (adds them to the synonyms table)."""
    if paths.rejected.is_file():
        tags.remove_merge_rows(paths.rejected, rows)
    return tags.add_merge_rows(paths.synonyms, rows)


def reject(paths: TagPaths, rows: list[dict]) -> int:
    """Never suggest ``rows`` again."""
    return tags.add_merge_rows(paths.rejected, rows)


def remove_synonyms(paths: TagPaths, rows: list[dict]) -> int:
    """Stop merging ``rows``."""
    return tags.remove_merge_rows(paths.synonyms, rows) if paths.synonyms.is_file() else 0


# --- crossing on demand -----------------------------------------------------------


def dimension_choices(paths: TagPaths) -> list[str]:
    """Dimensions with values in the last run, most used first."""
    if not paths.values.is_file():
        return []
    frame = pd.read_csv(paths.values, dtype=str).fillna("")
    order = Counter()
    for row in frame.to_dict("records"):
        order[row["dimension"]] += int(row.get("papers") or 0)
    return [name for name, _ in order.most_common()]


def cross(
    paths: TagPaths, first: str, second: str, similarity: float = tags.DEFAULT_SIMILARITY
) -> tuple[Path, int]:
    """Draw the crossing of two dimensions on the tags of the last run.

    Returns the chart and the number of papers having both dimensions.
    """
    if first == second:
        raise TagReviewError("Choose two different dimensions.")
    if not paths.source.is_file():
        raise TagReviewError("Run the analysis first.")
    frame = pd.read_csv(paths.source, dtype=str)
    analysis = analyse(frame, paths, similarity)
    table, common = tags.cooccurrence(analysis, first, second)
    if table.empty:
        raise TagReviewError(
            f"No paper has a value for both {first} and {second}."
        )
    name = f"cross_{tags._safe_name(first)}_x_{tags._safe_name(second)}.png"
    return tags.plot_crossing(first, second, table, common, paths.out_dir / name), common


# --- cleaning Zotero -------------------------------------------------------------


@dataclass
class CleanPreview:
    """What cleaning the Zotero tags would change."""

    plan: tags.TagCleanPlan
    examples: list[tuple[str, str, int]]  # (old tag, new tag, papers)


def preview_cleaning(
    review_folder: Path, paths: TagPaths, similarity: float = tags.DEFAULT_SIMILARITY
) -> CleanPreview:
    """Read Zotero now and plan writing every merged spelling as its canonical value."""
    items = fetch_zotero_items(review_folder)
    analysis = analyse(items_frame(items), paths, similarity)
    plan = tags.plan_tag_cleaning(items, analysis)
    examples = [(old, new, n) for (old, new), n in plan.renames.most_common()]
    return CleanPreview(plan, examples)


def apply_cleaning(review_folder: Path, plan: tags.TagCleanPlan) -> dict[str, int]:
    """Write the planned tags to Zotero (an item edited meanwhile is skipped)."""
    api, _ = _zotero_api(review_folder)
    return api.update_item_tags(plan.updates)
