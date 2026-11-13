"""Annotate step: edit the annotation grid, apply it in Zotero, report on annotations."""

from __future__ import annotations

import io
import itertools

import pandas as pd
from nicegui import events, run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.components.run_status import RunStatus
from scilex.gui.services import annotations as service
from scilex.gui.services import zotero_library
from scilex.gui.services.jobs import Job, JobConflictError, review_zotero
from scilex.gui.services.keys_editor import effective_keys
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext
from scilex.tagging.grid import (
    ALL_TYPES,
    DETAIL_COLUMN,
    PAPER_TYPES,
    TAG_COLUMN,
    deduce_grid,
    merge_grids,
)

JOB_KIND = "annotate"
TYPE_CHOICES = {
    ALL_TYPES: "Every dimension of the grid",
    **{t: f"Papers of type '{t}' (dimensions marked {t})" for t in PAPER_TYPES},
}
GRID_COLUMNS = [
    {
        "field": TAG_COLUMN,
        "headerName": "Dimension",
        "editable": True,
        "minWidth": 170,
    },
    {
        "field": DETAIL_COLUMN,
        "headerName": "Question to answer",
        "editable": True,
        "flex": 2,
        "minWidth": 220,
        "tooltipField": DETAIL_COLUMN,
    },
    *(
        {
            "field": paper_type,
            "headerName": paper_type.capitalize(),
            "editable": True,
            "cellDataType": "boolean",
            "width": 110,
        }
        for paper_type in PAPER_TYPES
    ),
]


