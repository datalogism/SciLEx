"""Tools under the results of the Annotations analysis.

- Merge suggestions: accept (→ ``tag_synonyms.csv``) or reject them;
  the synonyms in use can be removed.
- Cross two dimensions chosen by the user.
- Clean the tags in Zotero: write every merged spelling as its canonical value.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.services import tag_review
from scilex.gui.services.jobs import Job, JobConflictError
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

CLEAN_JOB_KIND = "tags-zotero-clean"
EXAMPLES_SHOWN = 12


def _selectable_table(frame: pd.DataFrame, columns: list[tuple[str, str]], mark: str):
    rows = frame.reset_index(drop=True).assign(_id=lambda f: f.index).to_dict("records")
    return (
        ui.table(
            columns=[
                {"name": f, "label": label, "field": f, "align": "left", "sortable": True}
                for f, label in columns
            ],
            rows=rows,
            row_key="_id",
            selection="multiple",
            pagination=10,
        )
        .props("dense flat")
        .classes("w-full")
        .mark(mark)
    )


def render_tag_tools(ctx: AppContext, review: Review, collect_dir: Path) -> None:
    """Draw the merge, crossing and Zotero cards of the Annotations analysis."""
    paths = tag_review.paths_of(collect_dir, review.folder)
    _merges_card(paths)
    _cross_card(paths)
    _zotero_card(ctx, review, paths)


# --- merges ----------------------------------------------------------------------


def _merges_card(paths: tag_review.TagPaths) -> None:
    with ui.card().classes("w-full gap-2").mark("tags-merges"):
        ui.label("Merge suggestions").classes("text-lg font-bold")
        ui.label(
            "Close spellings that are probably one value. Accepted merges are saved "
            f"in {paths.synonyms.name} (review folder) and applied from the next run; "
            "rejected ones are never suggested again."
        ).classes("text-xs text-gray-500")

        @ui.refreshable
        def body() -> None:
            pending = tag_review.pending_suggestions(paths)
            if pending.empty:
                ui.label("No suggestion left to review.").classes(
                    "text-sm text-gray-500"
                ).mark("tags-no-suggestion")
            else:
                table = _selectable_table(
                    pending,
                    [
                        ("dimension", "Dimension"),
                        ("value", "Value"),
                        ("merge_into", "Merge into"),
                        ("similarity", "Similarity"),
                        ("papers", "Papers"),
                    ],
                    "tags-suggestions",
                )

                def decide(accepting: bool) -> None:
                    rows = list(table.selected)
                    if not rows:
                        ui.notify("Select suggestions first", type="warning")
                        return
                    if accepting:
                        count = tag_review.accept(paths, rows)
                        ui.notify(f"{count} merges accepted: run the analysis again")
                    else:
                        count = tag_review.reject(paths, rows)
                        ui.notify(f"{count} suggestions rejected")
                    body.refresh()

                def swap() -> None:
                    rows = list(table.selected)
                    if not rows:
                        ui.notify("Select suggestions first", type="warning")
                        return
                    ids = {row["_id"] for row in rows}
                    for row in table.rows:
                        if row["_id"] in ids:
                            row["value"], row["merge_into"] = row["merge_into"], row["value"]
                    table.selected = [row for row in table.rows if row["_id"] in ids]
                    table.update()
                    ui.notify("Direction swapped for the selected rows")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Accept selected", icon="merge", on_click=lambda: decide(True)
                    ).props("no-caps").mark("tags-accept")
                    ui.button(
                        "Reject selected", icon="block", on_click=lambda: decide(False)
                    ).props("outline no-caps").mark("tags-reject")
                    ui.button(
                        "Swap direction", icon="swap_horiz", on_click=swap
                    ).props("flat no-caps").mark("tags-swap").tooltip(
                        "Keep the other spelling as the value to merge into"
                    )

            synonyms = tag_analysis_table(paths.synonyms)
            if not synonyms.empty:
                ui.label(f"Merges in use ({len(synonyms)})").classes(
                    "font-medium mt-2"
                )
                used = _selectable_table(
                    synonyms,
                    [
                        ("dimension", "Dimension"),
                        ("value", "Value"),
                        ("merge_into", "Merged into"),
                    ],
                    "tags-synonyms",
                )

                def remove() -> None:
                    rows = list(used.selected)
                    if not rows:
                        ui.notify("Select merges first", type="warning")
                        return
                    count = tag_review.remove_synonyms(paths, rows)
                    ui.notify(f"{count} merges removed: run the analysis again")
                    body.refresh()

                ui.button(
                    "Stop merging selected", icon="call_split", on_click=remove
                ).props("outline no-caps").mark("tags-remove-synonyms")

        body()


def tag_analysis_table(path: Path) -> pd.DataFrame:
    from scilex.tag_analysis import read_merge_table

    return read_merge_table(path)


# --- crossing ----------------------------------------------------------------------


def _cross_card(paths: tag_review.TagPaths) -> None:
    choices = tag_review.dimension_choices(paths)
    if len(choices) < 2:
        return
    with ui.card().classes("w-full gap-2").mark("tags-cross"):
        ui.label("Cross two dimensions").classes("text-lg font-bold")
        ui.label(
            "Papers per pair of values; empty cells are combinations no paper covers."
        ).classes("text-xs text-gray-500")
        with ui.row().classes("items-center gap-4"):
            first = (
                ui.select(choices, value=choices[0], label="Rows", with_input=True)
                .classes("w-64")
                .mark("tags-cross-first")
            )
            second = (
                ui.select(choices, value=choices[1], label="Columns", with_input=True)
                .classes("w-64")
                .mark("tags-cross-second")
            )
            button = ui.button("Cross", icon="grid_on").props("no-caps").mark(
                "tags-cross-button"
            )
        chart = ui.column().classes("w-full")

        async def draw() -> None:
            try:
                path, common = await run.io_bound(
                    tag_review.cross, paths, first.value, second.value
                )
            except tag_review.TagReviewError as exc:
                show_error("Cannot cross these dimensions", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot cross these dimensions", exc)
                return
            chart.clear()
            with chart:
                ui.label(f"{path.name}: {common} papers with both").classes(
                    "text-xs text-gray-500"
                ).mark("tags-cross-result")
                data = base64.b64encode(path.read_bytes()).decode()
                ui.image(f"data:image/png;base64,{data}").classes("max-w-3xl")

        button.on_click(draw)


# --- Zotero cleaning --------------------------------------------------------------


def _zotero_card(ctx: AppContext, review: Review, paths: tag_review.TagPaths) -> None:
    from scilex.gui.services import zotero_library

    if zotero_library.load_source(review.folder) is None:
        return
    with ui.card().classes("w-full gap-2").mark("tags-zotero"):
        ui.label("Clean the spellings in Zotero").classes("text-lg font-bold")
        ui.label(
            "Rewrites each merged spelling with its value (Tool:Metashape → "
            "Tool:MetaShape, and the accepted merges) in the review's Zotero "
            "collection. Reads Zotero now; a paper edited meanwhile is skipped."
        ).classes("text-xs text-gray-500")
        preview = ui.column().classes("gap-1 w-full")
        holder: dict = {}

        async def compute() -> None:
            try:
                result = await run.io_bound(
                    tag_review.preview_cleaning, review.folder, paths
                )
            except tag_review.TagReviewError as exc:
                show_error("Cannot read Zotero", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot read Zotero", exc)
                return
            holder["plan"] = result.plan
            preview.clear()
            with preview:
                plan = result.plan
                renamed = sum(n for _, _, n in result.examples)
                ui.label(
                    f"{len(plan.updates)} of {plan.papers} papers would change "
                    f"({renamed} tags rewritten)."
                ).classes("font-medium").mark("tags-zotero-preview")
                for old, new, count in result.examples[:EXAMPLES_SHOWN]:
                    ui.label(f"• {old} → {new} ({count})").classes(
                        "text-xs text-gray-600"
                    )
                if len(result.examples) > EXAMPLES_SHOWN:
                    ui.label(
                        f"… and {len(result.examples) - EXAMPLES_SHOWN} more"
                    ).classes("text-xs text-gray-600")
            apply_button.set_enabled(bool(result.plan.updates))

        def apply() -> None:
            plan = holder.get("plan")
            if plan is None or not plan.updates:
                return

            def body(job: Job) -> str:
                job.message = f"Updating {len(plan.updates)} papers in Zotero…"
                outcome = tag_review.apply_cleaning(review.folder, plan)
                job.progress = 100
                return (
                    f"{outcome['success']} papers updated, {outcome['failed']} failed "
                    "(a paper edited meanwhile in Zotero is skipped: preview again)."
                )

            try:
                ctx.runner.start_task(review, CLEAN_JOB_KIND, body)
            except JobConflictError as exc:
                show_error("Cannot update Zotero now", exc, expected=True)
                return
            apply_button.set_enabled(False)
            holder.clear()

        with ui.row().classes("gap-2"):
            ui.button("Preview changes", icon="preview", on_click=compute).props(
                "outline no-caps"
            ).mark("tags-zotero-preview-button")
            apply_button = ui.button(
                "Apply in Zotero", icon="cleaning_services", on_click=apply
            ).props("no-caps").mark("tags-zotero-apply")
            apply_button.set_enabled(False)
        JobPanel(ctx, review, CLEAN_JOB_KIND, show_logs=False)
