"""Review screen: step sidebar plus the content of the active step."""

import importlib
import importlib.util

from nicegui import ui

from scilex.gui.components.stepper import (
    DEFAULT_STEP,
    NEEDS_RESULTS_HINT,
    RESULTS_POLL_SECONDS,
    STEPS,
    USABLE_WHEN_INVALID,
    is_enabled,
    render_sidebar,
)
from scilex.gui.state import AppContext

# Each step is drawn by ``scilex.gui.pages.<step>.render(ctx, review)``;
# a step without its module yet shows a placeholder.


def _invalid_config_banner(review, step: str) -> None:
    with ui.card().classes("w-full bg-red-50").mark("invalid-config"):
        ui.label("This review's scilex.yml cannot be loaded.").classes(
            "font-bold text-negative"
        )
        ui.label(review.error).classes("text-sm whitespace-pre-wrap")
        if step != "configure":  # already there: the editor is below
            ui.button(
                "Fix in ① Configure",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/configure"),
            ).props("flat")


def _reload_when_results_exist(review) -> None:
    """Draw the step once the aggregation writes its results file."""

    def check() -> None:
        if review.has_results:
            timer.cancel()
            ui.navigate.reload()

    timer = ui.timer(RESULTS_POLL_SECONDS, check)


def step_module(step: str):
    """Return the page module drawing ``step``, or None if it is not built yet."""
    name = f"scilex.gui.pages.{step}"
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def render(ctx: AppContext, review_id: str, step: str = DEFAULT_STEP) -> None:
    """Draw review ``review_id`` with ``step`` active."""
    review = ctx.workspace.get(review_id)
    if review is None:
        ui.label("This review is no longer available.").classes("p-6")
        ui.button("Back to my reviews", on_click=lambda: ui.navigate.to("/"))
        return
    if step not in STEPS:
        step = DEFAULT_STEP
    ui.page_title(f"{STEPS[step].label_for(review)} · {review.name} · SciLEx")

    with ui.row().classes("w-full p-4 gap-6 no-wrap items-start"):
        with ui.column().classes("gap-0"):
            ui.label(review.name).classes("text-lg font-bold px-2")
            ui.label(str(review.folder)).classes(
                "text-xs text-gray-500 px-2 pb-2 break-all w-52"
            )
            render_sidebar(review, step)
        with ui.column().classes("grow flex-1 w-0 gap-3 min-w-0"):
            module = step_module(step)
            if review.error:
                _invalid_config_banner(review, step)
            if review.error and step not in USABLE_WHEN_INVALID:
                pass
            elif not is_enabled(STEPS[step], review):
                ui.label(NEEDS_RESULTS_HINT).mark("needs-results")
                _reload_when_results_exist(review)
            elif module is not None:
                module.render(ctx, review)
            else:
                ui.label(STEPS[step].label_for(review)).classes("text-2xl font-bold")
                ui.label("Not available yet.").classes("text-gray-500")
