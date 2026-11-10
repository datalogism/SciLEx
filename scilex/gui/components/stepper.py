"""Sidebar listing the pipeline steps of a review."""

from dataclasses import dataclass

from nicegui import ui

from scilex.gui.components.branding import render_logo
from scilex.gui.services.workspace import Review


@dataclass(frozen=True)
class Step:
    """One entry of the sidebar."""

    key: str
    label: str
    icon: str
    needs_results: bool = False
    # Label once the review has papers (collected, imported or snowballed).
    label_with_results: str | None = None

    def label_for(self, review: Review) -> str:
        """Return the label shown for ``review``."""
        if self.label_with_results and review.has_results:
            return self.label_with_results
        return self.label


PIPELINE_STEPS = (
    Step("overview", "Overview", "dashboard"),
    Step("configure", "① Configure", "tune"),
    Step(
        "collect",
        "② Collect",
        "travel_explore",
        label_with_results="② Extend collect",
    ),
    Step("enrich", "③ Enrich", "auto_awesome", needs_results=True),
    Step("screen", "④ Screen", "fact_check", needs_results=True),
    Step("analyses", "⑤ Analyses", "insights", needs_results=True),
    Step("annotate", "⑥ Annotate", "sell"),
    Step("export", "⑦ Export", "ios_share", needs_results=True),
)
EXTRA_STEPS = (Step("keys", "API keys", "key"),)
STEPS = {step.key: step for step in (*PIPELINE_STEPS, *EXTRA_STEPS)}
DEFAULT_STEP = "overview"  # opening a review shows its summary first
RESULTS_POLL_SECONDS = 1.0
INVALID_CONFIG_HINT = "Fix scilex.yml in ① Configure first"
# Steps usable while scilex.yml cannot be loaded (to repair it).
USABLE_WHEN_INVALID = ("configure", "keys")
NEEDS_RESULTS_HINT = (
    "Available once a collection has been aggregated (step ②: Run, or "
    "Aggregate existing results after a stopped collection)."
)


def is_enabled(step: Step, review: Review) -> bool:
    """Return True if ``step`` can be opened for ``review``."""
    return review.has_results or not step.needs_results


def render_sidebar(review: Review, active: str) -> None:
    """Draw the steps of ``review``, highlighting ``active``.

    Steps that need results unlock by themselves as soon as the aggregation
    writes its results file (checked every second), without a page reload.
    """
    locked: list[ui.button] = []
    with ui.column().classes("w-52 gap-1 shrink-0"):
        render_logo("w-36 mb-2 cursor-pointer").on("click", lambda: ui.navigate.to("/"))
        for step in PIPELINE_STEPS:
            _step_button(review, step, active, locked)
        ui.separator()
        for step in EXTRA_STEPS:
            _step_button(review, step, active, locked)
        ui.button(
            "My reviews", icon="folder_open", on_click=lambda: ui.navigate.to("/")
        ).props("flat align=left no-caps").classes("w-full")

    if not locked:
        return

    def unlock_when_results_exist() -> None:
        if not review.has_results:
            return
        for button in locked:
            button.enable()
            for tooltip in [
                c for c in button.default_slot.children if isinstance(c, ui.tooltip)
            ]:
                tooltip.delete()
        locked.clear()
        timer.cancel()

    timer = ui.timer(RESULTS_POLL_SECONDS, unlock_when_results_exist)


def _step_button(
    review: Review, step: Step, active: str, locked: list[ui.button]
) -> None:
    button = ui.button(
        step.label_for(review),
        icon=step.icon,
        on_click=lambda: ui.navigate.to(f"/review/{review.id}/{step.key}"),
    ).props("align=left no-caps" + ("" if step.key == active else " flat"))
    button.classes("w-full").mark(f"step-{step.key}")
    if review.error and step.key not in USABLE_WHEN_INVALID:
        # Never unlocked by the results timer: the config must be fixed first.
        button.disable()
        button.tooltip(INVALID_CONFIG_HINT)
    elif not is_enabled(step, review):
        button.disable()
        button.tooltip(NEEDS_RESULTS_HINT)
        locked.append(button)
