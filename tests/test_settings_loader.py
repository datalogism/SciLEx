"""Tests for scilex.settings loader (discovery, precedence, env, provenance)."""

import logging
import os
from pathlib import Path

import pytest
import yaml

from scilex.settings import (
    SettingsError,
    find_config_file,
    find_keys_file,
    load_settings,
    loader,
    to_legacy,
)

BASE = {
    "name": "review",
    "search": {"keywords": [["a"]], "years": "2023-2024", "apis": ["OpenAlex"]},
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Isolate HOME, cwd and SCILEX_* variables, and hide the legacy keys file."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # "~" on Windows
    monkeypatch.chdir(tmp_path)
    for variable in list(os.environ):
        if variable.startswith("SCILEX_"):
            monkeypatch.delenv(variable)
    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", tmp_path / "no_legacy.yml")
    return tmp_path


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_minimal(isolated):
    _write(isolated / "scilex.yml", BASE)
    loaded = load_settings()
    assert loaded.settings.search.years == [2023, 2024]
    assert loaded.config_path == isolated / "scilex.yml"
    assert loaded.keys_path is None


def test_missing_config_raises(isolated):
    with pytest.raises(FileNotFoundError):
        load_settings()


def test_invalid_file_raises_readable(isolated):
    _write(isolated / "scilex.yml", {**BASE, "filters": {"max_paper": 3}})
    with pytest.raises(SettingsError, match="Did you mean ranking.max_papers"):
        load_settings()


def test_unknown_preset(isolated):
    _write(isolated / "scilex.yml", {**BASE, "preset": "bibliometric"})
    with pytest.raises(SettingsError, match="unknown preset"):
        load_settings()


def test_preset_precedence(isolated):
    _write(
        isolated / "scilex.yml",
        {**BASE, "preset": "bibliometrics", "ranking": {"max_papers": 50}},
    )
    settings = load_settings().settings
    assert settings.ranking.max_papers == 50  # file beats preset
    assert settings.filters.require == []  # preset beats default
    assert settings.filters.citations is False


def test_cli_override_precedence(isolated):
    _write(isolated / "scilex.yml", {**BASE, "ranking": {"max_papers": 50}})
    loaded = load_settings(
        cli_overrides={"ranking": {"max_papers": 7}, "search": {"years": [2020]}}
    )
    assert loaded.settings.ranking.max_papers == 7
    assert loaded.settings.search.years == [2020]
    assert loaded.settings.search.apis == ["OpenAlex"]  # deep merge keeps siblings


def test_provenance(isolated):
    _write(isolated / "scilex.yml", {**BASE, "preset": "bibliometrics"})
    loaded = load_settings(cli_overrides={"output_dir": "elsewhere"})
    assert loaded.provenance["name"] == "file"
    assert loaded.provenance["output_dir"] == "cli"
    assert loaded.provenance["filters.citations"] == "preset:bibliometrics"
    assert loaded.provenance["ranking.enabled"] == "default"


def test_config_discovery_order(isolated, monkeypatch):
    local = _write(isolated / "scilex.yml", BASE)
    assert find_config_file() == local
    from_env = _write(isolated / "env.yml", BASE)
    monkeypatch.setenv("SCILEX_CONFIG", str(from_env))
    assert find_config_file() == from_env
    from_cli = _write(isolated / "cli.yml", BASE)
    assert find_config_file(from_cli) == from_cli


def test_no_config_returns_none(isolated):
    assert find_config_file() is None


def test_keys_discovery_order(isolated, monkeypatch):
    user_keys = _write(isolated / "home" / ".config" / "scilex" / "keys.yml", {})
    assert find_keys_file() == user_keys
    from_env = _write(isolated / "env_keys.yml", {})
    monkeypatch.setenv("SCILEX_KEYS", str(from_env))
    assert find_keys_file() == from_env
    from_cli = _write(isolated / "cli_keys.yml", {})
    assert find_keys_file(from_cli) == from_cli


def test_legacy_keys_fallback_warns(isolated, monkeypatch, caplog):
    legacy = _write(isolated / "legacy_api.yml", {"Zotero": {"api_key": "k"}})
    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", legacy)
    with caplog.at_level(logging.WARNING, logger="scilex.settings.loader"):
        assert find_keys_file() == legacy
    assert "deprecated" in caplog.text


def test_env_key_override(isolated, monkeypatch):
    _write(isolated / "scilex.yml", BASE)
    keys = _write(isolated / "keys.yml", {"SemanticScholar": {"api_key": "from_file"}})
    monkeypatch.setenv("SCILEX_SEMANTICSCHOLAR_API_KEY", "from_env")
    monkeypatch.setenv("SCILEX_ELSEVIER_INST_TOKEN", "tok")
    loaded = load_settings(keys_path=keys)
    _, api = to_legacy(loaded.settings, loaded.keys)
    assert api["SemanticScholar"]["api_key"] == "from_env"
    assert api["Elsevier"]["inst_token"] == "tok"
    assert loaded.provenance["keys.SemanticScholar.api_key"] == "env"


def test_keys_file_legacy_shape(isolated):
    _write(isolated / "scilex.yml", BASE)
    keys = _write(
        isolated / "keys.yml",
        {
            "Zotero": {"api_key": "z", "user_id": "1"},
            "rate_limits": {"IEEE": 2.0},
            "ORCID": None,
        },
    )
    loaded = load_settings(keys_path=keys)
    _, api = to_legacy(loaded.settings, loaded.keys)
    assert api == {
        "Zotero": {"api_key": "z", "user_id": "1"},
        "ORCID": {},
        "rate_limits": {"IEEE": 2.0},
    }
    assert loaded.provenance["keys.Zotero.api_key"] == "file"


def test_invalid_keys(isolated):
    _write(isolated / "scilex.yml", BASE)
    keys = _write(isolated / "keys.yml", {"Zotero": "oops"})
    with pytest.raises(SettingsError, match="keys"):
        load_settings(keys_path=keys)


def test_to_legacy_shape(isolated):
    _write(
        isolated / "scilex.yml",
        {
            **BASE,
            "filters": {
                "item_types": ["book"],
                "require": ["doi"],
                "abstract_quality": 80,
            },
            "enrichment": {"paperswithcode": True},
            "collect": {"vpn": {"enabled": True}},
            "search": {**BASE["search"], "max_articles_per_query": 10},
        },
    )
    main, _ = to_legacy(load_settings().settings)
    qf = main["quality_filters"]
    assert qf["enable_itemtype_filter"] is True and qf["allowed_item_types"] == ["book"]
    assert qf["require_doi"] and not qf["require_abstract"]
    assert qf["validate_abstracts"] is True and qf["min_abstract_quality_score"] == 80
    assert main["max_articles_per_query"] == 10
    assert main["vpn"] == {"enabled": True}
    assert main["pwc_enrichment"]["enabled"] is True
    assert main["collect_name"] == "review"


def test_deprecated_huggingface_key_in_file(tmp_path, caplog):
    path = tmp_path / "scilex.yml"
    path.write_text(
        yaml.safe_dump({**BASE, "enrichment": {"huggingface": {"workers": 6}}})
    )
    with caplog.at_level(logging.WARNING):
        loaded = load_settings(config_path=path)
    block = loaded.settings.enrichment.paperswithcode
    assert block.enabled is True
    assert block.workers == 6
    assert "deprecated" in caplog.text


def test_huggingface_and_paperswithcode_in_file_is_an_error(tmp_path):
    path = tmp_path / "scilex.yml"
    path.write_text(
        yaml.safe_dump(
            {**BASE, "enrichment": {"huggingface": True, "paperswithcode": True}}
        )
    )
    with pytest.raises(SettingsError, match="both set"):
        load_settings(config_path=path)
