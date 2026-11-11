"""The dedicated Zotero group of a review: summary card and choice dialog.

Each review has its own Zotero group, chosen among the groups the global
Zotero key reaches (``zotero_source.yml``). Its details and members are on
the review's "Zotero group" page.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.components.zotero_picker import ZoteroPicker
from scilex.gui.services import zotero_library
from scilex.gui.services.workspace import Review

NO_GROUP = (
    "This review has no dedicated Zotero group yet: choose one among the "
    "groups your global Zotero key reaches."
)
NOT_A_GROUP = (
    "This review uses a personal Zotero library: a review should have its own "
    "Zotero group, shared by its members."
)


def group_problem(review: Review) -> str:
    """Why the review's Zotero library is not a dedicated group ("" when it is)."""
    source = zotero_library.load_source(review.folder)
    if source is None:
        return NO_GROUP
    if source.library_type != "group":
        return NOT_A_GROUP
    return ""


def choose_group_dialog(review: Review, on_saved: Callable[[], None]) -> None:
    """Let the user choose the review's group (and optionally one collection)."""
    with one_shot_dialog() as dialog, ui.card().classes("w-[36rem]"):
        ui.label("Zotero group of this review").classes("text-lg font-bold")
        ui.label(
            "The groups your global Zotero key reaches. The review reads, pushes "
            "and exports its papers there; choose a collection to use only part "
            "of the group."
        ).classes("text-sm text-gray-500")
        picker = ZoteroPicker(
            zotero_library.load_source(review.folder), groups_only=True, autoload=True
        )

        def save() -> None:
            source = picker.source()
            if source is None:
                ui.notify("Choose a Zotero group", type="warning")
                return
            zotero_library.save_source(review.folder, source)
            dialog.close()
            on_saved()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Save", on_click=save).mark("zotero-target-save")
    dialog.open()


def review_group_card(review: Review) -> None:
    """Show the review's group, with links to its page and to change it."""
    with ui.card().classes("w-full").mark("zotero-target"):
        ui.label("Zotero group of this review").classes("font-bold")

        @ui.refreshable
        def current() -> None:
            source = zotero_library.load_source(review.folder)
            problem = group_problem(review)
            if source is not None:
                ui.label(source.describe()).classes("text-sm").mark(
                    "zotero-target-current"
                )
            if problem:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("warning").classes("text-warning")
                    ui.label(problem).classes("text-sm").mark("zotero-group-missing")

        current()
        with ui.row().classes("gap-2"):
            ui.button(
                "Change",
                icon="edit",
                on_click=lambda: choose_group_dialog(review, current.refresh),
            ).props("outline dense").mark("zotero-target-change")
            ui.button(
                "Group details",
                icon="groups",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/group"),
            ).props("flat dense no-caps").mark("zotero-group-details")
