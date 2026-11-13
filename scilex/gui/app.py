"""Entry point of the SciLEx desktop application (``scilex-gui``)."""

import argparse
import contextlib
import logging
import multiprocessing
import os
import sys
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

WINDOW_SIZE = (1280, 800)


PRIMARY_COLOUR = "#1976d2"
WARNING_COLOUR = "#b45309"
# Keyboard focus must be visible. Quasar's `.no-outline` (outline: 0 !important,
# in a cascade layer that wins) removes the outline: draw a ring with box-shadow.
ACCESSIBILITY_CSS = (
    "html body :focus-visible "
    "{ box-shadow: 0 0 0 2px #fff, 0 0 0 4px #1d4ed8 !important; }"
)


def build_root(ctx) -> Callable[[], None]:
    """Return the NiceGUI root function routing between the screens."""
    import functools

    from nicegui import ui

    from scilex.gui.pages import home, keys, profile, review

    def require_orcid(page: Callable) -> Callable:
        """Show the ORCID form instead of ``page`` while the user has no ORCID iD."""

        @functools.wraps(page)  # keeps the signature NiceGUI reads the route data from
        def gated(*args, **kwargs):
            if not ctx.profile.is_complete:
                profile.render(ctx)
                return None
            return page(*args, **kwargs)

        return gated

    def root() -> None:
        # Contrast (WCAG AA): NiceGUI's light blue gives 3:1 with white text.
        # Amber warnings on white were ~1.7:1; amber-700 is ~5:1.
        ui.colors(primary=PRIMARY_COLOUR, warning=WARNING_COLOUR)
        # A plain <style> in the head: ui.add_css lost against Quasar's outline reset.
        ui.add_head_html(f"<style>{ACCESSIBILITY_CSS}</style>")
        ui.sub_pages(
            {
                "/": require_orcid(home.render),
                "/profile": profile.render,
                "/keys": require_orcid(keys.render_global),
                "/review/{review_id}": require_orcid(review.render),
                "/review/{review_id}/{step}": require_orcid(review.render),
            },
            data={"ctx": ctx},
        ).classes("w-full")  # flex column with align-items:flex-start would shrink-wrap

    return root


def build_parser() -> argparse.ArgumentParser:
    """Command-line options of ``scilex-gui``."""
    parser = argparse.ArgumentParser(
        prog="scilex-gui", description="SciLEx desktop application"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="check the installation without opening a window, then exit",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="open the UI in a browser tab instead of a native window (debugging)",
    )
    parser.add_argument("--port", type=int, default=None, help="port (browser mode)")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="browser mode: do not open a browser tab (automated UI tests)",
    )
    # Internal: run by the app itself in a child process (see native_window.py).
    parser.add_argument("--probe-native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _use_native_window(args: argparse.Namespace) -> bool:
    """False in browser mode, or when no native window can open on this machine."""
    if args.browser:
        return False
    from scilex.gui.native_window import native_window_problem

    problem = native_window_problem()
    if problem is None:
        return True
    message = f"Cannot open the SciLEx window, opening it in your web browser instead. Reason: {problem}"
    logger.warning(message)
    print(message, file=sys.stderr)
    return False


def safe_console_streams() -> None:
    """Make stdout/stderr accept any character (progress bars, ✓ in logs).

    A windowed frozen app has no console: writers get ``os.devnull``, opened
    in UTF-8 (the Windows default, cp1252, cannot encode "✓" and made the
    citation fetching of the pipeline fail). A real Windows console keeps its
    encoding but replaces what it cannot show instead of raising.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
        elif hasattr(stream, "reconfigure"):
            # A detached or unusual stream is left as it is.
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Start the desktop application."""
    # Must come first: in the frozen app every multiprocessing worker
    # re-executes this entry point.
    multiprocessing.freeze_support()
    safe_console_streams()
    args = build_parser().parse_args(argv)

    if args.probe_native:
        from scilex.gui.native_window import run_probe

        return run_probe()

    if args.self_test:
        from scilex.gui.self_test import run_self_test

        return run_self_test()

    from nicegui import app, ui

    from scilex.gui.components.branding import ICON_PATH
    from scilex.gui.services.diagnostics import setup_file_logging
    from scilex.gui.state import AppContext

    log_path = setup_file_logging()
    logger.info("Starting SciLEx GUI (log file: %s)", log_path)
    app.on_exception(lambda exc: logger.error("Unhandled UI error", exc_info=exc))

    native = _use_native_window(args)
    ctx = AppContext(native=native)
    port = args.port
    if native:
        # pywebview disables text selection by default: logs could not be copied.
        app.native.window_args["text_select"] = True
        port = port or _watch_native_window(app)
    ui.run(
        build_root(ctx),
        title="SciLEx",
        language="en-US",  # <html lang>, for screen readers
        favicon=ICON_PATH,
        native=native,
        window_size=WINDOW_SIZE if native else None,
        port=port,
        reload=False,
        show=not native and not args.no_open,
    )
    return 0


def _watch_native_window(app) -> int:
    """Open the browser if the native window never loads; return the server port.

    The window can fail without any error (e.g. WebView2 hanging on Windows),
    leaving the server running with nothing on screen.
    """
    from nicegui.native import find_open_port

    from scilex.gui.native_window import open_browser_if_window_missing

    port = find_open_port()
    window_loaded = threading.Event()
    app.native.on("loaded", window_loaded.set)
    app.on_startup(
        lambda: threading.Thread(
            target=open_browser_if_window_missing,
            args=(f"http://127.0.0.1:{port}", window_loaded),
            daemon=True,
        ).start()
    )
    return port


def _show_fatal_error(message: str) -> None:
    """Show a startup error: the frozen Windows app has no console to print it."""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "SciLEx", 0x10)


def run() -> int:
    """``main()`` that reports fatal startup errors in a dialog on Windows."""
    try:
        return main()
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("SciLEx failed to start")
        _show_fatal_error(f"SciLEx failed to start:\n{type(exc).__name__}: {exc}")
        raise


# Not "__mp_main__": spawned multiprocessing children import this module
# under that name and must not start a second app.
if __name__ == "__main__":
    sys.exit(run())
