"""Explore from anywhere: a button at the top right of every review screen.

It opens the Explore screen (articles, filters, eligibility criteria, notice)
full screen over the current step, so the step keeps its state. The Explore
content is loaded on the first opening and kept; "Reload" reads the papers
again (after a step changed them).
"""

from __future__ import annotations

from nicegui import ui

from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext


def render_explore_button(ctx: AppContext, review: Review) -> None:
    """The top-right Explore button of ``review`` (once it has papers)."""
    if not review.has_results or review.error:
        return
    from scilex.gui.pages import explore

    with (
        ui.dialog().props("maximized") as dialog,
        ui.card().classes("w-full h-full gap-2 overflow-auto").mark("explore-overlay"),
    ):
        with ui.row().classes("w-full items-center justify-end gap-2"):
            ui.button(
                "Open as a page",
                icon="open_in_new",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/explore"),
            ).props("flat dense no-caps")
            ui.button("Reload", icon="refresh", on_click=lambda: draw()).props(
                "flat dense no-caps"
            ).mark("explore-overlay-reload")
            ui.button(icon="close", on_click=dialog.close).props(
                "flat round dense"
            ).tooltip("Close (Esc)").mark("explore-overlay-close")
        content = ui.column().classes("w-full gap-3")

    def draw() -> None:
        content.clear()
        with content:
            explore.render(ctx, review)

    def open_explore() -> None:
        if not content.default_slot.children:
            draw()
        dialog.open()

    with ui.element("div").classes("fixed top-3 right-4 z-[3000]"):
        ui.button("Explore", icon="manage_search", on_click=open_explore).props(
            "unelevated no-caps"
        ).tooltip("Browse and filter the papers, from any step").mark(
            "explore-anywhere"
        )