PARAMETERS, TEAM, CAMPAIGNS, VALIDATE, PROGRESS = (
    "parameters",
    "team",
    "campaigns",
    "validate",
    "progress",
)
TABS = {
    PARAMETERS: ("Parameters", "tune"),
    TEAM: ("Team", "group"),
    CAMPAIGNS: ("Campaigns", "assignment"),
    VALIDATE: ("Validate", "fact_check"),
    PROGRESS: ("Progress & agreement", "insights"),
}
NEEDS_PAPERS = (TEAM, CAMPAIGNS, VALIDATE)


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Annotate screen (the annotation manager) of ``review``."""
    ui.label("Annotate").classes("text-2xl font-bold")
    ui.label(
        "The annotation manager: the grid and its guideline, the team, one campaign "
        "per collection (people and LLM annotators), the LLM proposals to validate, "
        "and the progress and agreement of the annotation."
    ).classes("text-gray-600")

    def saved_grid() -> pd.DataFrame:
        try:
            return service.load_review_grid(review)
        except (OSError, ValueError):
            return pd.DataFrame()

    with ui.tabs().classes("w-full").props("align=left") as tabs:
        for key, (label, icon) in TABS.items():
            ui.tab(key, label=label, icon=icon).mark(f"annotate-tab-{key}")
    drawn: set[str] = set()
    with ui.tab_panels(tabs, value=PARAMETERS).classes("w-full min-w-0"):
        containers = {key: ui.tab_panel(key).classes("gap-3") for key in TABS}

    def show(key: str) -> None:
        # Drawn when first opened: each tab reads its files and polls its jobs.
        if key in drawn:
            return
        drawn.add(key)
        with containers[key]:
            if key in NEEDS_PAPERS and not review.has_results:
                ui.label(
                    "The review has no papers yet: collect or import them first."
                ).classes("text-sm text-gray-500")
            elif key == PARAMETERS:
                from scilex.gui.components.guideline_card import GuidelineCard

                state = _GridState(review)
                collection = _CollectionPicker(ctx, review)
                _grid_card(state, collection)
                GuidelineCard(review, lambda: state.current()[TAG_COLUMN].tolist())
                _apply_card(ctx, review, state, collection)
            elif key == TEAM:
                from scilex.gui.components.annotators import AnnotatorsCard

                AnnotatorsCard(review, show_assign=False)
            elif key == CAMPAIGNS:
                from scilex.gui.components.campaigns_card import CampaignsCard

                CampaignsCard(ctx, review, saved_grid)
            elif key == VALIDATE:
                from scilex.gui.components.validate_queue import ValidateQueue

                ValidateQueue(review, saved_grid)
            elif key == PROGRESS:
                if review.has_results:
                    _campaign_progress_card(review, saved_grid)
                    _llm_agreement_card(review)
                _report_card(review, _CollectionPicker(ctx, review))
                if review.has_results:
                    from scilex.gui.components.agreement_card import AgreementCard

                    AgreementCard(ctx, review)

    tabs.on_value_change(lambda event: show(event.value))
    show(PARAMETERS)


def _campaign_progress_card(review: Review, grid) -> None:
    from scilex.gui.services import campaigns
    from scilex.gui.services.extend import read_results

    store = campaigns.load(review.folder)
    with ui.card().classes("w-full gap-2").mark("annotate-campaign-progress"):
        ui.label("Campaigns, per dimension").classes("text-lg font-bold")
        if not store.campaigns:
            ui.label("No campaign yet (Campaigns tab).").classes(
                "text-sm text-gray-500"
            )
            return
        try:
            data = read_results(review.results_path)
        except Exception:
            data = None
        if data is None:
            return
        frame = grid()
        with ui.tabs().props("dense align=left") as tabs:
            for campaign in store.campaigns:
                ui.tab(campaign.id, label=campaign.label)
        with ui.tab_panels(tabs, value=store.campaigns[0].id).classes("w-full"):
            for campaign in store.campaigns:
                with ui.tab_panel(campaign.id):
                    dims = campaigns.dimensions(frame, campaign)
                    progress = campaigns.progress(data, campaign, dims)
                    _table(
                        pd.DataFrame(progress.by_dimension),
                        [
                            ("dimension", "Dimension"),
                            ("human", "Coded by a person"),
                            ("proposed", "LLM proposal to validate"),
                            ("todo", "To do"),
                        ],
                        f"annotate-progress-{campaign.id}",
                    )


def _llm_agreement_card(review: Review) -> None:
    import math

    from scilex.gui.services import llm_annotator
    from scilex.gui.services.extend import read_results

    with ui.card().classes("w-full gap-2").mark("annotate-llm-agreement"):
        ui.label("LLM annotators against the people").classes("text-lg font-bold")
        ui.label(
            "For each model: how often people accepted, corrected or rejected its "
            "proposals, and Krippendorff's alpha (MASI) between its answers and the "
            "people's codes on the same papers and dimensions (answers on coded "
            "dimensions: Run LLM annotators > 'Also the dimensions people already coded')."
        ).classes("text-xs text-gray-500")
        result = ui.column().classes("w-full gap-2")

        async def build() -> None:
            try:
                data = read_results(review.results_path)
                models = await run.io_bound(llm_annotator.llm_agreement, review, data)
            except Exception as exc:
                show_error("Cannot compare the LLMs with the people", exc)
                return
            result.clear()
            with result:
                if not models:
                    ui.label("No LLM answer to compare yet.").classes("text-sm")
                    return
                for model in models:
                    outcomes = model.outcomes
                    share = model.acceptance
                    ui.label(
                        f"{model.model}: {outcomes['accepted']} accepted, "
                        f"{outcomes['corrected']} corrected, {outcomes['rejected']} "
                        "rejected"
                        + ("" if math.isnan(share) else f" ({share:.0%} accepted)")
                    ).classes("font-medium text-sm").mark("annotate-llm-outcomes")
                    _table(
                        pd.DataFrame(
                            [
                                {
                                    "dimension": d.dimension,
                                    "alpha": "—"
                                    if math.isnan(d.alpha)
                                    else f"{d.alpha:.2f}",
                                    "level": d.level,
                                    "papers": d.papers,
                                }
                                for d in model.dimensions
                            ]
                        ),
                        [
                            ("dimension", "Dimension"),
                            ("alpha", "α (MASI)"),
                            ("level", "Agreement"),
                            ("papers", "Papers"),
                        ],
                        "annotate-llm-alpha",
                    )

        ui.button("Compare", icon="compare", on_click=build).props(
            "outline no-caps"
        ).mark("annotate-llm-compare")


class _GridState:
    """The grid being edited: table rows plus the columns the table does not show."""

    def __init__(self, review: Review):
        self.review = review
        self.ids = itertools.count()
        self.previous = pd.DataFrame()
        self.rows: list[dict] = []
        self.dirty = False
        self.grid: ui.aggrid | None = None
        try:
            self.set_grid(service.load_review_grid(review), dirty=False)
        except (OSError, ValueError) as exc:
            show_error("Cannot read annotation_grid.csv", exc, expected=True)

    def set_grid(self, grid: pd.DataFrame, dirty: bool = True) -> None:
        self.previous = grid
        self.rows = [
            {"_id": next(self.ids), **row} for row in service.grid_to_rows(grid)
        ]
        self.dirty = dirty
        self.show()

    def show(self) -> None:
        if self.grid is not None:
            self.grid.options["rowData"] = self.rows
            self.grid.update()

    def current(self) -> pd.DataFrame:
        return service.rows_to_grid(self.rows, self.previous)

    def on_edit(self, event: events.GenericEventArguments) -> None:
        data = event.args.get("data") or {}
        for index, row in enumerate(self.rows):
            if row["_id"] == data.get("_id"):
                self.rows[index] = {**row, **data}
        self.dirty = True

    def add(self) -> None:
        self.rows.append(
            {
                "_id": next(self.ids),
                TAG_COLUMN: f"NEW_DIMENSION_{len(self.rows) + 1}",
                DETAIL_COLUMN: "",
                **dict.fromkeys(PAPER_TYPES, True),
            }
        )
        self.dirty = True
        self.show()

    async def remove_selected(self) -> None:
        selected = {row["_id"] for row in await self.grid.get_selected_rows()}
        if not selected:
            ui.notify("Tick the dimensions to remove first", type="warning")
            return
        self.rows = [row for row in self.rows if row["_id"] not in selected]
        self.dirty = True
        self.show()

    def save(self) -> bool:
        try:
            path = service.save_review_grid(self.review, self.current())
        except (OSError, ValueError) as exc:
            show_error("Cannot save the grid", exc, expected=True)
            return False
        self.previous = self.current()
        self.dirty = False
        ui.notify(f"Grid saved: {path}")
        return True


class _CollectionPicker:
    """Zotero collection the grid is applied to and reported on."""

    def __init__(self, ctx: AppContext, review: Review):
        self.review = review
        source = zotero_library.load_source(review.folder)
        self.options: dict[str, str] = {}
        default = None
        if source and source.collection_key:
            self.options[source.collection_key] = source.collection_name
            default = source.collection_key
        with ui.card().classes("w-full gap-2").mark("annotate-collection"):
            ui.label("Zotero collection").classes("text-lg font-bold")
            ui.label(
                "Uses the global Zotero key and the review's Zotero group. "
                + (
                    f"This review was created from '{source.collection_name}'."
                    if source
                    else "Export pushes a review to a collection named after it."
                )
            ).classes("text-xs text-gray-500")
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                self.select = (
                    ui.select(
                        self.options,
                        value=default,
                        label="Collection",
                        with_input=True,
                    )
                    .classes("grow")
                    .mark("annotate-collection-select")
                )
                ui.button("Load collections", icon="refresh", on_click=self.load).props(
                    "outline dense no-caps"
                ).mark("annotate-load-collections")

    async def load(self) -> None:
        try:
            api = zotero_library.client(
                effective_keys(self.review.folder),
                library=zotero_library.load_source(self.review.folder),
            )
            collections = await run.io_bound(zotero_library.list_collections, api)
        except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
            show_error("Cannot list the Zotero collections", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot list the Zotero collections", exc)
            return
        self.options = {c.key: f"{c.path} ({c.num_items})" for c in collections}
        self.select.set_options(self.options)
        if self.select.value not in self.options:
            match = next(
                (
                    c.key
                    for c in collections
                    if c.path.split(" / ")[-1] == self.review.name
                ),
                None,
            )
            self.select.value = match
        ui.notify(f"{len(collections)} collections")

    @property
    def key(self) -> str | None:
        return self.select.value

    @property
    def name(self) -> str:
        return self.options.get(self.select.value, self.select.value or "")

    async def papers(self) -> list[dict] | None:
        """Fetch the papers of the chosen collection; None (after a message) on error."""
        if not self.key:
            ui.notify("Choose a Zotero collection first", type="warning")
            return None
        try:
            api = zotero_library.client(
                effective_keys(self.review.folder),
                library=zotero_library.load_source(self.review.folder),
            )
            return await run.io_bound(zotero_library.fetch_papers, api, self.key)
        except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
            show_error("Cannot read the Zotero collection", exc, expected=True)
        except Exception as exc:
            show_error("Cannot read the Zotero collection", exc)
        return None


def _grid_card(state: _GridState, collection: _CollectionPicker) -> None:
    with ui.card().classes("w-full gap-2").mark("annotate-grid"):
        with ui.row().classes("items-center w-full"):
            ui.label("Annotation grid").classes("text-lg font-bold")
            ui.space()
            ui.label(str(service.grid_path(state.review))).classes(
                "text-xs text-gray-500 break-all"
            )
        ui.label(
            "One row per dimension. Tick the paper types it applies to; the "
            "question tells annotators what to write after DIMENSION:."
        ).classes("text-xs text-gray-500")
        state.grid = (
            ui.aggrid(
                {
                    "columnDefs": GRID_COLUMNS,
                    "rowData": state.rows,
                    ":getRowId": "(params) => String(params.data._id)",
                    "rowSelection": {"mode": "multiRow", "enableClickSelection": False},
                    "defaultColDef": {"resizable": True, "sortable": True},
                    "stopEditingWhenCellsLoseFocus": True,
                    "tooltipShowDelay": 300,
                }
            )
            .classes("w-full")
            .style("height: max(240px, 36vh)")
            .mark("annotate-grid-table")
        )
        state.grid.on("cellValueChanged", state.on_edit)
        empty_hint = ui.label(
            "No grid yet: start from the SciLEx grid, import a CSV, or deduce one "
            "from the annotations of the Zotero collection."
        ).classes("text-sm text-gray-500")
        empty_hint.bind_visibility_from(state, "rows", backward=lambda rows: not rows)

        async def deduce() -> None:
            papers = await collection.papers()
            if papers is None:
                return
            found = deduce_grid(papers)
            if found.empty:
                ui.notify(
                    "No DIMENSION:value annotation in this collection", type="warning"
                )
                return
            before = len(state.rows)
            state.set_grid(merge_grids(state.current(), found))
            ui.notify(
                f"{len(state.rows) - before} dimensions added from {len(papers)} papers"
            )

        def load_default() -> None:
            try:
                state.set_grid(merge_grids(state.current(), service.default_grid()))
            except (OSError, ValueError) as exc:
                show_error("Cannot read the SciLEx grid", exc, expected=True)

        async def imported(event: events.UploadEventArguments) -> None:
            try:
                content = await event.file.read()
                grid = pd.read_csv(
                    io.BytesIO(content), sep=None, engine="python", dtype=str
                )
                state.set_grid(merge_grids(state.current(), grid))
            except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as exc:
                show_error("Cannot import this CSV", exc, expected=True)
            upload_dialog.close()

        with ui.dialog() as upload_dialog, ui.card():
            ui.label("Import a grid (CSV with a 'tag' column)").classes("font-bold")
            ui.upload(on_upload=imported, auto_upload=True).props("accept=.csv").mark(
                "annotate-upload"
            )

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button("Add dimension", icon="add", on_click=state.add).props(
                "outline dense no-caps"
            ).mark("annotate-add")
            ui.button(
                "Remove ticked", icon="delete", on_click=state.remove_selected
            ).props("flat dense no-caps").mark("annotate-remove")
            ui.button(
                "Add the SciLEx grid", icon="library_add", on_click=load_default
            ).props("flat dense no-caps").mark("annotate-default")
            ui.button(
                "Import CSV…", icon="upload_file", on_click=upload_dialog.open
            ).props("flat dense no-caps").mark("annotate-import")
            ui.button(
                "Deduce from Zotero annotations", icon="auto_fix_high", on_click=deduce
            ).props("flat dense no-caps").mark("annotate-deduce")
            ui.space()
            ui.button("Save grid", icon="save", on_click=state.save).mark(
                "annotate-save"
            )


def _apply_card(
    ctx: AppContext,
    review: Review,
    state: _GridState,
    collection: _CollectionPicker,
) -> None:
    with ui.card().classes("w-full gap-2").mark("annotate-apply"):
        ui.label("Add the grid to the Zotero papers").classes("text-lg font-bold")
        ui.label(
            "Each paper gets DIMENSION:? for every dimension it has no value for; "
            "existing values are normalized (DIMENSION:DeepLearning)."
        ).classes("text-xs text-gray-500")
        with ui.row().classes("items-center gap-4"):
            paper_type = (
                ui.select(TYPE_CHOICES, value=ALL_TYPES, label="Dimensions to add")
                .classes("w-96")
                .mark("annotate-type")
            )
            keep_others = ui.checkbox(
                "Keep the other tags (SciLEx tags, keywords, other dimensions)",
                value=True,
            ).mark("annotate-keep")
        preview = ui.column().classes("gap-1 w-full")
        plan_holder: dict = {}

        async def compute_plan() -> None:
            if state.dirty and not state.save():
                return
            papers = await collection.papers()
            if papers is None:
                return
            try:
                plan = service.plan_apply(
                    state.current(), papers, paper_type.value, bool(keep_others.value)
                )
            except ValueError as exc:
                show_error("Cannot apply the grid", exc, expected=True)
                return
            plan_holder["plan"] = plan
            plan_holder["collection"] = collection.name
            preview.clear()
            with preview:
                ui.label(
                    f"{len(plan.updates)} of {plan.papers} papers of "
                    f"'{collection.name}' would change ({len(plan.dimensions)} dimensions)."
                ).classes("font-medium").mark("annotate-preview")
                if not keep_others.value:
                    ui.label(
                        "Tags outside the grid will be REMOVED from these papers."
                    ).classes("text-sm text-negative")
                for title, tags in plan.examples:
                    ui.label(f"• {title[:90]}: {', '.join(tags[-6:])}").classes(
                        "text-xs text-gray-600"
                    )
            apply_button.set_enabled(bool(plan.updates))

        def apply() -> None:
            plan = plan_holder.get("plan")
            if plan is None or not plan.updates:
                return

            def body(job: Job) -> str:
                job.message = f"Updating {len(plan.updates)} papers in Zotero…"
                api = zotero_library.client(
                    effective_keys(review.folder),
                    library=zotero_library.load_source(review.folder),
                )
                result = api.update_item_tags(plan.updates)
                job.progress = 100
                return (
                    f"{result['success']} papers updated, {result['failed']} failed "
                    "(a paper edited meanwhile in Zotero is skipped: preview again)."
                )

            try:
                ctx.runner.start_task(
                    review, JOB_KIND, body, resources=[review_zotero(review)]
                )
            except JobConflictError as exc:
                show_error("Cannot update Zotero now", exc, expected=True)
                return
            apply_button.set_enabled(False)
            plan_holder.clear()

        with ui.row().classes("gap-2"):
            ui.button("Preview changes", icon="preview", on_click=compute_plan).props(
                "outline no-caps"
            ).mark("annotate-preview-button")
            apply_button = ui.button(
                "Apply in Zotero", icon="sell", on_click=apply
            ).mark("annotate-apply-button")
            apply_button.set_enabled(False)
        run_status = RunStatus(review, JOB_KIND, "Applied in Zotero")
        JobPanel(
            ctx,
            review,
            JOB_KIND,
            show_logs=False,
            on_finished=lambda job: run_status.update(),
        )


def _table(frame: pd.DataFrame, columns: list[tuple[str, str]], mark: str) -> None:
    if frame is None or frame.empty:
        ui.label("Nothing yet.").classes("text-sm text-gray-500")
        return
    present = [(field, label) for field, label in columns if field in frame.columns]
    ui.table(
        columns=[
            {"name": f, "label": label, "field": f, "align": "left", "sortable": True}
            for f, label in present
        ],
        rows=frame[[f for f, _ in present]].to_dict("records"),
        pagination=10,
    ).props("dense flat").classes("w-full").mark(mark)


def _report_card(review: Review, collection: _CollectionPicker) -> None:
    with ui.card().classes("w-full gap-2").mark("annotate-report"):
        ui.label("Annotation report").classes("text-lg font-bold")
        ui.label(
            "Counts the annotation tags of the collection by dimension and by "
            "annotator (from Zotero's last-modified log), as scilex report_annotations does."
        ).classes("text-xs text-gray-500")
        result = ui.column().classes("w-full gap-2")

        async def build() -> None:
            papers = await collection.papers()
            if papers is None:
                return
            try:
                report = await run.io_bound(service.build_report, review, papers)
            except OSError as exc:
                show_error("Cannot write the report", exc, expected=True)
                return
            result.clear()
            with result:
                ui.label(
                    f"{report.papers} papers of '{collection.name}'. CSV files in {report.folder}"
                ).classes("text-sm font-medium").mark("annotate-report-summary")
                with ui.tabs() as tabs:
                    by_dim = ui.tab("By dimension")
                    top = ui.tab("Top tags")
                    people = ui.tab("Annotators")
                with ui.tab_panels(tabs, value=by_dim).classes("w-full"):
                    with ui.tab_panel(by_dim):
                        _table(
                            report.by_dimension,
                            [
                                ("dimension", "Dimension"),
                                ("nb_distinct_subtags", "Distinct values"),
                                ("nb_article_instances", "Papers"),
                            ],
                            "annotate-report-dimensions",
                        )
                    with ui.tab_panel(top):
                        _table(
                            report.top_tags,
                            [("tag", "Tag"), ("nb_articles", "Papers")],
                            "annotate-report-tags",
                        )
                    with ui.tab_panel(people):
                        _table(
                            report.annotators,
                            [
                                ("username", "User"),
                                ("nb_items_last_touched", "Papers last edited"),
                                ("nb_annotation_tag_instances", "Annotation tags"),
                                ("is_scilex_push_account", "SciLEx push account"),
                            ],
                            "annotate-report-annotators",
                        )

        ui.button("Build the report", icon="analytics", on_click=build).props(
            "outline no-caps"
        ).mark("annotate-report-button")
