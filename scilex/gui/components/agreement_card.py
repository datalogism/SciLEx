"""Agreement study card of ④ Annotate: copies per annotator, alpha, merge.

See :mod:`scilex.gui.services.agreement`.
"""

from __future__ import annotations

import math

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.services import agreement as service
from scilex.gui.services.extend import read_results
from scilex.gui.services.jobs import Job, JobConflictError, review_zotero
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

JOB_KIND = "agreement"
LEVEL_COLOURS = {
    "good": "positive",
    "tentative": "primary",
    "moderate": "warning",
    "fair": "orange",
    "poor": "negative",
    "n/a": "grey",
}


class AgreementCard:
    """Create the copies, compute Krippendorff's alpha, merge the codes."""

    def __init__(self, ctx: AppContext, review: Review):
        self.ctx, self.review = ctx, review
        self.studied: dict | None = None
        with ui.card().classes("w-full gap-2").mark("agreement-card"):
            ui.label("Agreement study").classes("text-lg font-bold")
            ui.label(
                "Papers assigned to two annotators or more (a campaign's "
                '"Annotators per paper") are copied into agreement/<annotator> in '
                "Zotero: each annotator codes their own copy, without seeing the "
                "others' codes. SciLEx then measures Krippendorff's alpha (MASI "
                "distance) per dimension and writes the agreed codes on the papers."
            ).classes("text-sm text-gray-500")
            self.plan_label = ui.label().classes("text-sm").mark("agreement-plan")
            with ui.row().classes("gap-2"):
                ui.button(
                    "Create annotator copies", icon="content_copy", on_click=self.create
                ).props("outline dense no-caps").mark("agreement-create")
                ui.button(
                    "Compute agreement", icon="analytics", on_click=self.compute
                ).props("dense no-caps").mark("agreement-compute")
                self.include_llm = (
                    ui.checkbox("Count the LLM annotators too", value=False)
                    .tooltip(
                        "Each model's answers on the same papers count as one more "
                        "annotator (llm:<model>). They are measured, never merged."
                    )
                    .mark("agreement-include-llm")
                )
            self.results = ui.column().classes("w-full gap-2").mark("agreement-results")
            JobPanel(ctx, review, JOB_KIND, show_logs=False)
        self.refresh_plan()

    def refresh_plan(self) -> None:
        try:
            data = read_results(self.review.results_path)
            plan = service.plan_copies(data) if data is not None else {}
        except Exception:
            plan = {}
        self.plan = plan
        copies = sum(len(who) for who in plan.values())
        self.plan_label.set_text(
            f"{len(plan)} papers with two annotators or more ({copies} copies)."
            if plan
            else "No paper has two annotators yet: assign papers with "
            '"Annotators per paper" = 2 or more, and sync with Zotero.'
        )

    def _start(self, body, title: str) -> None:
        try:
            self.ctx.runner.start_task(
                self.review, JOB_KIND, body, resources=[review_zotero(self.review)]
            )
        except JobConflictError as exc:
            show_error(title, exc, expected=True)

    def create(self) -> None:
        self.refresh_plan()
        if not self.plan:
            ui.notify("No paper with two annotators or more.", type="warning")
            return
        plan, review = dict(self.plan), self.review

        def body(job: Job) -> str:
            job.message = f"Copying {len(plan)} papers in Zotero…"
            return service.create_copies(review, plan).message()

        self._start(body, "Cannot create the copies now")

    async def compute(self) -> None:
        try:
            report, self.studied = await run.io_bound(
                lambda: service.compute(
                    self.review, include_llm=bool(self.include_llm.value)
                )
            )
        except (ValueError, ConnectionError) as exc:
            show_error("Cannot read the copies", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot read the copies", exc)
            return
        self.results.clear()
        with self.results:
            if not report.papers:
                ui.label("No paper has two coded copies yet.").classes("text-sm")
                return
            ui.label(
                f"{report.papers} papers coded by {len(report.annotators)} annotators: "
                + ", ".join(report.annotators)
            ).classes("text-sm").mark("agreement-summary")
            rows = [
                {
                    "dimension": d.dimension,
                    "alpha": "—" if math.isnan(d.alpha) else f"{d.alpha:.2f}",
                    "level": d.level,
                    "papers": d.papers,
                }
                for d in sorted(
                    report.dimensions,
                    key=lambda d: (
                        math.isnan(d.alpha),
                        -(d.alpha if not math.isnan(d.alpha) else 0),
                    ),
                )
            ]
            table = (
                ui.table(
                    columns=[
                        {
                            "name": "dimension",
                            "label": "Dimension",
                            "field": "dimension",
                            "align": "left",
                        },
                        {"name": "alpha", "label": "α (MASI)", "field": "alpha"},
                        {"name": "level", "label": "Agreement", "field": "level"},
                        {"name": "papers", "label": "Papers", "field": "papers"},
                    ],
                    rows=rows,
                )
                .props("dense flat")
                .classes("w-full")
                .mark("agreement-table")
            )
            table.add_slot(
                "body-cell-level",
                '<q-td :props="props"><q-badge :color="'
                + str(LEVEL_COLOURS).replace("'", '"').replace('"', "'")
                + '[props.value]" :label="props.value" /></q-td>',
            )
            ui.label(
                "α ≥ 0.8 good · ≥ 0.667 tentative · ≥ 0.4 moderate · ≥ 0.2 fair · "
                "below: poor. Dimensions coded by a single annotator on every paper "
                "have no α."
            ).classes("text-xs text-gray-500")
            with ui.row().classes("items-center gap-2"):
                majority = ui.checkbox(
                    "Also write the codes a majority gave", value=True
                ).mark("agreement-majority")
                ui.button(
                    "Merge into the papers",
                    icon="merge",
                    on_click=lambda: self.merge(majority.value),
                ).props("outline dense no-caps").mark("agreement-merge")

    def merge(self, with_majority: bool) -> None:
        if not self.studied:
            return
        studied, review = dict(self.studied), self.review

        def body(job: Job) -> str:
            job.message = "Writing the agreed codes in Zotero…"
            report = service.merge(review, studied, with_majority=with_majority)
            job.result = report.disputed
            return report.message() + " Sync with Zotero to update the review."

        self._start(body, "Cannot merge now")
