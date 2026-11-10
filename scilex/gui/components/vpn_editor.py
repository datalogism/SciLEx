"""Editor of the ``collect.vpn`` block: NordVPN rotation when a source blocks the IP.

The block stays a plain mapping in ``scilex.yml`` (the CLI reads the same keys);
keys this editor does not know (``provider``...) are kept as they are.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from nicegui import run, ui

from scilex.vpn.rotator import VPNRotator, rotate_once, vpn_status

# How the next server is picked, stored through the ``countries`` key.
COUNTRY_ALL = "all"  # key absent: a random country among every NordVPN country
COUNTRY_QUICK = "quick"  # empty list: NordVPN quick-connect (fastest server)
COUNTRY_LIST = "list"  # explicit list: a random country among these
COUNTRY_MODES = {
    COUNTRY_ALL: "Random country (all NordVPN countries)",
    COUNTRY_QUICK: "Quick connect (fastest server)",
    COUNTRY_LIST: "Random country among a list",
}
DEFAULT_DELAY = 15
DEFAULT_MAX_ROTATIONS = 10


def country_mode(block: dict) -> str:
    """Return how ``block`` picks the next server (one of ``COUNTRY_MODES``)."""
    if "countries" not in block or block["countries"] is None:
        return COUNTRY_ALL
    return COUNTRY_LIST if block["countries"] else COUNTRY_QUICK


def with_country_mode(block: dict, mode: str, countries: Sequence[str]) -> dict:
    """Return a copy of ``block`` whose ``countries`` key matches ``mode``."""
    updated = dict(block)
    if mode == COUNTRY_ALL:
        updated.pop("countries", None)
    elif mode == COUNTRY_QUICK:
        updated["countries"] = []
    else:
        updated["countries"] = list(countries)
    return updated


def normalized(block: dict) -> dict | None:
    """Return what to store: None when rotation is off and nothing else is set."""
    if not block.get("enabled") and set(block) <= {"enabled", "provider"}:
        return None
    return block


def render_vpn_editor(
    current: dict | None,
    on_change: Callable[[dict | None], None],
    api_names: Sequence[str],
) -> None:
    """Draw the VPN controls; ``on_change`` receives the new block (None = off)."""
    block: dict[str, Any] = dict(current or {})
    block.setdefault("provider", "nordvpn")

    def emit() -> None:
        on_change(normalized(dict(block)))
        options.set_visibility(bool(block.get("enabled")))

    def set_key(key: str, value: Any) -> None:
        if value in (None, "", []) and key != "countries":
            block.pop(key, None)
        else:
            block[key] = value
        emit()

    with ui.column().classes("gap-2 w-full").mark("vpn-editor"):
        ui.switch(
            "Rotate the NordVPN server when a source blocks this IP",
            value=bool(block.get("enabled")),
            on_change=lambda event: set_key("enabled", bool(event.value)),
        ).mark("vpn-enabled")
        ui.label(
            "Needs the NordVPN app installed and logged in (Windows, WSL2) or the "
            "nordvpn command (Linux). After all retries of a query fail with "
            "429/409, SciLEx switches server, checks that the IP changed and "
            "retries the same page."
        ).classes("text-xs text-gray-500 max-w-2xl")

        with ui.column().classes("gap-2 pl-2 w-full") as options:
            ui.select(
                list(api_names),
                multiple=True,
                value=list(block.get("rotate_on_rate_limit") or []),
                label="Only for these sources (empty: all sources)",
                on_change=lambda event: set_key(
                    "rotate_on_rate_limit", list(event.value or [])
                ),
            ).props("use-chips dense outlined").classes("w-full max-w-2xl").mark(
                "vpn-apis"
            )

            countries_select = None

            def mode_changed(event) -> None:
                chosen = list(countries_select.value or []) if countries_select else []
                new_block = with_country_mode(block, event.value, chosen)
                block.clear()
                block.update(new_block)
                countries_select.set_visibility(event.value == COUNTRY_LIST)
                emit()

            mode = country_mode(block)
            ui.select(
                COUNTRY_MODES, value=mode, label="Next server", on_change=mode_changed
            ).props("dense outlined").classes("w-96").mark("vpn-country-mode")
            countries_select = (
                ui.select(
                    VPNRotator.ALL_COUNTRIES,
                    multiple=True,
                    value=list(block.get("countries") or []),
                    label="Countries",
                    with_input=True,
                    on_change=lambda event: set_key(
                        "countries", list(event.value or [])
                    ),
                )
                .props("use-chips dense outlined")
                .classes("w-full max-w-2xl")
                .mark("vpn-countries")
            )
            countries_select.set_visibility(mode == COUNTRY_LIST)

            with ui.row().classes("gap-3"):
                ui.number(
                    "Wait after connecting (s)",
                    value=block.get("rotation_delay", DEFAULT_DELAY),
                    min=0,
                    max=300,
                    step=1,
                    on_change=lambda event: set_key(
                        "rotation_delay",
                        None if event.value is None else int(event.value),
                    ),
                ).props("dense outlined").classes("w-56").mark("vpn-delay")
                ui.number(
                    "Max rotations per run",
                    value=block.get("max_rotations_per_session", DEFAULT_MAX_ROTATIONS),
                    min=1,
                    max=1000,
                    step=1,
                    on_change=lambda event: set_key(
                        "max_rotations_per_session",
                        None if event.value is None else int(event.value),
                    ),
                ).props("dense outlined").classes("w-56").mark("vpn-max")

        _render_checks(lambda: dict(block))
    options.set_visibility(bool(block.get("enabled")))


def _render_checks(current_block: Callable[[], dict]) -> None:
    """Buttons to check the NordVPN client and to try one rotation."""
    result = ui.label().classes("text-sm whitespace-pre-wrap").mark("vpn-check-result")
    result.set_visibility(False)

    def show(text: str, ok: bool) -> None:
        result.text = text
        result.classes(
            replace="text-sm whitespace-pre-wrap "
            + ("text-positive" if ok else "text-negative")
        )
        result.set_visibility(True)

    async def check() -> None:
        show("Checking…", True)
        status = await run.io_bound(vpn_status)
        found = status["exe_path"]
        lines = [
            f"NordVPN client: {found}" if found else "NordVPN client: not found",
            f"Current public IP: {status['public_ip'] or 'unknown (offline?)'}",
            f"System: {status['platform']}",
        ]
        show("\n".join(lines), bool(found))

    async def rotate() -> None:
        confirm.close()
        rotate_button.disable()
        show("Rotating: the VPN disconnects for a few seconds…", True)
        try:
            changed, before, after = await run.io_bound(rotate_once, current_block())
        finally:
            rotate_button.enable()
        if changed:
            show(f"IP changed: {before} → {after}", True)
        else:
            show(
                f"The IP did not change (before: {before or 'unknown'}, after: "
                f"{after or 'unknown'}). Is the NordVPN app installed and logged in?",
                False,
            )

    with ui.dialog() as confirm, ui.card():
        ui.label("Rotate the VPN now?").classes("font-bold")
        ui.label(
            "NordVPN disconnects then connects to another server: other "
            "connections of this computer drop for a few seconds."
        ).classes("text-sm max-w-md")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=confirm.close).props("flat")
            ui.button("Rotate", on_click=lambda: asyncio.create_task(rotate())).mark(
                "vpn-rotate-confirm"
            )

    with ui.row().classes("gap-2"):
        ui.button("Check VPN", icon="vpn_lock", on_click=check).props(
            "outline dense no-caps"
        ).mark("vpn-check")
        rotate_button = (
            ui.button("Test a rotation…", icon="sync", on_click=confirm.open)
            .props("flat dense no-caps")
            .mark("vpn-rotate")
        )
