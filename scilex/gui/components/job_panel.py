"""Status, progress bar and log tail of the latest job of one kind."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from scilex.gui.services import clipboard
from scilex.gui.services.jobs import Job
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext
from scilex.pipeline import jobs as job_states

LOG_LINES_SHOWN = 50
STATUS_LABELS = {
    job_states.PENDING: "Starting…",
    job_states.RUNNING: "Running",
    job_states.CANCELLING: "Cancelling…",
    job_states.COMPLETED: "Completed",
    job_states.FAILED: "Failed",
    job_states.CANCELLED: "Cancelled",
}


class BusyNotice:
    """One line explaining why buttons are disabled: a conflicting job runs.

    Jobs that do not conflict with the page's action (other reviews, readers,
    enrichers of other columns) run alongside and are not mentioned. The label
    is created once; ``update`` only changes its text and visibility, so it is
    safe to call on every tick.
    """

    def __init__(self, ctx: AppContext):
        """Draw the (initially hidden) line at the current position."""
        self.ctx = ctx
        self.label = ui.label().classes("text-sm text-warning").mark("busy-notice")
        self.label.set_visibility(False)

    def update(self, own_job: Job | None = None, blocking: Job | None = None) -> None:
        """Show ``blocking`` (from ``runner.conflicting_job``) unless it is ``own_job``."""
        busy = blocking is not None and blocking is not own_job
        self.label.set_visibility(busy)
        if busy:
            self.label.text = f"Waiting for {blocking.describe()} to finish"


class JobPanel:
    """Live view of ``runner.latest_for(review.id, kind)``, refreshed every 0.5 s.

    ``on_change(job)`` is called on every refresh, so the page can enable or
    disable its own buttons; ``on_finished(job)`` once when a job it watched
    reaches a terminal state (e.g. to show the result).
    """

    def __init__(
        self,
        ctx: AppContext,
        review: Review,
        kind: str,
        *,
        on_change: Callable[[Job | None], None] | None = None,
        on_finished: Callable[[Job], None] | None = None,
        show_logs: bool = True,
    ):
        """Draw the panel at the current position of the page."""
        self.ctx, self.review, self.kind = ctx, review, kind
        self.on_change, self.on_finished = on_change, on_finished
        self.status = ui.label().classes("font-bold").mark(f"{kind}-status")
        self.progress = ui.linear_progress(value=0, show_value=False).classes("w-full")
        self.message = ui.label().classes("text-sm")
        self.log_view = None
        if show_logs:
            self.log_view = (
                ui.log(max_lines=LOG_LINES_SHOWN)
                .classes("w-full max-w-full h-64 text-xs select-text")
                .style("width: 100%")
            )
            self.copy_button = (
                ui.button("Copy log", icon="content_copy", on_click=self.copy_log)
                .props("flat dense no-caps")
                .mark(f"{kind}-copy-log")
            )
        self._tail: list[str] = []
        # Jobs already finished when the page opened are not reported again;
        # any other job is reported once it ends, even if it ended between two
        # ticks (a fast export can start and finish within 0.5 s).
        existing = self.job
        self._reported: set[str] = (
            {existing.id} if existing is not None and not existing.is_active else set()
        )
        self.refresh()
        self.timer = ui.timer(0.5, self.refresh)

    @property
    def job(self) -> Job | None:
        """Latest job of this kind for the review."""
        return self.ctx.runner.latest_for(self.review.id, self.kind)

    def blocking(self, resources=None) -> Job | None:
        """The active job that would refuse a new job of this kind (or None)."""
        return self.ctx.runner.conflicting_job(self.review, self.kind, resources)

    def refresh(self) -> None:
        """Update the widgets from the job state."""
        job = self.job
        if self.on_change is not None:
            self.on_change(job)
        if self.log_view is not None:
            # No job yet: an empty log box would only take room.
            self.log_view.set_visibility(job is not None)
            self.copy_button.set_visibility(job is not None)
        if job is None:
            # Nothing to report: keep the elements (markers) but show nothing.
            self.status.text = ""
            self.status.set_visibility(False)
            self.message.text = ""
            self.progress.set_visibility(False)
            return
        self.status.set_visibility(True)
        self.progress.set_visibility(True)
        self.status.text = STATUS_LABELS.get(job.status, job.status)
        self.progress.value = job.progress / 100
        self.message.text = job.message
        failed = job.status == job_states.FAILED
        if failed:
            self.message.classes(add="text-negative")
        else:
            self.message.classes(remove="text-negative")
        # A failed job keeps its bar where it stopped, in red: not "in progress".
        self.progress.props(f"color={'negative' if failed else 'primary'}")
        self._append_new_logs(job)
        if not job.is_active and job.id not in self._reported:
            self._reported.add(job.id)
            if self.on_finished is not None:
                self.on_finished(job)

    def copy_log(self) -> None:
        """Copy the whole log of the job (not only the lines shown) to the clipboard."""
        job = self.job
        if job is None or not job.logs:
            ui.notify("No log to copy yet.")
            return
        text = "\n".join(job.logs)
        if clipboard.copy_text(text):
            ui.notify(f"Copied {len(job.logs)} log lines.", type="positive")
        else:
            ui.clipboard.write(text)  # browser fallback (needs a secure context)
            ui.notify("Log sent to the browser clipboard.")

    def _append_new_logs(self, job: Job) -> None:
        if self.log_view is None:
            return
        # The job trims its log list in place, so compare the tail, not the length.
        tail = job.logs[-LOG_LINES_SHOWN:]
        if tail == self._tail:
            return
        new_lines = _lines_after(self._tail, tail)
        if new_lines is None:
            self.log_view.clear()
            new_lines = tail
        # ui.log keeps at most LOG_LINES_SHOWN lines: push only what is new
        # instead of re-sending the whole view on every tick.
        for line in new_lines:
            self.log_view.push(line)
        self._tail = tail


def _lines_after(previous: list[str], current: list[str]) -> list[str] | None:
    """Lines of ``current`` that follow ``previous`` (None if they do not overlap).

    ``current`` is the latest window of the log; it is a continuation of
    ``previous`` when one of its prefixes is a suffix of ``previous``.
    """
    if not previous:
        return current
    for start in range(len(previous)):
        overlap = previous[start:]
        if current[: len(overlap)] == overlap:
            return current[len(overlap) :]
    return None
