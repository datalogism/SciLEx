"""SciLEx logo and icon files shown by the desktop app."""

from pathlib import Path

from nicegui import ui

ASSETS_DIR = Path(__file__).parents[1] / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"  # wide logo, transparent background
ICON_PATH = ASSETS_DIR / "icon.png"  # square icon (window, tab, app bundle)


def render_logo(width: str = "w-40") -> ui.image:
    """Draw the SciLEx logo at the given Tailwind width."""
    return (
        ui.image(LOGO_PATH)
        .classes(width)
        .props("fit=contain no-spinner no-transition")
        .mark("logo")
    )
