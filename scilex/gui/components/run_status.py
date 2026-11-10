"""Coloured "last run" chip of a costly action, so it is not run again by mistake.

Red: never run for this review. Green: completed within
``run_history.RECENT_DAYS`` days. Grey: completed before that.
"""

from __future__ import annotations

from nicegui import ui

from scilex.gui.services import run_history
from scilex.gui.services.workspace import Review

# Quasar colours of each state (chip background, tab alert dot).
COLORS = {
    run_history.NEVER: "negative",
    run_history.RECENT: "positive",
    run_history.OLD: "grey-6",
}
ICONS = {
    run_history.NEVER: "radio_button_unchecked",
    run_history.RECENT: "check_circle",
    run_history.OLD: "history",
}


def state_of(review: Review, key: str, history: dict | None = None):
    """Return ``(run, freshness)`` of action ``key`` for ``review``."""
    run = run_history.last_run(review, key, history)
    return run, run_history.freshness(run)


class RunStatus:
    """Chip showing when action ``key`` last completed; call ``update`` after a run.

    ``label`` names the action in the chip (e.g. "Collection") when one page
    shows several of them.
    """

    def __init__(
        self,
        review: Review,
        key: str,
        label: str | None = None,
        history: dict | None = None,
    ):
        """Draw the chip at the current position."""
        self.review, self.key, self.label = review, key, label
        self.chip = (
            ui.chip("", icon="history")
            .props("dense square text-color=white")
            .classes("text-xs")
            .mark(f"run-status-{key}")
        )
        with self.chip:
            self.tooltip = ui.tooltip("")
        self.freshness = run_history.NEVER
        self.update(history)

    def update(self, history: dict | None = None) -> str:
        """Re-read the history and redraw; return the freshness shown."""
        run, fresh = state_of(self.review, self.key, history)
        text = run_history.describe(run)
        self.chip.text = f"{self.label}: {text}" if self.label else text
        self.chip.props(f"color={COLORS[fresh]} icon={ICONS[fresh]}")
        self.tooltip.text = run_history.details(run)
        self.freshness = fresh
        return fresh


def set_tab_dot(tab: ui.tab, fresh: str) -> None:
    """Show the freshness as the coloured alert dot of a tab."""
    tab.props(f"alert={COLORS[fresh]}")
