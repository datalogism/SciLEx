"""Zotero sync icon, top left of every review page.

Shows at a glance whether Zotero has updates to get, whether SciLEx has changes
(enrichment, screening, tags) to push, or both; a click opens the details with
the actions. See :mod:`scilex.gui.services.zotero_sync`.
"""

from __future__ import annotations

from datetime import datetime

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import zotero_sync as sync
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

CHECK_EVERY_SECONDS = 120
LISTED = 8

# state -> (icon, colour, tooltip)
LOOKS = {
    "checking": ("cloud_sync", "grey-6", "Checking Zotero…"),
    "error": ("cloud_off", "grey-6", ""),
    "unlinked": ("link_off", "orange-8", "Not synced with Zotero yet: click to link"),
    "synced": ("cloud_done", "positive", "In sync with Zotero"),
    "pull": ("cloud_download", "primary", "Zotero has updates to get"),
    "push": ("cloud_upload", "warning", "SciLEx has changes to push to Zotero"),
    "both": ("sync", "deep-purple-6", "Updates on both sides: get and push"),
    "conflict": ("sync_problem", "negative", "Changed on both sides: choose what to keep"),
}


def badge_text(status: sync.SyncStatus) -> str:
    """Short count shown on the icon ("" for none)."""
    state = status.state
    if state == "pull":
        return str(status.zotero_count)
    if state == "push":
        return str(status.local_count)
    if state == "both":
        return f"↓{status.zotero_count} ↑{status.local_count}"
    if state == "conflict":
        return str(len(status.conflicts))
    return ""


def summary(status: sync.SyncStatus) -> str:
    """One sentence describing ``status``."""
    if status.error:
        return status.error
    if status.never_synced:
        return (
            f"Not synced yet: link the {status.local_unlinked} papers with their "
            "Zotero items to follow the changes on both sides."
        )
    parts = []
    if status.zotero_count:
        parts.append(
            f"Zotero: {len(status.zotero_changed)} changed, {len(status.zotero_new)} new, "
            f"{len(status.zotero_removed)} removed"
        )
    if status.local_count:
        parts.append(f"SciLEx: {status.local_count} changed")
    if status.conflicts:
        parts.append(f"{len(status.conflicts)} conflicts")
    if not parts:
        return f"In sync with Zotero ({status.linked} papers linked)."
    return " · ".join(parts) + "."


def render_sync_badge(ctx: AppContext, review: Review) -> None:
    """Draw the icon; it checks Zotero in the background."""
    current: dict = {"status": None}
    with ui.button(icon=LOOKS["checking"][0]).props(
        f"flat round dense color={LOOKS['checking'][1]}"
    ).mark("sync-badge") as button:
        tooltip = ui.tooltip(LOOKS["checking"][2])
        badge = ui.badge("").props("floating rounded").mark("sync-badge-count")
        badge.set_visibility(False)

    def show(status: sync.SyncStatus) -> None:
        current["status"] = status
        icon, colour, text = LOOKS[status.state]
        button.props(f"icon={icon} color={colour}")
        checked = datetime.fromtimestamp(status.checked_at).strftime("%H:%M")
        tooltip.set_text(f"{text or summary(status)} (checked {checked})")
        count = badge_text(status)
        badge.set_text(count)
        badge.props(f"color={colour}")
        badge.set_visibility(bool(count))
        button.mark(f"sync-badge sync-state-{status.state}")

    async def refresh(force: bool = False) -> None:
        status = await run.io_bound(sync.cached_check, review, force)
        if not button.is_deleted:
            show(status)

    button.on_click(lambda: _open_dialog(ctx, review, current, refresh))
    ui.timer(0.1, refresh, once=True)
    ui.timer(CHECK_EVERY_SECONDS, lambda: refresh(True))


def _busy(ctx: AppContext) -> bool:
    if ctx.runner.active_job() is not None:
        ui.notify("A job is running: sync when it has finished", type="warning")
        return True
    return False


