"""API keys screens.

- Global keys (``/keys``, reached from the home page): one file shared by all
  reviews, the default of every review.
- A review's keys (its "API keys" step): the same form, where a filled field
  overrides the global value for this review only (``review_keys.yml`` in the
  review folder); an empty field uses the global value.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from nicegui import run, ui

from scilex.gui.components.branding import render_logo
from scilex.gui.components.errors import show_error
from scilex.gui.services import keys_editor as editor
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext


def _show_result(label: ui.label, ok: bool, message: str) -> None:
    label.set_text(("✓ " if ok else "✗ ") + message)
    label.classes(replace="text-sm " + ("text-positive" if ok else "text-negative"))


def _masked(value) -> str:
    """Show the end of a secret only."""
    text = str(value or "")
    return f"…{text[-4:]}" if len(text) > 4 else "set"


def _global_hint(inherited: dict | None, block: str, field: str, secret: bool) -> str:
    """Hint under a review field: the global value it falls back to."""
    if inherited is None:
        return ""
    value = (inherited.get(block) or {}).get(field)
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = next(iter(value.values()), None)
    if value in (None, ""):
        return "Empty: no global value either."
    shown = _masked(value) if secret else str(value)
    return f"Empty: uses the global value ({shown})."


class _KeyRows:
    """The editable list of keys of one API (password inputs, add/remove)."""

    def __init__(self, api: str, initial: list[str], hint: str = ""):
        self.api = api
        self.hint = hint
        self.inputs: list[ui.input] = []
        self.container = ui.column().classes("w-full gap-1")
        for key in initial or [""]:
            self.add(key)

    def add(self, value: str = "") -> None:
        first = not self.inputs
        with self.container, ui.row().classes("w-full items-center no-wrap") as row:
            field = ui.input(
                "Key" if first else "Additional key",
                value=value,
                password=True,
                password_toggle_button=True,
            ).classes("grow")
            if first and self.hint:
                field.props["hint"] = self.hint
            field.mark(
                f"key-{self.api}" if first else f"key-{self.api}-{len(self.inputs)}"
            )
            ui.button(icon="delete", on_click=lambda: self._remove(field, row)).props(
                "flat round dense"
            )
        self.inputs.append(field)

    def _remove(self, field: ui.input, row: ui.row) -> None:
        if len(self.inputs) == 1:
            field.set_value("")
            return
        self.inputs.remove(field)
        self.container.remove(row)

    def values(self) -> list[str]:
        return [field.value or "" for field in self.inputs]


def _keys_form(
    data: dict,
    save_data: Callable[[dict], Path | None],
    inherited: dict | None = None,
    load_error: Exception | None = None,
) -> None:
    """Draw the keys form for ``data``; ``inherited`` (review scope) are the global keys."""
    overrides = editor.env_overrides()
    rows: dict[str, _KeyRows] = {}

    async def test_api(spec: editor.ApiSpec, result: ui.label) -> None:
        keys = [key for key in rows[spec.name].values() if key.strip()]
        if not keys and inherited is not None:
            keys = editor.get_keys_list(inherited.get(spec.name), spec.field)
        if not keys:
            _show_result(result, False, "Enter a key first.")
            return
        result.set_text("Testing…")
        outcomes = [await run.io_bound(editor.check_key, spec.name, k) for k in keys]
        accepted = sum(ok for ok, _ in outcomes)
        message = (
            outcomes[0][1]
            if len(outcomes) == 1
            else f"{accepted}/{len(outcomes)} keys accepted."
        )
        _show_result(result, accepted == len(outcomes), message)

    for spec in editor.API_SPECS:
        env_name = overrides.get(f"{spec.name}.{spec.field}")
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.label(spec.label).classes("text-lg font-bold")
                ui.badge("required" if spec.required else "optional").props(
                    "color=negative" if spec.required else "color=grey"
                )
                ui.link("Get a key", spec.help_url, new_tab=True).classes("text-sm")
            ui.label(spec.note).classes("text-gray-500 text-sm")
            if env_name:
                ui.label(
                    f"Overridden by the environment variable {env_name}: the "
                    "value saved here is ignored while it is set."
                ).classes("text-warning text-sm").mark(f"env-{spec.name}")
            key_rows = rows[spec.name] = _KeyRows(
                spec.name,
                editor.get_keys_list(data.get(spec.name), spec.field),
                _global_hint(inherited, spec.name, spec.field, secret=True),
            )
            with ui.row().classes("items-center gap-2"):
                ui.button("Add another key", icon="add", on_click=key_rows.add).props(
                    "flat dense"
                )
                if spec.testable:
                    result = ui.label("").classes("text-sm")
                    ui.button(
                        "Test",
                        icon="network_check",
                        on_click=lambda _=None, s=spec, r=result: test_api(s, r),
                    ).props("outline dense").mark(f"key-test-{spec.name}")

    zotero = data.get("Zotero") or {}
    inherited_zotero = (inherited or {}).get("Zotero") or {}
    with ui.card().classes("w-full").mark("keys-zotero"):
        with ui.row().classes("items-center gap-2"):
            ui.label("Zotero").classes("text-lg font-bold")
            ui.badge("optional").props("color=grey")
            ui.link("Get a key", editor.ZOTERO_HELP_URL, new_tab=True).classes(
                "text-sm"
            )
        ui.label(
            "Needed to push results to Zotero, to start a review from a Zotero "
            "collection, and to annotate in Zotero."
        ).classes("text-gray-500 text-sm")
        zotero_key = (
            ui.input(
                "API key",
                value=str(zotero.get("api_key") or ""),
                password=True,
                password_toggle_button=True,
            )
            .classes("w-full")
            .mark("key-Zotero")
        )
        zotero_id = (
            ui.input("Library id", value=str(zotero.get("user_id") or ""))
            .classes("w-full")
            .mark("zotero-user-id")
        )
        for widget, field, secret in (
            (zotero_key, "api_key", True),
            (zotero_id, "user_id", False),
        ):
            hint = _global_hint(inherited, "Zotero", field, secret)
            if hint:
                widget.props["hint"] = hint
        mode_choices = {"user": "user", "group": "group"}
        if inherited is not None:
            mode_choices = {
                "": f"Global ({inherited_zotero.get('user_mode') or 'user'})",
                **mode_choices,
            }
        zotero_mode = ui.select(
            mode_choices,
            label="Library type",
            value=zotero.get("user_mode") or ("" if inherited is not None else "user"),
        ).mark("zotero-user-mode")
        zotero_result = ui.label("").classes("text-sm")

        async def test_zotero() -> None:
            outcome = await run.io_bound(
                editor.check_zotero,
                zotero_key.value or inherited_zotero.get("api_key") or "",
                zotero_id.value or str(inherited_zotero.get("user_id") or ""),
                zotero_mode.value or inherited_zotero.get("user_mode") or "user",
            )
            _show_result(zotero_result, *outcome)

        ui.button("Test", icon="network_check", on_click=test_zotero).props(
            "outline dense"
        ).mark("key-test-Zotero")

    email_inputs: dict[str, ui.input] = {}
    with ui.card().classes("w-full"):
        ui.label("Contact e-mail").classes("text-lg font-bold")
        for block_name, (field_name, note) in editor.EMAIL_BLOCKS.items():
            email_inputs[block_name] = (
                ui.input(
                    f"{block_name} ({note})",
                    value=str((data.get(block_name) or {}).get(field_name) or ""),
                )
                .classes("w-full")
                .mark(f"key-{block_name}")
            )
            hint = _global_hint(inherited, block_name, field_name, secret=False)
            if hint:
                email_inputs[block_name].props["hint"] = hint

    with ui.expansion("Advanced: rate limits", icon="tune").classes("w-full"):
        ui.label(
            "Requests per second, per API. Leave empty to keep the defaults"
            + (" (or the global values)." if inherited is not None else ".")
        ).classes("text-gray-500 text-sm")
        limit_inputs = {
            name: ui.number(name, value=value, min=0.01)
            for name, value in sorted((data.get("rate_limits") or {}).items())
        }
        new_api = ui.input("Add an API name (e.g. SemanticScholar)")
        new_value = ui.number("Requests per second", min=0.01)

    def collect_edits() -> dict:
        updated = dict(data)
        for spec in editor.API_SPECS:
            editor.set_keys_list(
                updated, spec.name, rows[spec.name].values(), spec.field
            )
        zotero_block = dict(updated.get("Zotero") or {})
        for field_name, widget in (("api_key", zotero_key), ("user_id", zotero_id)):
            text = (widget.value or "").strip()
            if text:
                zotero_block[field_name] = text
            else:
                zotero_block.pop(field_name, None)
        if zotero_mode.value:
            zotero_block["user_mode"] = zotero_mode.value
        else:
            zotero_block.pop("user_mode", None)
        if inherited is None and not ({"api_key", "user_id"} & set(zotero_block)):
            zotero_block = {}  # globally, a library type alone means nothing
        if zotero_block:
            updated["Zotero"] = zotero_block
        else:
            updated.pop("Zotero", None)
        for block_name, (field_name, _) in editor.EMAIL_BLOCKS.items():
            editor.set_keys_list(
                updated, block_name, [email_inputs[block_name].value or ""], field_name
            )
        limits = {n: w.value for n, w in limit_inputs.items() if w.value}
        if (new_api.value or "").strip() and new_value.value:
            limits[new_api.value.strip()] = new_value.value
        if limits:
            updated["rate_limits"] = limits
        else:
            updated.pop("rate_limits", None)
        return updated

    def save() -> None:
        try:
            updated = collect_edits()
            path = save_data(updated)
        except ValueError as exc:
            show_error("Invalid keys", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot save the keys", exc)
            return
        data.clear()
        data.update(updated)
        if path is None:
            ui.notify("This review now uses the global keys only", type="positive")
        else:
            ui.notify(f"Keys saved to {path}", type="positive")

    save_button = ui.button("Save", icon="save", on_click=save).mark("keys-save")
    if load_error is not None:
        # Saving would replace the unreadable file with a near-empty one.
        save_button.disable()


def _legacy_import_card(data: dict) -> None:
    """Offer the keys of the legacy api.config.yml the global file lacks."""
    missing = editor.legacy_blocks_to_import(data)
    if not missing:
        return
    legacy = editor.legacy_keys_path()
    with ui.card().classes("w-full bg-blue-50").mark("keys-legacy-import"):
        ui.label("Keys found in your previous configuration").classes("font-bold")
        ui.label(
            f"{legacy} holds keys the app does not use yet: "
            f"{', '.join(sorted(missing))}. Import them into the global keys? "
            "Values already set here are not changed."
        ).classes("text-sm")

        def import_them() -> None:
            try:
                path = editor.save_keys(editor.merge_keys(missing, data))
            except ValueError as exc:
                show_error("Cannot import these keys", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot import these keys", exc)
                return
            ui.notify(f"Keys imported into {path}", type="positive")
            ui.navigate.reload()

        ui.button("Import", icon="download", on_click=import_them).mark(
            "keys-legacy-import-button"
        )


def render_global(ctx: AppContext) -> None:
    """Draw the global keys screen (``/keys``)."""
    ui.page_title("API keys · SciLEx")
    try:
        data = editor.load_keys()
        load_error = None
    except Exception as exc:
        data, load_error = {}, exc
    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-3"):
        with ui.row().classes("w-full items-center"):
            render_logo("w-36 cursor-pointer").on("click", lambda: ui.navigate.to("/"))
            ui.space()
            ui.button(
                "My reviews", icon="folder_open", on_click=lambda: ui.navigate.to("/")
            ).props("flat").mark("keys-back")
        ui.label("API keys").classes("text-2xl font-bold")
        ui.label(
            "Global keys: the default of every review. A review can override any "
            "of them in its own API keys step."
        ).classes("text-gray-500")
        ui.label(f"File: {editor.keys_path()}").classes("text-sm font-mono")
        if load_error is not None:
            ui.label(f"The keys file could not be read: {load_error}").classes(
                "text-negative"
            )
        else:
            _legacy_import_card(data)
        _keys_form(data, editor.save_keys, load_error=load_error)


def render(ctx: AppContext, review: Review) -> None:
    """Draw a review's API keys step: global defaults plus its own overrides."""
    try:
        inherited = editor.load_keys()
        data = editor.load_keys(editor.review_keys_path(review.folder))
        load_error = None
    except Exception as exc:
        inherited, data, load_error = {}, {}, exc

    ui.label("API keys").classes("text-2xl font-bold")
    with ui.row().classes("items-center gap-2"):
        ui.label(
            "This review uses the global keys. Fill a field below only to use a "
            "different value for this review; leave it empty to keep the global one."
        ).classes("text-gray-600")
        ui.button(
            "Edit global keys", icon="key", on_click=lambda: ui.navigate.to("/keys")
        ).props("flat dense no-caps").mark("keys-edit-global")
    overrides_path = editor.review_keys_path(review.folder)
    ui.label(
        f"Overrides: {overrides_path}"
        + ("" if overrides_path.is_file() else " (none yet)")
    ).classes("text-sm font-mono")
    if load_error is not None:
        ui.label(f"A keys file could not be read: {load_error}").classes(
            "text-negative"
        )
    _keys_form(
        data,
        lambda updated: editor.save_review_keys(review.folder, updated),
        inherited=inherited,
        load_error=load_error,
    )
