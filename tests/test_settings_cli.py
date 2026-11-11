"""Tests for the shared --config/--keys options, ``scilex config`` and VPN config."""

import importlib
import os

import matplotlib.pyplot  # noqa: F401  (load the font cache before HOME is isolated)
import pytest
import yaml

from scilex.__main__ import ARGV_COMMANDS
from scilex.settings import cli, loader, resolve
from scilex.vpn import rotator

CLI_MODULES = [
    "scilex.run_collection",
    "scilex.aggregate_collect",
    "scilex.enrich_with_pwc",
    "scilex.push_to_zotero",
    "scilex.export_to_bibtex",
    "scilex.report_charts",
    "scilex.enrich_with_citations",
    "scilex.export_to_turtle",
    "scilex.analyze",
    "scilex.snowball_sampling",
    "scilex.seed_papers",
    "scilex.summarize_clusters",
    "scilex.suggest_keywords",
    "scilex.collect_status",
]

VALID = {
    "name": "demo",
    "search": {"keywords": [["a"]], "years": [2024], "apis": ["OpenAlex"]},
}
LEGACY = {
    "collect_name": "old",
    "keywords": [["a"]],
    "years": [2024],
    "apis": ["OpenAlex"],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    package = tmp_path / "package"
    package.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # "~" on Windows
    monkeypatch.chdir(tmp_path)
    for variable in list(os.environ):
        if variable.startswith("SCILEX_"):
            monkeypatch.delenv(variable)
    monkeypatch.setattr(resolve, "PACKAGE_DIR", package)
    monkeypatch.setattr(cli, "PACKAGE_DIR", package)
    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", package / "api.config.yml")
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_every_cli_accepts_config_and_keys(module_name, monkeypatch, capsys):
    module = importlib.import_module(module_name)
    monkeypatch.setattr("sys.argv", ["prog", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--config" in help_text
    assert "--keys" in help_text


def test_apply_config_arguments_sets_environment(monkeypatch):
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_config_arguments(parser)
    args = parser.parse_args(["--config", "a.yml", "--keys", "k.yml"])
    cli.apply_config_arguments(args)
    assert os.environ["SCILEX_CONFIG"] == "a.yml"
    assert os.environ["SCILEX_KEYS"] == "k.yml"
    monkeypatch.delenv("SCILEX_CONFIG")
    monkeypatch.delenv("SCILEX_KEYS")


def test_scilex_commands_registered():
    assert set(ARGV_COMMANDS) == {"init", "config"}


# ---------------------------------------------------------------------------
# scilex config check / show / migrate
# ---------------------------------------------------------------------------


def test_check_valid_returns_0(isolated, capsys):
    _write(isolated / "scilex.yml", VALID)
    assert cli.config_main(["check"]) == 0
    assert "valid" in capsys.readouterr().out


def test_check_invalid_returns_1_with_readable_message(isolated, capsys):
    _write(isolated / "scilex.yml", {**VALID, "filters": {"max_paper": 3}})
    assert cli.config_main(["check"]) == 1
    assert "Did you mean ranking.max_papers" in capsys.readouterr().err


def test_check_unknown_api_and_missing_file(isolated, capsys):
    assert cli.config_main(["check"]) == 1
    bad = {**VALID, "search": {**VALID["search"], "apis": ["Nope"]}}
    _write(isolated / "scilex.yml", bad)
    assert cli.config_main(["check"]) == 1
    assert "Nope" in capsys.readouterr().err


def test_check_with_config_option(isolated):
    path = _write(isolated / "other" / "r.yml", VALID)
    assert cli.config_main(["check", "--config", str(path)]) == 0


def test_check_legacy_file_is_valid_but_flagged(isolated, capsys):
    _write(resolve.PACKAGE_DIR / "scilex.config.yml", LEGACY)
    assert cli.config_main(["check"]) == 0
    assert "legacy" in capsys.readouterr().out


def test_show_prints_provenance_and_masks_secrets(isolated, capsys):
    _write(isolated / "scilex.yml", {**VALID, "preset": "bibliometrics"})
    _write(
        isolated / "home/.config/scilex/keys.yml",
        {"OpenAlex": {"api_key": "SECRET123"}},
    )
    assert cli.config_main(["show"]) == 0
    output = capsys.readouterr().out
    assert "name = " in output and "(file)" in output
    assert "filters.citations = false   (preset:bibliometrics)" in output
    assert "output_dir = " in output and "(default)" in output
    assert "SECRET123" not in output
    assert "keys.OpenAlex.api_key = ***" in output


def test_migrate_prints_then_writes_without_overwriting(isolated, capsys):
    legacy_dir = isolated / "legacy"
    _write(legacy_dir / "scilex.config.yml", LEGACY)
    assert cli.config_main(["migrate", "--from", str(legacy_dir)]) == 0
    assert "name: old" in capsys.readouterr().out
    assert not (isolated / "scilex.yml").exists()
    assert cli.config_main(["migrate", "--from", str(legacy_dir), "--write"]) == 0
    assert yaml.safe_load((isolated / "scilex.yml").read_text())["name"] == "old"
    assert cli.config_main(["migrate", "--from", str(legacy_dir), "--write"]) == 1
    args = ["migrate", "--from", str(legacy_dir), "--write", "--force"]
    assert cli.config_main(args) == 0


def test_migrate_missing_directory_returns_1(isolated):
    assert cli.config_main(["migrate", "--from", str(isolated / "none")]) == 1


# ---------------------------------------------------------------------------
# VPN
# ---------------------------------------------------------------------------


def test_vpn_config_from_new_format(isolated):
    block = {"enabled": True, "provider": "x"}
    _write(isolated / "scilex.yml", {**VALID, "collect": {"vpn": block}})
    main_config, api_config = resolve.resolve_legacy_configs()
    assert rotator.vpn_config_from_configs(main_config, api_config) == block


def test_vpn_config_legacy_api_config_fallback(isolated):
    _write(resolve.PACKAGE_DIR / "scilex.config.yml", LEGACY)
    _write(resolve.PACKAGE_DIR / "api.config.yml", {"vpn": {"enabled": True}})
    main_config, api_config = resolve.resolve_legacy_configs()
    assert rotator.vpn_config_from_configs(main_config, api_config) == {"enabled": True}


def test_vpn_config_never_raises(isolated):
    assert rotator.vpn_config_from_configs({}, {}) == {}  # nothing configured
    assert rotator.vpn_config_from_configs(None, None) == {}
    assert rotator.vpn_config_from_configs({"vpn": "oops"}, {}) == {}
