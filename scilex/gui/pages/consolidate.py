"""Consolidate screen: deduplicate and filter the corpus once it was extended.

Preview first (nothing written), then apply the duplicate groups ticked and
the filters of scilex.yml. See :mod:`scilex.gui.services.consolidate`.
"""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.components.run_status import RunStatus
from scilex.gui.services import consolidate as service
from scilex.gui.services.jobs import (
    ROWS,
    Job,
    JobConflictError,
    results_resource,
    review_zotero,
)
from scilex.gui.services.workspace import Review, Workspace
from scilex.gui.state import AppContext

JOB_KIND = "consolidate"
MAX_FILTERED_SHOWN = 300


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Consolidate screen of ``review``."""
    ui.label("Consolidate").classes("text-2xl font-bold")
    ui.label(
        "After extending the review (new queries, Zotero, BibTeX, snowball), find the "
        "papers that came in twice and the papers the filters of scilex.yml reject. "
        "Preview, tick what to merge, then apply. The results are backed up first."
    ).classes("text-gray-500")
    ConsolidatePage(ctx, review).build()


class ConsolidatePage:
    """Options, preview and apply."""

    def __init__(self, ctx: AppContext, review: Review):
        self.ctx, self.review = ctx, review
        self.plan: service.Plan | None = None
        self.ticks: dict[int, ui.checkbox] = {}

    def build(self) -> None:
        with ui.row().classes("items-center gap-4"):
            self.similarity = (
                ui.number(
                    "Title similarity (%)",
                    value=service.DEFAULT_SIMILARITY,
                    min=80,
                    max=100,
                    precision=0,
                )
                .props("dense outlined")
                .classes("w-44")
                .tooltip("100: exact titles only")
                .mark("consolidate-similarity")
            )
            self.separate = (
                ui.checkbox("Keep copies in different sub-corpora apart", value=True)
                .tooltip(
                    "A paper may be annotated once per Zotero collection on purpose "
                    "(e.g. as a model and as a dataset)"
                )
                .mark("consolidate-separate")
            )
            self.filter_imported = ui.checkbox(
                "Filter imported papers too (Zotero, BibTeX, knowledge graph)"
            ).mark("consolidate-filter-imported")
            ui.button("Preview", icon="preview", on_click=self.preview).props(
                "no-caps"
            ).mark("consolidate-preview")
        self.result = ui.column().classes("w-full gap-3").mark("consolidate-result")
        run_status = RunStatus(self.review, JOB_KIND, "Consolidated")
        JobPanel(
            self.ctx,
            self.review,
            JOB_KIND,
            show_logs=False,
            on_finished=lambda job: (run_status.update(), self._clear()),
        )

    def _clear(self) -> None:
        self.plan = None
        self.result.clear()
        with self.result:
            ui.label("Applied. Preview again to check the corpus.").classes("text-sm")

    async def preview(self) -> None:
        try:
            config = Workspace.load_config(self.review)
            self.plan = await run.io_bound(
                service.plan,
                self.review,
                config.main,
                similarity=int(self.similarity.value or service.DEFAULT_SIMILARITY),
                filter_imported=self.filter_imported.value,
                separate_subcorpora=self.separate.value,
            )
        except Exception as exc:
            show_error("Cannot preview the consolidation", exc)
            return
        self.draw()

    def draw(self) -> None:
        plan = self.plan
        self.result.clear()
        self.ticks = {}
        with self.result:
            ui.label(plan.message()).classes("font-medium").mark("consolidate-summary")
            self._duplicates(plan)
            self._filtered(plan)
            self._unclassified(plan)
            with ui.row().classes("items-center gap-3"):
                ui.button("Apply", icon="done_all", on_click=self.apply).props(
                    "no-caps"
                ).mark("consolidate-apply")
                ui.label(
                    "Merges the ticked groups and applies the filters as chosen above."
                ).classes("text-sm text-gray-500")

    def _duplicates(self, plan: service.Plan) -> None:
        ui.label(f"Duplicates ({len(plan.groups)} groups)").classes("text-lg font-bold")
        if not plan.groups:
            ui.label("No duplicates found.").classes("text-sm text-gray-500")
            return
        ui.label(
            "Pre-ticked: groups whose copies carry no different annotations. The first "
            "copy is kept; it gains the codes of dimensions it has not coded."
        ).classes("text-xs text-gray-500")
        for position, group in enumerate(plan.groups):
            with ui.card().classes("w-full gap-1").mark("consolidate-group"):
                with ui.row().classes("items-center gap-2 w-full"):
                    self.ticks[position] = ui.checkbox("Merge", value=group.safe).mark(
                        f"consolidate-merge-{position}"
                    )
                    ui.badge(group.reason).props("outline")
                    if not group.safe:
                        ui.badge(
                            f"{len(group.differing_codes)} differing codes",
                            color="warning",
                        )
                for index, (title, corpus, codes) in enumerate(
                    zip(group.titles, group.collections, group.code_counts, strict=True)
                ):
                    role = "kept" if index == 0 else "merged"
                    ui.label(
                        f"{role}: {title} — sub-corpus: {corpus} — {codes} codes"
                    ).classes("text-sm" + (" font-medium" if index == 0 else ""))
                if group.differing_codes:
                    with (
                        ui.expansion("Codes that differ")
                        .props("dense")
                        .classes("w-full")
                    ):
                        ui.label(", ".join(group.differing_codes)).classes("text-xs")

    def _filtered(self, plan: service.Plan) -> None:
        ui.label(f"Filters of scilex.yml ({len(plan.filtered)} papers)").classes(
            "text-lg font-bold"
        )
        self.apply_filters = ui.checkbox(
            "Apply the filters", value=bool(plan.filtered)
        ).mark("consolidate-apply-filters")
        self.action = (
            ui.radio(
                {
                    service.EXCLUDE_IN_SCREEN: "Exclude them in ③ Screen (reversible)",
                    service.REMOVE: "Remove them from the results",
                },
                value=service.EXCLUDE_IN_SCREEN,
            )
            .props("inline dense")
            .mark("consolidate-action")
        )
        if not plan.filtered:
            ui.label("No paper is rejected.").classes("text-sm text-gray-500")
            return
        rows = [
            {"title": paper.title, "reasons": "; ".join(paper.reasons)}
            for paper in plan.filtered[:MAX_FILTERED_SHOWN]
        ]
        ui.table(
            columns=[
                {"name": "title", "label": "Title", "field": "title", "align": "left"},
                {
                    "name": "reasons",
                    "label": "Rejected because",
                    "field": "reasons",
                    "align": "left",
                },
            ],
            rows=rows,
            pagination=15,
        ).classes("w-full").props("dense flat").mark("consolidate-filtered")

    def _unclassified(self, plan: service.Plan) -> None:
        """Papers in none of the required sub-corpora, with a sub-corpus to pick."""
        self.roles: dict[int, ui.select] = {}
        if not plan.required:
            ui.label(
                "Tip: list the sub-corpora every paper must belong to in scilex.yml "
                "(subcorpora: required: [datasets, surveys, models]) to check them here."
            ).classes("text-xs text-gray-500")
            return
        ui.label(
            f"Sub-corpora ({len(plan.unclassified)} papers in none of "
            f"{', '.join(plan.required)})"
        ).classes("text-lg font-bold")
        if not plan.unclassified:
            ui.label("Every paper belongs to a required sub-corpus.").classes(
                "text-sm text-gray-500"
            )
            return
        options = {"": "(leave)", **{name: name for name in plan.required}}
        for paper in plan.unclassified:
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                self.roles[paper.index] = (
                    ui.select(options, value=paper.suggestion or "")
                    .props("dense outlined")
                    .classes("w-36")
                    .mark("consolidate-role")
                )
                where = (
                    "in Zotero" if paper.zotero_key else "in SciLEx only (not linked)"
                )
                ui.label(
                    f"{paper.title} — now in: {paper.collections} — added {where}"
                ).classes("text-sm")
        ui.button("Classify", icon="category", on_click=self.classify).props(
            "outline no-caps"
        ).mark("consolidate-classify")

    def classify(self) -> None:
        assignments = {i: s.value for i, s in self.roles.items() if s.value}
        if not assignments:
            ui.notify("Choose a sub-corpus for at least one paper", type="warning")
            return
        review = self.review

        def body(job: Job) -> str:
            job.message = f"Classifying {len(assignments)} papers…"
            return service.classify(review, assignments)

        try:
            # Rewrites rows and adds items to Zotero collections.
            self.ctx.runner.start_task(
                review,
                JOB_KIND,
                body,
                resources=[results_resource(review.id, ROWS), review_zotero(review)],
            )
        except JobConflictError as exc:
            show_error("Cannot classify now", exc, expected=True)

    def apply(self) -> None:
        plan = self.plan
        if plan is None:
            return
        merge = [position for position, tick in self.ticks.items() if tick.value]
        apply_filters = self.apply_filters.value
        action = self.action.value
        review = self.review

        def body(job: Job) -> str:
            job.message = "Consolidating…"
            return service.apply(
                review, plan, merge=merge, apply_filters=apply_filters, action=action
            )

        try:
            self.ctx.runner.start_task(
                review, JOB_KIND, body, resources=[results_resource(review.id, ROWS)]
            )
        except JobConflictError as exc:
            show_error("Cannot consolidate now", exc, expected=True)
