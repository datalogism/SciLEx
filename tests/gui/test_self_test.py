"""Tests for ``scilex-gui --self-test``."""

from scilex.gui import self_test
from scilex.gui.app import main


def test_self_test_passes_in_dev_install(capsys):
    assert main(["--self-test"]) == 0
    assert "self-test passed" in capsys.readouterr().out


def test_self_test_reports_failures(monkeypatch, capsys):
    monkeypatch.setitem(self_test.REQUIRED_DATA, "missing_dir", "*.csv")

    assert self_test.run_self_test() == 1
    assert "FAIL data files" in capsys.readouterr().out
