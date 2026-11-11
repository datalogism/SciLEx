"""Tests of the native-window check and the browser fallback (Linux tester report)."""

import subprocess
import sys
import threading

import pytest

from scilex.gui import native_window
from scilex.gui.app import _use_native_window, build_parser


@pytest.fixture
def on_linux(monkeypatch):
    monkeypatch.setattr(native_window.sys, "platform", "linux")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")


def _fake_probe(monkeypatch, returncode, stdout="", stderr=""):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    monkeypatch.setattr(native_window.subprocess, "run", run)


def test_no_check_on_macos(monkeypatch):
    monkeypatch.setattr(native_window.sys, "platform", "darwin")
    assert native_window.native_window_problem() is None


def test_no_display_means_no_window(on_linux, monkeypatch):
    monkeypatch.delenv("DISPLAY")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert "no graphical display" in native_window.native_window_problem()


def test_failed_probe_reports_toolkit_errors(on_linux, monkeypatch):
    _fake_probe(
        monkeypatch, 1, stderr="qt: ModuleNotFoundError: No module named 'qtpy'"
    )
    problem = native_window.native_window_problem()
    assert "no usable window toolkit" in problem
    assert "qtpy" in problem


def test_successful_probe_pins_the_backend(on_linux, monkeypatch):
    _fake_probe(monkeypatch, 0, stdout="qt\n")
    assert native_window.native_window_problem() is None
    assert native_window.os.environ["PYWEBVIEW_GUI"] == "qt"


def test_probe_timeout_is_a_problem(on_linux, monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("probe", 30)

    monkeypatch.setattr(native_window.subprocess, "run", run)
    assert "failed to run" in native_window.native_window_problem()


def test_app_falls_back_to_browser(monkeypatch, capsys):
    monkeypatch.setattr(native_window, "native_window_problem", lambda: "no Qt")
    assert _use_native_window(build_parser().parse_args([])) is False
    assert "web browser" in capsys.readouterr().err


def test_browser_flag_skips_the_check(monkeypatch):
    def fail():
        raise AssertionError("check must not run in browser mode")

    monkeypatch.setattr(native_window, "native_window_problem", fail)
    assert _use_native_window(build_parser().parse_args(["--browser"])) is False


def test_probe_command_runs_from_source():
    # Real child process: exits 0 or 1 (no display / no toolkit), never crashes.
    result = subprocess.run(
        [*native_window._probe_command()], capture_output=True, text=True, timeout=60
    )
    assert result.returncode in (0, 1), result.stderr
    assert native_window._probe_command()[0] == sys.executable


def test_windows_probe_runs_without_display(monkeypatch):
    # Windows has no DISPLAY: the probe must run anyway.
    monkeypatch.setattr(native_window.sys, "platform", "win32")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    _fake_probe(monkeypatch, 1, stderr="winforms: RuntimeError: WebView2 is missing")
    problem = native_window.native_window_problem()
    assert "WebView2" in problem


def test_windows_successful_probe(monkeypatch):
    monkeypatch.setattr(native_window.sys, "platform", "win32")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    _fake_probe(monkeypatch, 0, stdout="winforms\n")
    assert native_window.native_window_problem() is None
    assert "PYWEBVIEW_GUI" not in native_window.os.environ


def test_windows_probes_winforms_only(monkeypatch):
    monkeypatch.setattr(native_window.sys, "platform", "win32")
    assert [name for name, _ in native_window._probes()] == ["winforms"]


def test_browser_opens_when_window_never_loads():
    opened = []
    assert native_window.open_browser_if_window_missing(
        "http://127.0.0.1:8000", threading.Event(), timeout=0.01, open_url=opened.append
    )
    assert opened == ["http://127.0.0.1:8000"]


def test_no_browser_when_window_loads():
    loaded = threading.Event()
    loaded.set()
    opened = []
    assert not native_window.open_browser_if_window_missing(
        "http://x", loaded, timeout=0.01, open_url=opened.append
    )
    assert opened == []
