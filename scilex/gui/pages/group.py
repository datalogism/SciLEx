"""The review's Zotero group: its details and the review's members.

Each review has a dedicated Zotero group, chosen among the groups the global
Zotero key reaches. This page shows the group (type, rights, papers, link on
zotero.org), the part of it the review uses, and the people: the group's
owner, admins and members, completed by ``members.yml`` (names, ORCID iDs).
"""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.review_group import choose_group_dialog, group_problem
from scilex.gui.services import keys_editor, members, zotero_library
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

GROUP_TYPES = {
    "Private": "Private (members only)",
    "PublicClosed": "Public, closed membership",
    "PublicOpen": "Public, open membership",
}
ROLE_COLORS = {
    "owner": "primary",
    "admin": "secondary",
    "member": "positive",
    "contributor": "grey",
    "manual": "grey",
}


def _fact(name: str, value: str) -> None:
    with ui.row().classes("gap-2 items-baseline no-wrap"):
        ui.label(name).classes("text-sm text-gray-500 w-40 shrink-0")
        ui.label(value or "—").classes("text-sm")


def render(ctx: AppContext, review: Review) -> None:
    """Draw the review's Zotero group page."""

    @ui.refreshable
    def body() -> None:
        source = zotero_library.load_source(review.folder)
        problem = group_problem(review)
        with ui.row().classes("items-center gap-2"):
            ui.label("Zotero group").classes("text-2xl font-bold")
            ui.button(
                "Change group" if source else "Choose a group",
                icon="edit",
                on_click=lambda: choose_group_dialog(review, body.refresh),
            ).props("outline dense no-caps").mark("group-change")
        if problem:
            with (
                ui.card().classes("w-full bg-orange-50").mark("group-problem"),
                ui.row().classes("items-center gap-2 no-wrap"),
            ):
                ui.icon("warning").classes("text-warning")
                ui.label(problem).classes("text-sm")
        if source is None:
            return
        with ui.card().classes("w-full gap-1"):
            ui.label("What the review uses").classes("font-bold")
            _fact("Library", source.describe())
            _fact(
                "Scope",
                "the whole group"
                if source.whole_library
                else f"collection {source.collection_name}"
                + (" and its sub-collections" if source.include_subcollections else ""),
            )
        details = ui.column().classes("w-full gap-3")
        with details:
            ui.spinner()
        ui.timer(0, lambda: _load(review, source, details), once=True)

    body()


async def _load(review: Review, source, container: ui.column) -> None:
    """Read the group from Zotero, then draw its details and people."""
    group = error = info = None
    if source.library_type == "group":
        try:
            keys = keys_editor.effective_keys(review.folder)
            group = await run.io_bound(zotero_library.group_details, source, keys)
            info = await run.io_bound(
                zotero_library.key_info, zotero_library.zotero_api_key(keys)
            )
        except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
            error = exc
        except Exception as exc:
            error = exc
            show_error("Cannot read the Zotero group", exc)
    container.clear()
    with container:
        if error is not None:
            ui.label(f"The group could not be read: {error}").classes(
                "text-sm text-negative"
            ).mark("group-error")
        if group is not None:
            _group_card(group, info)
        _members_card(review, group)


def _group_card(group, info) -> None:
    with ui.card().classes("w-full gap-1").mark("group-details"):
        with ui.row().classes("items-center gap-2"):
            ui.label(group.name or f"Group {group.group_id}").classes(
                "text-lg font-bold"
            )
            ui.link("Open on zotero.org", group.web_url, new_tab=True).classes(
                "text-sm"
            )
        if group.description:
            ui.label(group.description).classes("text-sm text-gray-600")
        _fact("Group id", group.group_id)
        _fact("Type", GROUP_TYPES.get(group.group_type, group.group_type))
        _fact("Papers and notes", str(group.num_items))
        _fact("People", str(group.people))
        _fact("Library readable by", group.library_reading)
        _fact("Library editable by", group.library_editing)
        _fact("Files editable by", group.file_editing)
        _fact("Created", group.created[:10])
        _fact("Last modified", group.last_modified[:10])
        if info is not None:
            access = info.group_access(group.group_id)
            _fact(
                "Your key",
                {"write": "read and write", "read": "read only (pushes will fail)"}.get(
                    access, "no access"
                ),
            )
        if group.url:
            ui.link(group.url, group.url, new_tab=True).classes("text-sm")


def _members_card(review: Review, group) -> None:
    with ui.card().classes("w-full gap-2").mark("group-members"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Members of the review").classes("text-lg font-bold")
            refresh = (
                ui.button("Find names in Zotero", icon="sync")
                .props("outline dense no-caps")
                .mark("group-members-discover")
            )
            ui.button(
                "Edit ORCID iDs and assignments",
                icon="sell",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/annotate"),
            ).props("flat dense no-caps")
        ui.label(
            "The group's owner, admins and members, then the other people of the "
            "review (who edited papers, or were added by hand). Zotero gives only "
            "user ids: names come with the papers they created or edited."
        ).classes("text-sm text-gray-500")

        @ui.refreshable
        def table() -> None:
            rows = members.group_roster(group, members.load(review.folder))
            if not rows:
                ui.label("No member known yet.").classes("text-sm text-gray-500")
                return
            ui.table(
                columns=[
                    {
                        "name": "label",
                        "label": "Name",
                        "field": "label",
                        "align": "left",
                    },
                    {"name": "role", "label": "Role", "field": "role", "align": "left"},
                    {
                        "name": "username",
                        "label": "Zotero user",
                        "field": "username",
                        "align": "left",
                    },
                    {
                        "name": "orcid",
                        "label": "ORCID iD",
                        "field": "orcid",
                        "align": "left",
                    },
                    {"name": "group", "label": "In the group", "field": "group"},
                ],
                rows=[
                    {
                        "label": row.label,
                        "role": row.role,
                        "username": row.username or "—",
                        "orcid": row.orcid or "missing",
                        "group": "yes" if row.in_group else "no",
                    }
                    for row in rows
                ],
                row_key="label",
            ).classes("w-full").props("dense flat").mark("group-members-table")

        table()

        async def discover() -> None:
            refresh.disable()
            try:
                found = await run.io_bound(members.discover, review)
            except (
                ValueError,
                ConnectionError,
                zotero_library.ZoteroNotConfiguredError,
            ) as exc:
                show_error("Cannot read the members", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot read the members", exc)
                return
            finally:
                refresh.enable()
            ui.notify(f"{len(found)} members known", type="positive")
            table.refresh()

        refresh.on_click(discover)
