"""Configure screen: edit the review's ``scilex.yml`` through a guided form (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import yaml
from nicegui import ui
from pydantic import BaseModel

from scilex.config_defaults import DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS
from scilex.gui.components.errors import show_error
from scilex.gui.components.vpn_editor import render_vpn_editor
from scilex.gui.services import config_editor as editor
from scilex.gui.services import field_catalog as catalog
from scilex.gui.services.keys_editor import load_keys
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext
from scilex.settings.schema import ScilexSettings, SettingsError

NONE_CHOICE = ""  # select value standing for "no value"
ITEM_TYPE_FIELDS = (
    "filters.item_types",
    "filters.always_keep",
    "ranking.itemtype_weights",
)
KEY_BADGES = {
    "missing": ("Key missing", "negative"),
    "advised": ("Key recommended", "warning"),
}


def _raw_editor(review: Review, expanded: bool) -> None:
    """Expansion with the raw text of ``scilex.yml``, to repair what the form cannot."""
    original = editor.read_text(review)
    with (
        ui.expansion("Edit scilex.yml directly", icon="code", value=expanded)
        .classes("w-full")
        .props("popup")
        .mark("raw-editor")
    ):
        ui.label(
            "Edit the file as text. It is written exactly as typed, comments "
            "included, and only when it is valid. Note: saving with the form "
            "above keeps only the comment block at the top of the file."
        ).classes("text-sm text-gray-500")
        text_area = (
            ui.codemirror(original, language="yaml", line_wrapping=True)
            .classes("w-full")
            .mark("raw-text")
        )
        result = ui.column().classes("gap-0")
        save_file = ui.button("Save file", icon="save").mark("raw-save")
        save_file.set_enabled(False)

        def check() -> None:
            outcome = editor.check_text(text_area.value or "")
            save_file.set_enabled(outcome.valid)
            result.clear()
            with result:
                if outcome.valid:
                    ui.label("No problem found.").classes("text-positive").mark(
                        "raw-valid"
                    )
                for message in outcome.problems:
                    ui.label(message).classes("text-negative text-sm").mark("raw-error")

        def save_text() -> None:
            try:
                editor.write_text(review, text_area.value or "")
            except SettingsError as exc:
                show_error("Cannot save scilex.yml", exc, expected=True)
                return
            except OSError as exc:
                show_error("Cannot save scilex.yml", exc)
                return
            ui.notify(f"Saved {review.config_path.name}", type="positive")
            # Same-route navigation does not re-render a sub page: reload it.
            ui.navigate.reload()

        text_area.on_value_change(lambda _event: save_file.set_enabled(False))
        with ui.row().classes("items-center gap-3"):
            ui.button("Check", icon="rule", on_click=check).props("outline").mark(
                "raw-check"
            )
        save_file.on_click(save_text)


def _unknown_keys_banner(review: Review, unknown: list[tuple[str, str | None]]) -> None:
    """Explain unknown keys and offer to remove them."""
    with ui.card().classes("w-full gap-1 bg-red-50").mark("unknown-keys"):
        ui.label(
            "scilex.yml contains keys that SciLEx does not know. Remove them (or fix "
            "their spelling in the editor at the bottom) to be able to save."
        ).classes("text-negative")
        for dotted, suggestion in unknown:
            hint = f" (did you mean {suggestion}?)" if suggestion else ""
            ui.label(f"{dotted}{hint}").classes("text-sm font-mono")

        def remove() -> None:
            try:
                editor.remove_unknown_keys(review)
            except (SettingsError, OSError) as exc:
                show_error("Cannot remove the unknown keys", exc, expected=True)
                return
            ui.notify("Unknown keys removed", type="positive")
            # Same-route navigation does not re-render a sub page: reload it.
            ui.navigate.reload()

        ui.button("Remove unknown keys", icon="delete", on_click=remove).props(
            "outline color=negative"
        ).mark("remove-unknown")


def _review_changed(ctx: AppContext, review: Review) -> bool:
    """True when the saved file gives a different review (name, output, validity)."""
    fresh = ctx.workspace.get(review.id)
    return fresh is not None and (fresh != review or fresh.error != review.error)


def _load_keys_quietly() -> dict:
    """Keys file content for the key badges; ``{}`` if it cannot be read."""
    try:
        return load_keys()
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Configure screen of ``review``."""
    ui.label("Configure").classes("text-2xl font-bold")
    try:
        data = editor.load_editable(review)
        known_origins = editor.origins(review)
    except (SettingsError, FileNotFoundError) as exc:
        if not review.error:  # otherwise the banner above already says it
            show_error("Cannot read scilex.yml", exc, expected=True)
        ui.label(
            "The form cannot be shown because scilex.yml cannot be read. Fix the "
            "file in the editor below."
        ).classes("text-negative")
        if not review.error:
            ui.label(str(exc)).classes("text-negative whitespace-pre-wrap text-sm")
        _raw_editor(review, expanded=True)
        return
    unknown = editor.check_text(editor.read_text(review)).unknown_keys
    if unknown:
        _unknown_keys_banner(review, unknown)
    keys = _load_keys_quietly()
    preset_at_load = data.get("preset")

    error_labels: dict[str, ui.label] = {}
    unsaved = {"changes": False}
    advanced_items: list[tuple[str, ui.element]] = []

    with ui.row().classes("items-center gap-4 w-full"):
        ui.label(
            "Fill in the essentials, then save. Every other setting has a "
            "sensible default."
        ).classes("text-gray-600")
        show_advanced = ui.switch("Show advanced fields").mark("show-advanced")

    def advanced(dotted: str, element: ui.element) -> None:
        """Hide ``element`` until "Show advanced fields" is on."""
        advanced_items.append((dotted, element))
        element.set_visibility(bool(show_advanced.value))

    def apply_advanced(_event=None) -> None:
        for _, element in advanced_items:
            element.set_visibility(bool(show_advanced.value))

    show_advanced.on_value_change(apply_advanced)

    # -- state access ------------------------------------------------------
    def get(path: tuple[str, ...]) -> Any:
        node: Any = data
        for key in path:
            node = node[key]
        return node

    def put(path: tuple[str, ...], value: Any) -> None:
        node = data
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        unsaved["changes"] = True
        revalidate()

    def error_slot(path: tuple[str, ...]) -> None:
        dotted = ".".join(path)
        label = ui.label().classes("text-negative text-xs").mark(f"error-{dotted}")
        label.set_visibility(False)
        error_labels[dotted] = label

    def help_line(dotted: str) -> None:
        """One grey line under a field: what it does and its default."""
        meta = catalog.field_meta(dotted)
        default = editor.format_default(editor.default_value(dotted, preset_at_load))
        text = meta.help
        if dotted not in ("name", "search.keywords", "search.years", "search.apis"):
            text = f"{text} Default: {default}.".strip()
        if text:
            ui.label(text).classes("text-xs text-gray-500 max-w-2xl").mark(
                f"help-{dotted}"
            )

    def caption(dotted: str) -> None:
        """Label of a field with its origin badge."""
        with ui.row().classes("items-center gap-2"):
            ui.label(catalog.label_of(dotted)).classes("text-sm font-medium")
            origin = editor.origin_of(dotted, known_origins)
            if origin != "default":
                ui.badge("from preset" if origin == "preset" else "from file").props(
                    "outline"
                ).classes("text-xs").mark(f"origin-{dotted}")

    # -- reusable widgets --------------------------------------------------
    def chips_editor(
        values: list,
        on_change: Callable[[list], None],
        marker: str,
        hint: str,
        suggestions: tuple[str, ...] = (),
    ) -> None:
        """Editable list of terms shown as removable chips, with autocompletion."""

        @ui.refreshable
        def chips() -> None:
            with ui.row().classes("items-center gap-1"):
                for index, value in enumerate(values):

                    def remove(event, position=index) -> None:
                        if not event.value:
                            del values[position]
                            on_change(values)
                            chips.refresh()

                    ui.chip(str(value), removable=True, on_value_change=remove).mark(
                        f"chip-{marker}-{index}"
                    )

        chips()

        def add() -> None:
            text = entry.value.strip()
            if text and text not in values:
                values.append(text)
                on_change(values)
                chips.refresh()
            entry.set_value("")

        with ui.row().classes("items-center gap-2"):
            entry = (
                ui.input(placeholder=hint, autocomplete=list(suggestions))
                .props("dense outlined")
                .classes("w-72")
                .mark(f"input-{marker}")
            )
            entry.on("keydown.enter", add)
            ui.button(icon="add", on_click=add).props("flat dense round").mark(
                f"add-{marker}"
            )

    def number_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        def changed(event) -> None:
            value = event.value
            if value is not None and spec.kind == "int" and float(value).is_integer():
                value = int(value)
            put(path, value)

        ui.number(value=get(path), placeholder=meta.example, on_change=changed).props(
            "dense outlined clearable" if spec.nullable else "dense outlined"
        ).classes("w-64").mark(f"field-{'.'.join(path)}")

    def date_input(path: tuple[str, ...], meta) -> None:
        def changed(event) -> None:
            put(path, (event.value or "").strip() or None)

        with (
            ui.input(value=get(path) or "", placeholder=meta.example, on_change=changed)
            .props("dense outlined clearable")
            .classes("w-64")
            .mark(f"field-{'.'.join(path)}") as field
        ):
            with ui.menu().props("no-parent-event") as menu:
                ui.date(mask="YYYY-MM-DD").bind_value(field).on_value_change(menu.close)
            with field.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer"
                )

    def text_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        dotted = ".".join(path)
        if dotted == "search.since":
            date_input(path, meta)
            return

        def changed(event) -> None:
            value = event.value
            put(path, (value or None) if spec.nullable else (value or ""))

        if dotted == "llm_screening.topic":
            ui.textarea(
                value=get(path) or "", placeholder=meta.example, on_change=changed
            ).props("dense outlined autogrow rows=3").classes("w-full max-w-2xl").mark(
                f"field-{dotted}"
            )
            return
        ui.input(
            value=get(path) or "",
            placeholder=meta.example,
            autocomplete=list(meta.suggestions) or None,
            on_change=changed,
        ).props("dense outlined").classes("w-96").mark(f"field-{dotted}")

    def choice_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        names = dict(meta.option_labels)
        options = {option: names.get(option, option) for option in spec.options}
        if spec.nullable:
            options = {NONE_CHOICE: "(none)", **options}
        current = get(path)

        def changed(event) -> None:
            put(path, None if event.value == NONE_CHOICE else event.value)

        ui.select(
            options,
            value=NONE_CHOICE if current is None else current,
            on_change=changed,
        ).props("dense outlined").classes("w-64").mark(f"field-{'.'.join(path)}")

    def multichoice_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        names = dict(meta.option_labels)
        ui.select(
            {option: names.get(option, option) for option in spec.options},
            value=list(get(path) or []),
            multiple=True,
            on_change=lambda event: put(path, list(event.value)),
        ).props("dense outlined use-chips").classes("w-96").mark(
            f"field-{'.'.join(path)}"
        )

    def item_types_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        """Multi-select of document types, readable names, current values kept."""
        dotted = ".".join(path)
        names = dict(meta.option_labels)
        if dotted == "ranking.itemtype_weights":
            weights = {**DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS, **(get(path) or {})}
            current = [name for name, kept in weights.items() if kept]
        else:
            current = list(get(path) or [])
        options = {value: names.get(value, value) for value in meta.suggestions}
        options.update({value: value for value in current if value not in options})

        def changed(event) -> None:
            selected = list(event.value or [])
            if dotted == "ranking.itemtype_weights":
                # Write only what differs from the defaults (unlisted = no points).
                put(
                    path,
                    {
                        name: name in selected
                        for name in {*DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS, *selected}
                        if (name in selected)
                        != DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS.get(name, False)
                    },
                )
            else:
                put(path, (selected or None) if spec.nullable else selected)

        select = (
            ui.select(
                options,
                value=current,
                multiple=True,
                with_input=True,
                on_change=changed,
            )
            .props("dense outlined use-chips")
            .classes("w-96")
            .mark(f"field-{dotted}")
        )
        if meta.example and not current:
            # A value, not a props string: quotes or backslashes would break parsing.
            select.props["placeholder"] = meta.example

    def intlist_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        def changed(event) -> None:
            parts = [
                part.strip() for part in (event.value or "").split(",") if part.strip()
            ]
            try:
                put(path, [int(part) for part in parts])
            except ValueError:
                put(path, parts)  # shown as a validation error

        ui.input(
            value=", ".join(str(v) for v in get(path) or []),
            placeholder=meta.example,
            on_change=changed,
        ).props("dense outlined").classes("w-64").mark(f"field-{'.'.join(path)}")

    def strlist_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        values = list(get(path) or [])

        def changed(items: list) -> None:
            put(path, (list(items) or None) if spec.nullable else list(items))

        chips_editor(
            values,
            changed,
            ".".join(path),
            meta.example or "Type a value, press Enter",
            meta.suggestions,
        )

    def floatmap_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        dotted = ".".join(path)
        shares = ui.label().classes("text-xs text-gray-600").mark(f"shares-{dotted}")

        def show_shares() -> None:
            values = {k: v or 0 for k, v in get(path).items()}
            total = sum(values.values())
            if total <= 0:
                shares.set_text("All weights are 0: every paper gets the same score.")
                return
            shares.set_text(
                "Share of the score: "
                + ", ".join(
                    f"{catalog.WEIGHT_LABELS.get(k, k)} {v / total:.0%}"
                    for k, v in values.items()
                )
            )

        def changed(key: str, value: Any) -> None:
            put((*path, key), value)
            show_shares()

        with ui.row().classes("gap-3"):
            for key in list(get(path)):
                ui.number(
                    catalog.WEIGHT_LABELS.get(key, key),
                    value=get(path)[key],
                    min=0,
                    step=0.05,
                    on_change=lambda event, key=key: changed(key, event.value),
                ).props("dense outlined").classes("w-44").mark(f"field-{dotted}.{key}")
        show_shares()

    def yaml_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        current = get(path)
        text = "" if current in (None, {}) else yaml.safe_dump(current).strip()

        def changed(event) -> None:
            raw = (event.value or "").strip()
            if not raw:
                put(path, None if spec.nullable else {})
                return
            try:
                put(path, yaml.safe_load(raw))
            except yaml.YAMLError:
                put(path, raw)  # reported as "not a valid mapping"

        ui.textarea(value=text, placeholder=meta.example, on_change=changed).props(
            "dense outlined"
        ).classes("w-96").mark(f"field-{'.'.join(path)}")

    def bool_input(path: tuple[str, ...], spec: editor.FieldSpec, meta) -> None:
        ui.switch(
            meta.label,
            value=bool(get(path)),
            on_change=lambda event: put(path, event.value),
        ).mark(f"field-{'.'.join(path)}")

    builders = {
        "bool": bool_input,
        "int": number_input,
        "float": number_input,
        "str": text_input,
        "choice": choice_input,
        "multichoice": multichoice_input,
        "intlist": intlist_input,
        "strlist": strlist_input,
        "floatmap": floatmap_input,
        "yaml": yaml_input,
    }

    def vpn_field(path: tuple[str, ...]) -> None:
        dotted = ".".join(path)
        with ui.column().classes("gap-0 w-full"):
            caption(dotted)
            render_vpn_editor(
                get(path), lambda value: put(path, value), editor.API_NAMES
            )
            error_slot(path)

    def generic_field(path: tuple[str, ...], annotation: Any) -> None:
        dotted = ".".join(path)
        if dotted == "collect.vpn":
            vpn_field(path)
            return
        spec = editor.describe_field(annotation)
        meta = catalog.field_meta(dotted)
        builder = (
            item_types_input if dotted in ITEM_TYPE_FIELDS else builders[spec.kind]
        )
        with ui.column().classes("gap-0") as column:
            if spec.kind != "bool":
                caption(dotted)
            builder(path, spec, meta)
            help_line(dotted)
            error_slot(path)
        if meta.advanced:
            advanced(dotted, column)

    def model_fields(model: type[BaseModel], prefix: tuple[str, ...]) -> None:
        for name, field in model.model_fields.items():
            path = (*prefix, name)
            core, _ = editor._unwrap(field.annotation)
            if isinstance(core, type) and issubclass(core, BaseModel):
                section = catalog.SECTIONS.get(name)
                ui.label(section.label if section else name).classes("font-bold mt-2")
                if section:
                    ui.label(section.help).classes("text-xs text-gray-500")
                with ui.column().classes("pl-4 gap-2 border-l-2"):
                    model_fields(core, path)
            else:
                generic_field(path, field.annotation)

    # -- Essentials --------------------------------------------------------------
    with ui.card().classes("w-full gap-3").mark("section-search"):
        ui.label("Essentials").classes("text-xl font-bold")

        caption("name")
        ui.input(
            value=data["name"],
            placeholder=catalog.FIELDS["name"].example,
            on_change=lambda event: put(("name",), event.value),
        ).props("dense outlined").classes("w-96").mark("config-name")
        help_line("name")
        error_slot(("name",))

        # Preset, shown as readable choices with their effect.
        caption("preset")

        def preset_changed(event) -> None:
            value = event.value or NONE_CHOICE
            preset_help.set_text(catalog.PRESETS_INFO[value].help)
            put(("preset",), None if value == NONE_CHOICE else value)

        current_preset = data.get("preset") or NONE_CHOICE
        ui.radio(
            {value: info.label for value, info in catalog.PRESETS_INFO.items()},
            value=current_preset,
            on_change=preset_changed,
        ).props("inline").mark("field-preset")
        preset_help = ui.label().classes("text-xs text-gray-500 max-w-2xl")
        preset_help.set_text(
            catalog.PRESETS_INFO.get(current_preset, catalog.PRESETS_INFO[""]).help
        )
        ui.label(catalog.FIELDS["preset"].help).classes("text-xs text-gray-500")
        error_slot(("preset",))

        # Keyword groups
        caption("search.keywords")
        help_line("search.keywords")
        rule_label = ui.label().classes("text-sm text-gray-600").mark("keyword-rule")
        suggestions = catalog.template_keywords()

        @ui.refreshable
        def keyword_groups() -> None:
            groups = get(("search", "keywords"))
            rule_label.set_text(
                "A paper is kept if it contains at least one term of group 1 AND "
                "at least one term of group 2. Example: group 1 = metabolomics, "
                "lipidomics; group 2 = knowledge graph, ontology."
                if len(groups) > 1
                else "A paper is kept if it contains at least one of these terms. "
                "Add a second group to require two topics at once."
            )
            for index in range(len(groups)):
                if index:
                    ui.label("AND").classes("font-bold text-primary")
                with (
                    ui.card()
                    .props("flat bordered")
                    .classes("w-full")
                    .mark(f"keyword-group-{index}")
                ):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(
                            f"Group {index + 1}: "
                            + ("main topic" if index == 0 else "second topic")
                            + " — any of these terms (synonyms)"
                        ).classes("text-sm font-medium")
                        if len(groups) > 1:
                            ui.button(
                                "Remove group",
                                icon="delete",
                                on_click=lambda position=index: remove_group(position),
                            ).props("flat dense color=negative").mark(
                                f"remove-group-{index}"
                            )
                    chips_editor(
                        groups[index],
                        lambda _items: put(("search", "keywords"), groups),
                        f"keyword-{index}",
                        "Type a term, press Enter",
                        suggestions,
                    )
            if len(groups) < editor.MAX_KEYWORD_GROUPS:
                ui.button(
                    "Add a second group (AND)", icon="add", on_click=lambda: add_group()
                ).props("outline dense").mark("add-group")

        def add_group() -> None:
            get(("search", "keywords")).append([])
            put(("search", "keywords"), get(("search", "keywords")))
            keyword_groups.refresh()

        def remove_group(position: int) -> None:
            del get(("search", "keywords"))[position]
            put(("search", "keywords"), get(("search", "keywords")))
            keyword_groups.refresh()

        keyword_groups()
        error_slot(("search", "keywords"))

        # Years
        caption("search.years")
        years = get(("search", "years"))
        as_range = editor.years_as_range(years)
        # Follow the shape written in the file (list vs "YYYY-YYYY"), so a raw
        # edit does not flip the toggle.
        shape = editor.years_shape(review)
        if shape is None:
            shape = "range" if as_range or not years else "list"
        today_year = date.today().year
        start_end = list(as_range or (today_year - 2, today_year))

        def update_range() -> None:
            first, last = start_end
            if first is None or last is None:
                put(("search", "years"), [])
            elif first <= last:
                put(("search", "years"), list(range(int(first), int(last) + 1)))
            else:
                # Invalid on purpose: the validator reports "From is after To".
                put(("search", "years"), f"{int(first)}-{int(last)}")

        def update_list(event) -> None:
            parts = [p.strip() for p in (event.value or "").split(",") if p.strip()]
            try:
                put(("search", "years"), [int(p) for p in parts])
            except ValueError:
                put(("search", "years"), parts)

        mode_toggle = ui.toggle(
            {"range": "Range", "list": "Specific years"}, value=shape
        ).mark("years-mode")
        with ui.row().classes("items-center gap-3") as range_row:
            ui.number(
                "From",
                value=start_end[0],
                precision=0,
                on_change=lambda e: (start_end.__setitem__(0, e.value), update_range()),
            ).props("dense outlined").classes("w-32").mark("years-start")
            ui.number(
                "To",
                value=start_end[1],
                precision=0,
                on_change=lambda e: (start_end.__setitem__(1, e.value), update_range()),
            ).props("dense outlined").classes("w-32").mark("years-end")
        list_input = (
            ui.input(
                "Years (comma separated)",
                value=", ".join(str(y) for y in years)
                if isinstance(years, list)
                else "",
                placeholder="2019, 2022, 2025",
                on_change=update_list,
            )
            .props("dense outlined")
            .classes("w-96")
            .mark("years-list")
        )

        def switch_mode(event=None) -> None:
            is_range = mode_toggle.value == "range"
            range_row.set_visibility(is_range)
            list_input.set_visibility(not is_range)
            if is_range:
                update_range()
            else:
                update_list(type("E", (), {"value": list_input.value})())

        mode_toggle.on_value_change(switch_mode)
        range_row.set_visibility(shape == "range")
        list_input.set_visibility(shape == "list")
        help_line("search.years")
        error_slot(("search", "years"))

        # Sources
        caption("search.apis")
        help_line("search.apis")
        selected_apis = set(get(("search", "apis")))

        def toggle_api(name: str, checked: bool) -> None:
            (selected_apis.add if checked else selected_apis.discard)(name)
            put(
                ("search", "apis"),
                [api for api in editor.API_NAMES if api in selected_apis],
            )

        with ui.grid(columns="repeat(auto-fill, minmax(17rem, 1fr))").classes(
            "w-full gap-2"
        ):
            for api_name in editor.API_NAMES:
                info = catalog.API_INFO.get(api_name, catalog.ApiInfo(api_name, ""))
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.checkbox(
                            info.label,
                            value=api_name in selected_apis,
                            on_change=lambda event, api_name=api_name: toggle_api(
                                api_name, event.value
                            ),
                        ).mark(f"api-{api_name}")
                        badge = KEY_BADGES.get(editor.key_status(api_name, keys))
                        if badge:
                            ui.badge(badge[0], color=badge[1]).props("outline").classes(
                                "text-xs"
                            ).mark(f"api-key-{api_name}")
                    ui.label(info.coverage).classes("text-xs text-gray-500 pl-10")
        ui.button(
            "Manage API keys",
            icon="key",
            on_click=lambda: ui.navigate.to(f"/review/{review.id}/keys"),
        ).props("flat dense").mark("go-keys")
        error_slot(("search", "apis"))

        query_estimate = (
            ui.label().classes("text-sm font-medium").mark("query-estimate")
        )

        # Other search fields
        for name in (
            "max_articles_per_query",
            "bonus_keywords",
            "semantic_scholar_mode",
            "since",
        ):
            generic_field(
                ("search", name),
                ScilexSettings.model_fields["search"]
                .annotation.model_fields[name]
                .annotation,
            )

    # -- Filters and more options ----------------------------------------------
    for section_name, section_model in editor.sections():
        section = catalog.SECTIONS.get(section_name)
        if section_name == "citations":
            ui.label("More options").classes("text-lg font-bold mt-4")
        with (
            ui.expansion(
                section.label if section else section_name,
                caption=section.help if section else None,
            )
            .classes("w-full")
            .props("popup")
            .mark(f"section-{section_name}")
        ):
            model_fields(section_model, (section_name,))
            error_slot((section_name,))

    with (
        ui.expansion("Output folder", icon="folder")
        .classes("w-full")
        .props("popup")
        .mark("section-general") as general
    ):
        generic_field(("output_dir",), str)
    advanced("output_dir", general)

    # -- Warnings, validation summary and actions --------------------------------
    with ui.card().classes("w-full gap-1"):

        @ui.refreshable
        def summary(
            problems: list[tuple[str, str]], warnings: list[tuple[str, str]]
        ) -> None:
            if not problems:
                ui.label("No problem found.").classes("text-positive").mark(
                    "config-valid"
                )
            for path, message in problems:
                ui.label(editor.readable_problem(path, message)).classes(
                    "text-negative text-sm"
                ).mark("config-error")
            for _path, message in warnings:
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.icon("warning", size="xs").classes("text-warning")
                    ui.label(message).classes("text-sm").mark("config-warning")

        summary([], [])

        with ui.row().classes("items-center gap-3"):
            save_button = ui.button("Save", icon="save").mark("config-save")
            ui.button(
                "Save and go to ② Collect",
                icon="arrow_forward",
                on_click=lambda: save_and_collect(),
            ).props("outline").mark("config-next")
            unsaved_label = (
                ui.label("Unsaved changes")
                .classes("text-warning text-sm")
                .mark("config-unsaved")
            )

    shown: list[tuple] = [([], [])]  # drawn by summary([], [])

    def show_estimate() -> None:
        count = editor.estimate_queries(data)
        if not count:
            query_estimate.set_text(
                "Add keywords, years and sources to see how many queries will run."
            )
            return
        search = data["search"]
        query_estimate.set_text(
            f"≈ {count} queries ({count // (len(search['years']) * len(search['apis']))}"
            f" keyword combinations × {len(search['years'])} years × "
            f"{len(search['apis'])} sources)."
        )

    def revalidate() -> None:
        # Validation is cheap (~10 µs); redrawing the summary on every
        # keystroke is not, so it is only redrawn when the messages change.
        problems = editor.validate(data)
        warnings = editor.dependency_warnings(data, keys)
        save_button.set_enabled(not problems)
        unsaved_label.set_visibility(unsaved["changes"])
        show_estimate()
        if (problems, warnings) != shown[0]:
            shown[0] = (problems, warnings)
            summary.refresh(problems, warnings)
        for dotted, label in error_labels.items():
            messages = [
                message
                for path, message in problems
                if path == dotted or path.startswith(f"{dotted}.")
            ]
            label.set_text("; ".join(messages))
            label.set_visibility(bool(messages))
        # An error in a hidden field must be visible: show the advanced fields.
        if not show_advanced.value and any(
            path == dotted or path.startswith(f"{dotted}.")
            for path, _ in problems
            for dotted, _ in advanced_items
        ):
            show_advanced.set_value(True)

    def save() -> bool:
        try:
            editor.save(review, data)
        except SettingsError as exc:
            show_error("Cannot save scilex.yml", exc, expected=True)
            return False
        except OSError as exc:
            show_error("Cannot save scilex.yml", exc)
            return False
        unsaved["changes"] = False
        unsaved_label.set_visibility(False)
        ui.notify(f"Saved {review.config_path.name}", type="positive")
        if _review_changed(ctx, review):
            # Name, output folder or validity changed: the sidebar, the
            # results path and the locked steps were drawn from the old one.
            ui.navigate.reload()
        return True

    def save_and_collect() -> None:
        # Collect reads scilex.yml from disk: unsaved edits would be ignored.
        if unsaved["changes"] and not save():
            return
        ui.navigate.to(f"/review/{review.id}/collect")

    save_button.on_click(save)
    revalidate()
    _raw_editor(review, expanded=bool(unknown))
