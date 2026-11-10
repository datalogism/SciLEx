"""Profile screen: the user's ORCID iD, required before anything else."""

from nicegui import run, ui

from scilex.gui.components.branding import render_logo
from scilex.gui.state import AppContext
from scilex.user_profile import InvalidOrcidError, lookup_name


def render(ctx: AppContext) -> None:
    """Draw the ORCID form (shown instead of any page while no iD is set)."""
    profile = ctx.profile
    with ui.column().classes("p-6 gap-3 max-w-xl"):
        render_logo("w-40")
        ui.label("Your ORCID iD").classes("text-2xl font-bold")
        ui.label(
            "SciLEx needs your ORCID iD before you can use it. It identifies who "
            "collected, screened and annotated the papers, and is written as the "
            "creator of the knowledge graphs you export."
        ).classes("text-gray-600")
        ui.link("Get an ORCID iD (free)", "https://orcid.org/register", new_tab=True)
        orcid_input = (
            ui.input(
                "ORCID iD",
                value=profile.orcid,
                placeholder="0000-0002-1825-0097 or https://orcid.org/…",
            )
            .props("clearable")
            .classes("w-96")
            .mark("orcid-input")
        )
        name_input = ui.input("Name (optional)", value=profile.name).classes("w-96").mark(
            "orcid-name"
        )
        error = ui.label("").classes("text-negative").mark("orcid-error")
        found = ui.label("").classes("text-sm text-gray-600").mark("orcid-found")

        async def check() -> None:
            error.text = found.text = ""
            try:
                name = await run.io_bound(lookup_name, orcid_input.value or "")
            except (InvalidOrcidError, ConnectionError) as exc:
                error.text = str(exc)
                return
            if name is None:
                error.text = "No ORCID record has this iD."
            else:
                found.text = f"Registered on orcid.org as: {name or '(name not public)'}"
                if name and not name_input.value:
                    name_input.value = name

        def save() -> None:
            error.text = ""
            try:
                profile.set(orcid_input.value or "", name_input.value or "")
            except InvalidOrcidError as exc:
                error.text = str(exc)
                return
            ui.navigate.to("/")

        with ui.row().classes("gap-2"):
            ui.button("Save", icon="check", on_click=save).mark("orcid-save")
            ui.button("Check on orcid.org", icon="travel_explore", on_click=check).props(
                "outline"
            ).mark("orcid-check")
            if profile.is_complete:
                ui.button("Back", on_click=lambda: ui.navigate.to("/")).props("flat")
