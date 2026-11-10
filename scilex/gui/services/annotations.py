"""Annotate step: the review's annotation grid and its use in Zotero.

The grid is stored next to ``scilex.yml`` as ``annotation_grid.csv`` (same
format as ``scilex/tagging/*.csv``). Applying it adds ``DIMENSION:?``
placeholders to the papers of a Zotero collection; the report counts the
annotations already made.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from scilex.gui.services.workspace import Review
from scilex.tagging.grid import (
    DEFAULT_GRID_PATH,
    DETAIL_COLUMN,
    GRID_FILENAME,
    PAPER_TYPES,
    TAG_COLUMN,
    empty_grid,
    load_grid,
    normalize_grid,
    plan_grid_updates,
    save_grid,
    tags_for_type,
)

REPORT_DIRNAME = "annotations"


def grid_path(review: Review) -> Path:
    """Return where the review's grid is stored."""
    return review.folder / GRID_FILENAME


def load_review_grid(review: Review) -> pd.DataFrame:
    """Return the review's grid (empty when it has none yet)."""
    path = grid_path(review)
    return load_grid(path) if path.is_file() else empty_grid()


def default_grid() -> pd.DataFrame:
    """Return the grid shipped with SciLEx (``scilex/tagging``)."""
    return load_grid(DEFAULT_GRID_PATH)


def grid_to_rows(grid: pd.DataFrame) -> list[dict]:
    """Rows for the editable table: paper types become booleans."""
    rows = []
    for record in normalize_grid(grid).to_dict("records"):
        row = {
            TAG_COLUMN: record[TAG_COLUMN],
            DETAIL_COLUMN: str(record.get(DETAIL_COLUMN, "")),
        }
        for paper_type in PAPER_TYPES:
            row[paper_type] = "X" in str(record.get(paper_type, "")).upper()
        rows.append(row)
    return rows


def rows_to_grid(
    rows: list[dict], previous: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Turn edited table rows back into a grid, keeping the extra columns of ``previous``."""
    edited = pd.DataFrame(
        [
            {
                TAG_COLUMN: str(row.get(TAG_COLUMN) or ""),
                DETAIL_COLUMN: str(row.get(DETAIL_COLUMN) or ""),
                **{t: "X" if row.get(t) else "" for t in PAPER_TYPES},
            }
            for row in rows
        ],
        columns=[TAG_COLUMN, DETAIL_COLUMN, *PAPER_TYPES],
    )
    edited = normalize_grid(edited)
    if previous is None or previous.empty:
        return edited
    previous = normalize_grid(previous)
    extra = [c for c in previous.columns if c not in edited.columns]
    if not extra:
        return edited
    return edited.merge(
        previous[[TAG_COLUMN, *extra]], on=TAG_COLUMN, how="left"
    ).fillna("")


def save_review_grid(review: Review, grid: pd.DataFrame) -> Path:
    """Write the review's grid."""
    return save_grid(grid, grid_path(review))


@dataclass(frozen=True)
class ApplyPlan:
    """What applying the grid to a collection would change."""

    papers: int
    updates: dict[str, tuple[int, list[str]]]
    dimensions: list[str]
    examples: list[tuple[str, list[str]]]  # (title, new tags) of a few papers


def plan_apply(
    grid: pd.DataFrame, items: list[dict], paper_type: str, keep_other_tags: bool
) -> ApplyPlan:
    """Compute the tag changes of applying ``grid`` to ``items``.

    Raises:
        ValueError: If no dimension of the grid applies to ``paper_type``.
    """
    dimensions = tags_for_type(grid, paper_type)
    if not dimensions:
        raise ValueError(f"No dimension of the grid applies to '{paper_type}' papers.")
    updates = plan_grid_updates(items, dimensions, keep_other_tags)
    titles = {item["key"]: item["data"].get("title", "") for item in items}
    examples = [
        (titles.get(key, key), tags) for key, (_, tags) in list(updates.items())[:5]
    ]
    papers = sum(1 for item in items if item.get("data", {}).get("title"))
    return ApplyPlan(papers, updates, dimensions, examples)


@dataclass(frozen=True)
class AnnotationReport:
    """Tables of the annotation report and the folder they were written to."""

    papers: int
    by_dimension: pd.DataFrame
    top_tags: pd.DataFrame
    annotators: pd.DataFrame
    folder: Path


def build_report(review: Review, items: list[dict]) -> AnnotationReport:
    """Count the annotations of ``items`` and write the CSV reports.

    Files go to ``<collection folder>/annotations/``, as
    ``scilex-report-annotations`` would write them.
    """
    from scilex.report_annotations import (
        analyze_items,
        build_annotator_activity,
        build_tags_by_dimension,
        build_tags_summary,
    )

    analysis = analyze_items(items)
    tags = build_tags_summary(analysis) if analysis["tag_articles"] else pd.DataFrame()
    dimensions = (
        build_tags_by_dimension(analysis)
        if analysis["dimension_articles"]
        else pd.DataFrame()
    )
    annotators = (
        build_annotator_activity(analysis)
        if analysis["annotator_items"]
        else pd.DataFrame()
    )
    folder = review.collection_dir / REPORT_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    tags.to_csv(folder / "tags_summary.csv", index=False)
    dimensions.to_csv(folder / "tags_by_dimension.csv", index=False)
    annotators.to_csv(folder / "annotator_activity.csv", index=False)

    from scilex.gui.services.overview import record_snapshot, zotero_tags

    record_snapshot(review.folder, zotero_tags(items), "annotate")
    annotation_dims = (
        dimensions[dimensions["category"] == "annotation"]
        if len(dimensions)
        else dimensions
    )
    top = tags[tags["category"] == "annotation"].head(30) if len(tags) else tags
    return AnnotationReport(
        papers=len(analysis["valid_papers"]),
        by_dimension=annotation_dims,
        top_tags=top,
        annotators=annotators,
        folder=folder,
    )
