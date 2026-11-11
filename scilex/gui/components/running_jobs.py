"""Which jobs are running: a button with their count, opening their list.

Shown on the home page and in every review. Each job shows its review, what
it does, its progress and message; it can be opened (its review) or cancelled.
Jobs finished in the last minutes stay listed with their outcome.
"""

from __future__ import annotations

from datetime import datetime

from nicegui import ui

from scilex.gui.services.jobs import Job
from scilex.gui.state import AppContext

REFRESH_SECONDS = 1.0
STATUS_ICONS = {
    "pending": ("schedule", "text-gray-500"),
    "running": ("autorenew", "text-primary"),
    "cancelling": ("hourglass_bottom", "text-warning"),
    "completed": ("check_circle", "text-positive"),
    "failed": ("error", "text-negative"),
    "cancelled": ("cancel", "text-gray-500"),
}


def _elapsed(job: Job) -> str:
    end = job.finished_at or datetime.now()
    seconds = int((end - job.started_at).total_seconds())
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"


def render_jobs_button(ctx: AppContext) -> None:
    """Draw the running-jobs button; its badge and list refresh every second."""
    with (
        ui.button(icon="pending_actions")
        .props("flat round dense")
        .mark("jobs-button") as button
    ):
        badge = (
            ui.badge("0", color="primary").props("floating rounded").mark("jobs-count")
        )
        tooltip = ui.tooltip("No job running")
        with ui.menu().props("anchor='bottom right' self='top right'") as menu:
            entries = ui.column().classes("p-3 gap-2 w-[28rem]").mark("jobs-list")

    def draw_list() -> None:
        entries.clear()
        active = ctx.runner.active_jobs()
        recent = ctx.runner.recent_jobs()
        with entries:
            ui.label("Running jobs").classes("font-bold")
            if not active:
                ui.label("No job running.").classes("text-sm text-gray-500")
            for job in active:
                _job_row(ctx, job, menu)
            if recent:
                ui.separator()
                ui.label("Finished in the last 15 minutes").classes(
                    "text-xs text-gray-500"
                )
                for job in recent[:8]:
                    _job_row(ctx, job, menu)

    def tick() -> None:
        count = len(ctx.runner.active_jobs())
        badge.set_text(str(count))
        badge.set_visibility(count > 0)
        tooltip.text = (
            f"{count} job{'s' if count > 1 else ''} running"
            if count
            else "No job running"
        )
        if menu.value:
            draw_list()

    button.on_click(draw_list)
    tick()
    ui.timer(REFRESH_SECONDS, tick)


def _job_row(ctx: AppContext, job: Job, menu: ui.menu) -> None:
    icon, color = STATUS_ICONS.get(job.status, ("help", "text-gray-500"))
    with ui.column().classes("w-full gap-0").mark(f"job-{job.id}"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.icon(icon).classes(color)
            ui.label(job.describe()).classes("text-sm font-medium grow")
            ui.label(_elapsed(job)).classes("text-xs text-gray-500")
            ui.button(
                icon="open_in_new",
                on_click=lambda j=job: (
                    menu.close(),
                    ui.navigate.to(f"/review/{j.review_id}"),
                ),
            ).props("flat round dense size=sm").tooltip("Open its review")
            if job.is_active:
                ui.button(
                    icon="stop",
                    on_click=lambda j=job: ctx.runner.cancel(j.id),
                ).props("flat round dense size=sm color=negative").tooltip(
                    "Cancel"
                ).mark(f"job-cancel-{job.id}")
        if job.is_active:
            ui.linear_progress(value=job.progress / 100, show_value=False).props(
                "rounded"
            ).classes("w-full")
        detail = job.error if job.status == "failed" and job.error else job.message
        if detail:
            ui.label(detail).classes("text-xs text-gray-600 break-words")
