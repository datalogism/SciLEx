"""Folder picker drawn in the page, for when there is no native file dialog.

The app's server always runs on the user's machine, so listing folders on the
server side lists the user's own folders, in a browser tab too.
"""

from functools import partial
from pathlib import Path

from nicegui import ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.services.workspace import resolve_folder, reviews_home


def list_subfolders(folder: Path) -> list[Path]:
    """Visible subfolders of ``folder``, sorted by name; empty if unreadable."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    subfolders = []
    for entry in entries:
        try:
            if entry.is_dir() and not entry.name.startswith("."):
                subfolders.append(entry)
        except OSError:  # broken link, no permission
            continue
    return sorted(subfolders, key=lambda path: path.name.lower())


def _start_folder(initial: str | None) -> Path:
    # The typed folder may not exist yet: start at its closest parent.
    path = resolve_folder(initial) if initial else reviews_home()
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path.home()


async def pick_folder_in_page(initial: str | None = None) -> str | None:
    """Let the user browse to a folder; return its path, or None if cancelled."""
    current = [_start_folder(initial)]

    with one_shot_dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label("Choose a folder").classes("text-lg font-bold")

        @ui.refreshable
        def listing() -> None:
            folder = current[0]
            with ui.row().classes("w-full items-center no-wrap"):
                ui.button(
                    icon="arrow_upward", on_click=lambda: go(folder.parent)
                ).props("flat dense").tooltip("Parent folder").set_enabled(
                    folder.parent != folder
                )
                ui.button(icon="home", on_click=lambda: go(Path.home())).props(
                    "flat dense"
                ).tooltip("Home folder")
                ui.label(str(folder)).classes("text-sm break-all").mark("picker-path")
            with ui.scroll_area().classes("w-full h-72 border rounded"):
                subfolders = list_subfolders(folder)
                if not subfolders:
                    ui.label("No subfolder").classes("text-gray-500 p-2")
                for sub in subfolders:
                    ui.item(sub.name, on_click=partial(go, sub)).classes(
                        "w-full"
                    ).props("clickable dense").mark(f"picker-{sub.name}")

        def go(folder: Path) -> None:
            current[0] = folder
            listing.refresh()

        listing()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(
                "Select this folder", on_click=lambda: dialog.submit(str(current[0]))
            ).mark("picker-select")

    return await dialog
