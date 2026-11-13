"""The frozen windowed app has no console: writing "✓" must not fail."""

import io
import sys

from scilex.gui.app import safe_console_streams


def test_missing_streams_accept_any_character(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    safe_console_streams()
    try:
        print("✓ 💾 done", file=sys.stderr)
        print("✓", file=sys.stdout)
    finally:
        sys.stderr.close()
        sys.stdout.close()


def test_cp1252_console_replaces_instead_of_raising(monkeypatch):
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stderr", console)
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), "cp1252"))
    safe_console_streams()
    print("fetching ✓ 12", file=sys.stderr)
    sys.stderr.flush()
    assert raw.getvalue().rstrip() == b"fetching ? 12"
