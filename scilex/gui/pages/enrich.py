"""Enrich screen: add external data to the papers (citations, Papers with Code...).

Usable before screening (on every paper) or after it (on the papers kept),
through the "Only the papers kept" option of each source.
"""

from nicegui import ui

from scilex.gui.pages.analyses import render_tabs
from scilex.gui.services import analyses as service
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Enrich screen of ``review``."""
    ui.label("Enrich").classes("text-2xl font-bold")
    ui.label(
        "Add data from external sources to the papers. Run it before ③ Screen on "
        "every paper, or after it on the papers you kept."
    ).classes("text-gray-500")
    render_tabs(ctx, review, service.in_group("enrich"))
