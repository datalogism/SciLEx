"""Which papers Explore and the Dashboard show: screened results, automatic, all.

Shown once the review has a screened-results collection (Zotero group page,
:mod:`scilex.gui.services.collection_roles`); the choice is remembered per
review while the app runs.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from scilex.gui.services import collection_roles
from scilex.gui.services.screening import ScreeningSession, load_results
from scilex.gui.services.workspace import Review

_chosen: dict[str, str] = {}


def current(review: Review) -> str:
    roles = collection_roles.load(review.folder)
    if not collection_roles.configured(roles):
        return collection_roles.SCOPE_ALL
    return _chosen.get(str(review.folder), collection_roles.default_scope(roles))


def load_session(review: Review, scope: str) -> ScreeningSession:
    """The papers of ``scope`` (all of them while no collection is screened)."""
    roles = collection_roles.load(review.folder)
    data = collection_roles.filter_scope(load_results(review), roles, scope)
    return ScreeningSession(review, results=data)


def switch(review: Review, on_change: Callable[[str], None]) -> ui.toggle | None:
    """The scope toggle (None while the review has no screened collection)."""
    roles = collection_roles.load(review.folder)
    if not collection_roles.configured(roles):
        return None

    def changed(event) -> None:
        _chosen[str(review.folder)] = event.value
        on_change(event.value)

    with ui.row().classes("items-center gap-2"):
        ui.label("Papers").classes("text-sm text-gray-500")
        toggle = (
            ui.toggle(collection_roles.SCOPES, value=current(review), on_change=changed)
            .props("dense no-caps")
            .mark("scope-switch")
        )
        ui.label(
            "Screened results = the papers of the screened collections "
            "(Zotero group page)."
        ).classes("text-xs text-gray-400")
    return toggle
