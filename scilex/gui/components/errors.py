"""Error dialog with a copyable diagnostic report."""

import logging

from nicegui import ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.services.diagnostics import diagnostic_text

logger = logging.getLogger(__name__)


def show_error(title: str, exc: BaseException, *, expected: bool = False) -> None:
    """Show ``exc`` in a dialog.

    Args:
        title: What the user was trying to do.
        exc: The error.
        expected: True for user-facing errors (invalid file, missing config):
            the message alone is shown, without the diagnostic report.
    """
    if not expected:
        logger.error("%s", title, exc_info=exc)
    with one_shot_dialog() as dialog, ui.card().classes("w-[36rem]"):
        ui.label(title).classes("text-lg font-bold")
        # Long paths have no spaces: let them wrap instead of being cut.
        ui.label(str(exc)).classes("whitespace-pre-wrap").style(
            "overflow-wrap: anywhere"
        )
        with ui.row().classes("w-full justify-end"):
            if not expected:
                report = diagnostic_text(exc)
                ui.button(
                    "Copy diagnostics",
                    icon="content_copy",
                    on_click=lambda: (
                        ui.clipboard.write(report),
                        ui.notify("Diagnostics copied"),
                    ),
                ).props("flat")
            ui.button("Close", on_click=dialog.close)
    dialog.open()
