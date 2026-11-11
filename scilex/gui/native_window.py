"""Can this machine open the native window? If not, the app uses a browser tab.

On Linux, pywebview needs Qt WebEngine (bundled in the Linux build) or GTK
with its Python bindings (system packages). Even with Qt bundled, Qt can still
abort at startup, e.g. without a display or without the ``libxcb-cursor0``
system library. Such a failure kills the window process after the server has
started, which leaves the user with nothing on screen. So on Linux the app
first opens the GUI toolkit in a short-lived child process (``--probe-native``)
and falls back to the browser when that child fails.

On Windows, pywebview needs pythonnet, .NET Framework 4.6.2+ and the Microsoft
Edge WebView2 Runtime. The same child-process check loads them. A window can
still fail later without any error (the app is built without a console), so
the app also opens the browser when the window has not loaded after a while
(``open_browser_if_window_missing``).
"""

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable

logger = logging.getLogger(__name__)

PROBE_FLAG = "--probe-native"
PROBE_TIMEOUT_SECONDS = 30
WINDOW_LOAD_TIMEOUT_SECONDS = 45


def _probe_qt() -> None:
    # Same imports as pywebview's Qt backend; QtWebEngineWidgets must be
    # imported before the QApplication is created.
    from qtpy import QtWebEngineWidgets  # noqa: F401
    from qtpy.QtWidgets import QApplication

    QApplication([])


def _probe_gtk() -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    if not Gtk.init_check()[0]:
        raise RuntimeError("GTK cannot open the display")


def _probe_winforms() -> None:
    # Loads pythonnet, .NET and WinForms; checks .NET 4.6.2+ and WebView2.
    from webview.platforms import winforms

    if not winforms.is_chromium:
        raise RuntimeError(
            "Microsoft Edge WebView2 Runtime (or .NET Framework 4.6.2+) is missing"
        )
    # Loads the WebView2 assemblies shipped with pywebview.
    from webview.platforms import edgechromium  # noqa: F401


def _probes() -> tuple[tuple[str, Callable[[], None]], ...]:
    if sys.platform == "win32":
        return (("winforms", _probe_winforms),)
    return (("qt", _probe_qt), ("gtk", _probe_gtk))


def run_probe() -> int:
    """Body of ``scilex-gui --probe-native``: print the usable backend, exit 0 if any."""
    for name, probe in _probes():
        try:
            probe()
        except Exception as exc:
            print(f"{name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        else:
            print(name)
            return 0
    return 1


def _probe_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, PROBE_FLAG]
    return [sys.executable, "-m", "scilex.gui.app", PROBE_FLAG]


def native_window_problem() -> str | None:
    """Return why the native window cannot open here, or None if it can.

    On Linux, also sets ``PYWEBVIEW_GUI`` to the backend that passed the
    probe, so the window process does not try another one first.
    """
    is_windows = sys.platform == "win32"
    if not (is_windows or sys.platform.startswith("linux")):
        return None  # macOS ships its own web view
    if not is_windows and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return "no graphical display (DISPLAY and WAYLAND_DISPLAY are not set)"
    # From source, python.exe is a console program: do not flash a console.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0
    try:
        result = subprocess.run(
            _probe_command(),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"the window toolkit check failed to run ({exc})"
    if result.returncode != 0:
        details = (result.stderr or "").strip()[-2000:]
        toolkit = "WebView2" if is_windows else "Qt or GTK"
        return f"no usable window toolkit ({toolkit}):\n{details}"
    backend = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if backend in ("qt", "gtk"):
        os.environ.setdefault("PYWEBVIEW_GUI", backend)
    return None


def open_browser_if_window_missing(
    url: str,
    window_loaded: threading.Event,
    timeout: float = WINDOW_LOAD_TIMEOUT_SECONDS,
    open_url: Callable[[str], object] = webbrowser.open,
) -> bool:
    """Open ``url`` in the browser if the native window has not loaded in time.

    Blocking: run it in a thread. Returns True when the browser was opened.
    """
    if window_loaded.wait(timeout):
        return False
    logger.warning(
        "The SciLEx window did not load within %s s, opening %s in the web browser.",
        timeout,
        url,
    )
    open_url(url)
    return True
