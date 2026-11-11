"""Dialogs built on each click."""

import asyncio

from nicegui import ui

# Deleting the dialog inside close() would delete the slot the click handler
# still runs in: a ui.navigate.to() or ui.notify() after close() would be lost.
DELETE_DELAY_SECONDS = 1.0


def one_shot_dialog() -> ui.dialog:
    """Return a dialog deleted shortly after it is closed.

    Dialogs created on each click would otherwise pile up in the page
    (hidden, but kept in memory and sent to the browser).
    """
    dialog = ui.dialog()

    def delete() -> None:
        if not dialog.is_deleted and not dialog.value:
            dialog.delete()

    def delete_when_closed(event) -> None:
        if not event.value and not dialog.is_deleted:
            asyncio.get_running_loop().call_later(DELETE_DELAY_SECONDS, delete)

    dialog.on_value_change(delete_when_closed)
    return dialog
