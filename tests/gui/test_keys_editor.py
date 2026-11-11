"""Unit tests of the keys editor service (no UI, no network)."""

import os
import stat
from unittest.mock import patch

import pytest
import requests
import yaml

from scilex.gui.services import keys_editor as editor


def test_keys_path_uses_env(isolated_scilex_env):
    assert editor.keys_path() == isolated_scilex_env


def test_round_trip_mode_and_unknown_blocks(isolated_scilex_env):
    isolated_scilex_env.write_text("Custom:\n  foo: bar\nOpenAlex:\n  api_key: a\n")
    data = editor.load_keys()
    editor.set_keys_list(data, "OpenAlex", ["k1", "k2"])
    editor.save_keys(data)
    saved = yaml.safe_load(isolated_scilex_env.read_text())
    assert saved["Custom"] == {"foo": "bar"}
    assert saved["OpenAlex"]["api_key"] == ["k1", "k2"]
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert stat.S_IMODE(os.stat(isolated_scilex_env).st_mode) == 0o600
    assert editor.get_keys_list(saved["OpenAlex"]) == ["k1", "k2"]


def test_set_keys_list_single_and_empty():
    data = {}
    editor.set_keys_list(data, "IEEE", [" x "])
    assert data["IEEE"]["api_key"] == "x"
    editor.set_keys_list(data, "IEEE", ["", " "])
    assert "IEEE" not in data


def test_save_rejects_invalid(isolated_scilex_env):
    with pytest.raises(ValueError):
        editor.save_keys({"IEEE": "not a mapping"})


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SCILEX_OPENALEX_API_KEY", "x")
    assert editor.env_overrides()["OpenAlex.api_key"] == "SCILEX_OPENALEX_API_KEY"


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status", "expected"), [(200, True), (401, False), (403, False), (500, False)]
)
def test_check_key_statuses(status, expected):
    with patch("requests.get", return_value=_Response(status)):
        ok, message = editor.check_key("SemanticScholar", "secret")
    assert ok is expected
    assert "secret" not in message


def test_check_key_timeout_and_empty():
    with patch("requests.get", side_effect=requests.Timeout):
        ok, message = editor.check_key("IEEE", "k")
    assert not ok
    assert "Timeout" in message
    assert editor.check_key("IEEE", "")[0] is False
    assert editor.check_key("Unknown", "k")[0] is False


def test_check_zotero():
    with patch("requests.get", return_value=_Response(200)) as get:
        assert editor.check_zotero("k", "12", "group")[0]
    assert "/groups/12/" in get.call_args.args[0]


def test_unchanged_springer_mapping_keeps_its_shape():
    from scilex.gui.services import keys_editor

    mapping = {"meta_api_key": "META", "openaccess_api_key": "OA"}
    data = {"Springer": {"api_key": dict(mapping)}}
    keys_editor.set_keys_list(data, "Springer", ["META", "OA"])
    assert data["Springer"]["api_key"] == mapping


def test_save_keeps_a_private_backup_of_the_previous_file(isolated_scilex_env):
    isolated_scilex_env.write_text("OpenAlex:\n  api_key: old\n")
    editor.save_keys({"OpenAlex": {"api_key": "new"}})
    backup = isolated_scilex_env.with_name(isolated_scilex_env.name + ".bak")
    assert "old" in backup.read_text()
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert stat.S_IMODE(os.stat(backup).st_mode) == 0o600