def _open_dialog(ctx: AppContext, review: Review, current: dict, refresh) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full gap-2").mark(
        "sync-dialog"
    ):
        ui.label("Zotero sync").classes("text-lg font-bold")
        body = ui.column().classes("w-full gap-2")

        async def act(label: str, function, *args, reload: bool = False) -> None:
            if _busy(ctx):
                return
            spinner.set_visibility(True)
            try:
                result = await run.io_bound(function, review, *args)
            except sync.SyncError as exc:
                show_error(f"Cannot {label}", exc, expected=True)
                return
            except Exception as exc:
                show_error(f"Cannot {label}", exc)
                return
            finally:
                spinner.set_visibility(False)
            if isinstance(result, dict):
                ui.notify(", ".join(f"{k}: {v}" for k, v in result.items()))
            await recheck()
            if reload:
                ui.navigate.reload()

        async def recheck() -> None:
            spinner.set_visibility(True)
            await refresh(True)
            spinner.set_visibility(False)
            draw()

        def draw() -> None:
            status: sync.SyncStatus | None = current["status"]
            body.clear()
            with body:
                if status is None:
                    ui.label("Checking Zotero…")
                    return
                ui.label(summary(status)).classes("font-medium").mark("sync-summary")
                if status.never_synced:
                    ui.label(
                        "Linking matches each paper with its Zotero item (by Zotero "
                        "key, DOI, URL or title) and remembers both sides as they are "
                        "now. Nothing is changed in Zotero."
                    ).classes("text-xs text-gray-500")
                    ui.button(
                        "Link with Zotero",
                        icon="link",
                        on_click=lambda: act("link with Zotero", sync.link, reload=True),
                    ).props("no-caps").mark("sync-link")
                    return
                if status.error:
                    return
                _conflicts(status, review, act)
                _side(
                    "From Zotero",
                    status.zotero_changed,
                    [
                        f"{len(status.zotero_new)} new papers in the collection"
                        if status.zotero_new else "",
                        f"{len(status.zotero_removed)} papers removed from Zotero "
                        "(kept in SciLEx)" if status.zotero_removed else "",
                    ],
                    "Get Zotero updates",
                    "cloud_download",
                    status.zotero_count > 0,
                    lambda: act("get the Zotero updates", sync.pull, status, reload=True),
                    "sync-pull",
                )
                _side(
                    "From SciLEx",
                    status.local_changed,
                    [
                        f"{status.local_unlinked} papers are not in Zotero: push them "
                        "in ⑧ Export, then link again" if status.local_unlinked else "",
                    ],
                    "Push to Zotero",
                    "cloud_upload",
                    status.local_count > 0,
                    lambda: act("push to Zotero", sync.push, status),
                    "sync-push",
                )

        with ui.row().classes("w-full items-center justify-end gap-2"):
            spinner = ui.spinner(size="sm")
            spinner.set_visibility(False)
            ui.button("Check now", icon="refresh", on_click=recheck).props(
                "flat no-caps"
            ).mark("sync-check")
            ui.button("Close", on_click=dialog.close).props("flat no-caps")
        draw()
    dialog.open()


def _side(title, changes, notes, action, icon, enabled, handler, mark) -> None:
    ui.separator()
    ui.label(title).classes("font-bold")
    if not changes and not any(notes):
        ui.label("Nothing new.").classes("text-sm text-gray-500")
    for change in changes[:LISTED]:
        ui.label(f"• {change.title[:70]}: {change.describe()}").classes(
            "text-xs text-gray-700 break-all"
        )
    if len(changes) > LISTED:
        ui.label(f"… and {len(changes) - LISTED} more papers").classes("text-xs")
    for note in notes:
        if note:
            ui.label(note).classes("text-xs text-gray-600")
    button = ui.button(action, icon=icon, on_click=handler).props("no-caps").mark(mark)
    button.set_enabled(enabled)


def _conflicts(status: sync.SyncStatus, review: Review, act) -> None:
    if not status.conflicts:
        return
    ui.label("Changed on both sides").classes("font-bold text-negative")
    ui.label(
        "Choose the value to keep; the others are synced meanwhile."
    ).classes("text-xs text-gray-500")
    for index, conflict in enumerate(status.conflicts):
        with ui.card().classes("w-full p-2 gap-1").mark(f"sync-conflict-{index}"):
            ui.label(f"{conflict.title[:80]} — {conflict.what}").classes("text-sm font-medium")
            ui.label(f"SciLEx: {conflict.local[:200] or '(empty)'}").classes("text-xs")
            ui.label(f"Zotero: {conflict.zotero[:200] or '(empty)'}").classes("text-xs")
            with ui.row().classes("gap-2"):
                ui.button(
                    "Keep SciLEx",
                    on_click=lambda c=conflict: act("keep the SciLEx value", sync.resolve, c, "scilex"),
                ).props("outline dense no-caps").mark(f"sync-keep-scilex-{index}")
                ui.button(
                    "Use Zotero",
                    on_click=lambda c=conflict: act("use the Zotero value", sync.resolve, c, "zotero", reload=True),
                ).props("outline dense no-caps").mark(f"sync-use-zotero-{index}")
