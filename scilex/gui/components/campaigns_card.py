"""Campaigns of ④ Annotate: who annotates which collection, people and LLMs.

A campaign is one collection of the review, its paper type (which grid
dimensions apply), its human annotators (``ANNOT:<id>``, balanced, N per paper
for cross-annotation) and its LLM annotators (models run by SciLEx Annotator,
which only propose ``DIMENSION-AUTO:value`` tags). See
:mod:`scilex.gui.services.campaigns` and :mod:`scilex.gui.services.llm_annotator`.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.services import campaigns as service
from scilex.gui.services import llm_annotator, members
from scilex.gui.services.extend import read_results
from scilex.gui.services.jobs import Job, JobConflictError
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext
from scilex.tagging import auto_tags
from scilex.tagging.grid import ALL_TYPES, PAPER_TYPES

LLM_JOB = "llm-annotate"
ALL = "__all__"
TYPE_LABELS = {ALL_TYPES: "All dimensions", **{t: t.capitalize() for t in PAPER_TYPES}}
SUGGESTED_MODELS = [
    service.DEFAULT_MODEL,
    "anthropic:claude-sonnet-5-5",
    "openrouter:<vendor>/<model>",
    "ollama:<model>",
]


class CampaignsCard:
    """The LLM service address, the campaign form and one panel per campaign."""

    def __init__(self, ctx: AppContext, review: Review, grid: Callable):
        self.ctx, self.review, self.grid = ctx, review, grid
        self.store = service.load(review.folder)
        self._service_card()
        with ui.card().classes("w-full gap-2").mark("campaigns-card"):
            with ui.row().classes("items-center w-full"):
                ui.label("Campaigns").classes("text-lg font-bold")
                ui.space()
                ui.button(
                    "New campaign", icon="add", on_click=lambda: self.edit(None)
                ).props("dense no-caps").mark("campaign-new")
            ui.label(
                "One campaign per collection to annotate: its paper type selects the "
                "grid dimensions, its annotators get the papers (ANNOT:<id>), and its "
                "LLM models propose DIMENSION-AUTO:value tags that a person accepts, "
                "corrects or rejects (Validate tab). A human code always wins: the "
                "LLM only proposes on dimensions still at DIMENSION:?."
            ).classes("text-sm text-gray-500")
            self.panels()
        with ui.card().classes("w-full gap-1"):
            ui.label("LLM annotation runs").classes("font-medium")
            JobPanel(
                ctx,
                review,
                LLM_JOB,
                show_logs=False,
                on_finished=lambda job: self.panels.refresh(),
            )

    # -- service --------------------------------------------------------------

    def _service_card(self) -> None:
        with (
            ui.expansion("LLM annotator service (SciLEx Annotator)", icon="smart_toy")
            .classes("w-full")
            .mark("llm-service")
        ):
            ui.label(
                "LLM annotators are run by SciLEx Annotator, a separate program: start "
                "it with 'scilex-annotator api' (see its README). Its token is an API "
                "key (API keys > SciLEx Annotator); LLM provider keys stay on the "
                "service."
            ).classes("text-xs text-gray-500")
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                url = (
                    ui.input("Service address", value=self.store.annotator_url)
                    .props("dense outlined")
                    .classes("grow")
                    .mark("llm-service-url")
                )

                def save() -> None:
                    self.store = service.load(self.review.folder)
                    self.store.annotator_url = (url.value or "").strip() or (
                        service.DEFAULT_ANNOTATOR_URL
                    )
                    service.save(self.review.folder, self.store)
                    ui.notify("Service address saved")

                async def test() -> None:
                    client = llm_annotator.Client(
                        url.value or "",
                        llm_annotator.token_for(self.review),
                        timeout=10,
                    )
                    try:
                        ok = await run.io_bound(client.health)
                    except llm_annotator.AnnotatorError as exc:
                        show_error(
                            "SciLEx Annotator is not reachable", exc, expected=True
                        )
                        return
                    ui.notify(
                        "SciLEx Annotator answers" if ok else "Unexpected answer",
                        type="positive" if ok else "warning",
                    )

                ui.button("Save", icon="save", on_click=save).props(
                    "flat dense no-caps"
                )
                ui.button("Test", icon="network_check", on_click=test).props(
                    "outline dense no-caps"
                ).mark("llm-service-test")

    # -- campaigns -----------------------------------------------------------

    def _data(self):
        try:
            return read_results(self.review.results_path)
        except Exception:
            return None

    @ui.refreshable_method
    def panels(self) -> None:
        self.store = service.load(self.review.folder)
        data = self._data()
        if not self.store.campaigns:
            ui.label("No campaign yet: create one per collection to annotate.").classes(
                "text-sm text-gray-500"
            ).mark("campaigns-empty")
            return
        grid = self.grid()
        for campaign in self.store.campaigns:
            dims = service.dimensions(grid, campaign)
            progress = (
                service.progress(data, campaign, dims) if data is not None else None
            )
            with (
                ui.card()
                .classes("w-full gap-1")
                .props("flat bordered")
                .mark(f"campaign-{campaign.id}")
            ):
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.icon("folder", color="primary")
                    ui.label(campaign.label).classes("font-bold")
                    ui.badge(
                        TYPE_LABELS.get(campaign.paper_type, campaign.paper_type)
                    ).props("outline")
                    ui.label(f"{len(dims)} dimensions").classes("text-xs text-gray-500")
                    ui.space()
                    ui.button(
                        icon="edit", on_click=lambda c=campaign: self.edit(c)
                    ).props("flat dense round").tooltip("Edit")
                    ui.button(
                        icon="delete", on_click=lambda c=campaign: self.delete(c)
                    ).props("flat dense round color=negative").tooltip("Delete")
                with ui.row().classes("items-center gap-1 flex-wrap"):
                    ui.label("People:").classes("text-xs text-gray-500")
                    for who in campaign.annotators or ["none"]:
                        ui.chip(who, icon="person").props("dense outline")
                    ui.label(f"× {campaign.per_paper} per paper").classes("text-xs")
                    ui.label("· LLMs:").classes("text-xs text-gray-500")
                    for model in campaign.llm_models or ["none"]:
                        ui.chip(model, icon="smart_toy").props(
                            "dense outline color=purple"
                        )
                if progress is not None:
                    cells = progress.cells
                    ui.linear_progress(
                        value=round(progress.done_share, 3), show_value=False
                    ).classes("w-full")
                    ui.label(
                        f"{progress.papers} papers · {progress.assigned} assigned · "
                        f"{progress.validated} validated (ANNOT_VALID_BY) · "
                        f"dimensions: {cells[auto_tags.HUMAN]} coded, "
                        f"{cells[auto_tags.PROPOSED]} LLM proposals to validate, "
                        f"{cells[auto_tags.TODO]} to do"
                        + (
                            f" · {progress.stale} proposals left on coded dimensions"
                            if progress.stale
                            else ""
                        )
                    ).classes("text-sm").mark(f"campaign-progress-{campaign.id}")
                with ui.row().classes("gap-2"):
                    ui.button(
                        "Assign papers",
                        icon="assignment_ind",
                        on_click=lambda c=campaign: self.assign(c),
                    ).props("outline dense no-caps").mark(
                        f"campaign-assign-{campaign.id}"
                    )
                    ui.button(
                        "Run LLM annotators",
                        icon="smart_toy",
                        on_click=lambda c=campaign: self.run_llm(c),
                    ).props("outline dense no-caps").mark(f"campaign-llm-{campaign.id}")

    def edit(self, campaign: service.Campaign | None) -> None:
        data = self._data()
        paths = service.collection_paths(data) if data is not None else []
        collections = {ALL: "All papers of the review", **{p: p for p in paths}}
        people = {
            m.identifier: m.label
            for m in members.load(self.review.folder)
            if m.identifier
        }
        for who in campaign.annotators if campaign else []:
            people.setdefault(who, who)
        models = list(
            dict.fromkeys(SUGGESTED_MODELS + (campaign.llm_models if campaign else []))
        )
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full gap-2"):
            ui.label("Edit campaign" if campaign else "New campaign").classes(
                "text-lg font-bold"
            )
            collection = (
                ui.select(
                    collections,
                    value=(campaign.collection or ALL) if campaign else ALL,
                    label="Collection",
                    with_input=True,
                )
                .classes("w-full")
                .mark("campaign-collection")
            )
            name = (
                ui.input("Name", value=campaign.name if campaign else "")
                .classes("w-full")
                .mark("campaign-name")
            )
            paper_type = (
                ui.select(
                    TYPE_LABELS,
                    value=campaign.paper_type if campaign else ALL_TYPES,
                    label="Paper type (grid dimensions)",
                )
                .classes("w-full")
                .mark("campaign-type")
            )

            def collection_changed(event) -> None:
                if campaign is None and event.value and event.value != ALL:
                    paper_type.value = service.suggest_type(
                        event.value, self.review.folder
                    )
                    if not name.value:
                        name.value = event.value

            collection.on_value_change(collection_changed)
            if not people:
                ui.label(
                    "No member yet: add the annotators in the Team tab first."
                ).classes("text-sm text-warning")
            annotators = (
                ui.select(
                    people,
                    multiple=True,
                    value=list(campaign.annotators) if campaign else [],
                    label="Human annotators",
                )
                .props("use-chips")
                .classes("w-full")
                .mark("campaign-annotators")
            )
            per_paper = (
                ui.number(
                    "Annotators per paper (2+ = cross-annotation)",
                    value=campaign.per_paper if campaign else 1,
                    min=1,
                    max=5,
                    precision=0,
                )
                .classes("w-full")
                .mark("campaign-per-paper")
            )
            llms = (
                ui.select(
                    models,
                    multiple=True,
                    value=list(campaign.llm_models) if campaign else [],
                    label="LLM annotators (model strings; type to add one)",
                    new_value_mode="add-unique",
                )
                .props("use-chips")
                .classes("w-full")
                .mark("campaign-llms")
            )
            ui.label(
                "Several models = several LLM annotations of the same paper and "
                "dimension, compared with each other and with the people."
            ).classes("text-xs text-gray-500")

            def save() -> None:
                chosen = None if collection.value == ALL else collection.value
                models_chosen = [m for m in llms.value or [] if "<" not in m]
                try:
                    if campaign is None:
                        service.create(
                            self.review.folder,
                            chosen or "",
                            name=(name.value or "").strip(),
                            paper_type=paper_type.value,
                            annotators=list(annotators.value or []),
                            per_paper=int(per_paper.value or 1),
                            llm_models=models_chosen,
                        )
                    else:
                        campaign.collection = chosen or ""
                        campaign.name = (
                            name.value or ""
                        ).strip() or campaign.collection
                        campaign.paper_type = paper_type.value
                        campaign.annotators = list(annotators.value or [])
                        campaign.per_paper = int(per_paper.value or 1)
                        campaign.llm_models = models_chosen
                        service.update(self.review.folder, campaign)
                except (OSError, ValueError) as exc:
                    show_error("Cannot save the campaign", exc, expected=True)
                    return
                dialog.close()
                self.panels.refresh()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", icon="save", on_click=save).mark("campaign-save")
        dialog.open()

    def delete(self, campaign: service.Campaign) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete the campaign '{campaign.label}'?").classes("font-bold")
            ui.label(
                "Tags already written (ANNOT, codes, proposals) and the stored LLM "
                "answers stay."
            ).classes("text-sm")

            def confirm() -> None:
                service.remove(self.review.folder, campaign.id)
                dialog.close()
                self.panels.refresh()

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Delete", on_click=confirm).props("color=negative no-caps")
        dialog.open()

    # -- assignment ---------------------------------------------------------

    def assign(self, campaign: service.Campaign) -> None:
        data = self._data()
        if data is None:
            ui.notify("The review has no papers yet", type="warning")
            return
        try:
            plan = service.plan_assignment(data, campaign)
        except ValueError as exc:
            show_error("Cannot plan the assignment", exc, expected=True)
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Assign the papers of '{campaign.label}'").classes("font-bold")
            ui.label(plan.message()).classes("text-sm").mark("campaign-assign-preview")
            ui.label(
                "Papers already assigned are kept; loads are balanced inside the "
                "campaign. Sync with Zotero to share the ANNOT tags."
            ).classes("text-xs text-gray-500")

            async def confirm() -> None:
                try:
                    count = await run.io_bound(members.assign, self.review, plan)
                except Exception as exc:
                    show_error("Cannot assign the papers", exc)
                    return
                dialog.close()
                ui.notify(f"{count} papers assigned", type="positive")
                self.panels.refresh()

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Assign", icon="assignment_ind", on_click=confirm).props(
                    "no-caps"
                ).mark("campaign-assign-confirm").set_enabled(bool(plan.plan))
        dialog.open()

    # -- LLM ---------------------------------------------------------------

    def run_llm(self, campaign: service.Campaign) -> None:
        if not campaign.llm_models:
            ui.notify(
                "Add an LLM model to the campaign first (edit it)", type="warning"
            )
            return
        data = self._data()
        dims = service.dimensions(self.grid(), campaign)
        if data is None or not dims:
            ui.notify(
                "No paper, or no grid dimension for this paper type", type="warning"
            )
            return
        rejected = llm_annotator.rejected_pairs(self.review)
        with ui.dialog() as dialog, ui.card().classes("w-[34rem] max-w-full gap-2"):
            ui.label(f"LLM annotation of '{campaign.label}'").classes("font-bold")
            model = (
                ui.select(
                    campaign.llm_models, value=campaign.llm_models[0], label="Model"
                )
                .classes("w-full")
                .mark("llm-run-model")
            )
            also = ui.checkbox(
                "Also the dimensions people already coded (kept locally, to compare "
                "the LLM with them; costs more)",
                value=False,
            ).mark("llm-run-also")
            summary = ui.label().classes("text-sm").mark("llm-run-summary")

            def describe() -> None:
                plan = llm_annotator.plan_run(
                    data, campaign, dims, also_coded=bool(also.value), rejected=rejected
                )
                summary.set_text(
                    f"{plan.papers} papers, {plan.questions} questions to the model."
                    if plan.groups
                    else "Nothing to ask: every dimension is coded or proposed."
                )

            also.on_value_change(lambda _: describe())
            describe()
            ui.label(
                "The papers are sent without their tags. Answers on dimensions still "
                "at DIMENSION:? become DIMENSION-AUTO:value proposals."
            ).classes("text-xs text-gray-500")

            def start() -> None:
                review, url = (
                    self.review,
                    service.load(self.review.folder).annotator_url,
                )
                chosen, also_coded = model.value, bool(also.value)

                def body(job: Job) -> str:
                    return llm_annotator.run_campaign(
                        review, campaign, chosen, url, also_coded=also_coded, job=job
                    ).message()

                try:
                    self.ctx.runner.start_task(review, LLM_JOB, body)
                except JobConflictError as exc:
                    show_error(
                        "Cannot start the LLM annotation now", exc, expected=True
                    )
                    return
                dialog.close()

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Start", icon="play_arrow", on_click=start).props(
                    "no-caps"
                ).mark("llm-run-start")
        dialog.open()
