"""Regression tests for the review of the configuration system (ADR 0003)."""

import importlib
import logging
import os
from pathlib import Path

import matplotlib.pyplot  # noqa: F401  (load the font cache before HOME is isolated)
import pytest
import yaml

from scilex.settings import cli, loader, resolve
from scilex.settings.loader import load_settings
from scilex.settings.schema import SettingsError

VALID = {
    "name": "demo",
    "search": {"keywords": [["a"]], "years": [2024], "apis": ["OpenAlex"]},
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


def _config(**overrides):
    data = {**VALID, "search": dict(VALID["search"])}
    for key, value in overrides.items():
        if key == "search":
            data["search"].update(value)
        else:
            data[key] = value
    return data


def _load(tmp_path, **overrides):
    config = _write(tmp_path / "scilex.yml", _config(**overrides))
    keys = _write(tmp_path / "keys.yml", {})
    return load_settings(config, keys)


# ---------------------------------------------------------------------------
# 1. Readable errors in every CLI
# ---------------------------------------------------------------------------

CLI_ARGS = {
    "scilex.run_collection": [],
    "scilex.aggregate_collect": [],
    "scilex.enrich_with_pwc": [],
    "scilex.push_to_zotero": [],
    "scilex.export_to_bibtex": [],
    "scilex.enrich_with_citations": [],
    "scilex.export_to_turtle": [],
    "scilex.analyze": [],
    "scilex.snowball_sampling": [],
    "scilex.seed_papers": ["--dois", "10.1000/x"],
    "scilex.summarize_clusters": [],
    "scilex.suggest_keywords": [],
    "scilex.collect_status": [],
}


@pytest.mark.parametrize("module_name", CLI_ARGS)
def test_invalid_config_gives_readable_message_and_exit_1(
    module_name, isolated, monkeypatch, capsys
):
    monkeypatch.setenv("SCILEX_CONFIG", "")
    monkeypatch.setenv("SCILEX_KEYS", "")
    bad = _write(
        isolated / "bad.yml",
        {"name": "t", "search": {**VALID["search"], "yers": 1}},
    )
    module = importlib.import_module(module_name)
    monkeypatch.setattr(
        "sys.argv", ["prog", *CLI_ARGS[module_name], "--config", str(bad)]
    )
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err + captured.out
    assert "search.yers: unknown key" in captured.err
    assert str(bad) in captured.err


@pytest.mark.parametrize("module_name", CLI_ARGS)
def test_missing_config_file_exits_1_with_path_on_stderr(
    module_name, monkeypatch, capsys
):
    monkeypatch.setenv("SCILEX_CONFIG", "")
    monkeypatch.setenv("SCILEX_KEYS", "")
    module = importlib.import_module(module_name)
    monkeypatch.setattr(
        "sys.argv",
        ["prog", *CLI_ARGS[module_name], "--config", "/nonexistent/x.yml"],
    )
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err + captured.out
    assert str(Path("/nonexistent/x.yml")) in captured.err


def test_config_show_with_missing_file_is_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setenv("SCILEX_CONFIG", "/nonexistent/x.yml")
    assert cli.config_show() == 1
    assert str(Path("/nonexistent/x.yml")) in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 2. Booleans are not integers; years are bounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"filters": {"abstract_quality": False}},
        {"filters": {"min_authors": True}},
        {"filters": {"abstract_words": [True, 100]}},
        {"search": {"years": [True]}},
        {"search": {"max_articles_per_query": True}},
        {"ranking": {"max_papers": True}},
    ],
)
def test_boolean_is_rejected_for_integer_fields(isolated, overrides):
    with pytest.raises(SettingsError, match="not a boolean"):
        _load(isolated, **overrides)


@pytest.mark.parametrize("years", [[20], [5000], [999]])
def test_years_out_of_bounds_are_rejected(isolated, years):
    with pytest.raises(SettingsError, match="search.years"):
        _load(isolated, search={"years": years})


def test_years_are_deduplicated_and_sorted(isolated):
    loaded = _load(isolated, search={"years": [2025, 2020, 2020, 2022]})
    assert loaded.settings.search.years == [2020, 2022, 2025]


# ---------------------------------------------------------------------------
# 5. An empty mapping in the file keeps the preset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", ["filters", "ranking", "citations"])
def test_empty_section_does_not_erase_preset(isolated, section):
    with_preset = _load(isolated, preset="bibliometrics").settings
    with_empty = _load(isolated, preset="bibliometrics", **{section: {}}).settings
    assert with_empty == with_preset


def test_none_still_replaces_a_value(isolated):
    loaded = _load(isolated, preset="bibliometrics", ranking={"max_papers": None})
    assert loaded.settings.ranking.max_papers is None


# ---------------------------------------------------------------------------
# 7. Validation at load time
# ---------------------------------------------------------------------------


def test_empty_item_types_is_rejected_with_explanation(isolated):
    with pytest.raises(SettingsError, match="null"):
        _load(isolated, filters={"item_types": []})


def test_llm_screening_enabled_requires_topic(isolated):
    with pytest.raises(SettingsError, match="llm_screening.topic"):
        _load(isolated, llm_screening={"enabled": True})
    loaded = _load(isolated, llm_screening={"enabled": True, "topic": "graphs"})
    assert loaded.settings.llm_screening.topic == "graphs"


def test_unknown_api_is_rejected_with_suggestion(isolated):
    with pytest.raises(SettingsError, match="Did you mean 'OpenAlex'"):
        _load(isolated, search={"apis": ["OpenAlx"]})


def test_api_names_come_from_one_registry():
    from scilex.config_defaults import COLLECTOR_API_NAMES
    from scilex.crawlers.aggregate import FORMAT_CONVERTERS
    from scilex.crawlers.collector_collection import api_collectors

    assert set(COLLECTOR_API_NAMES) == set(api_collectors) == set(FORMAT_CONVERTERS)


def test_config_check_rejects_unknown_api_via_loader(isolated, capsys):
    _write(isolated / "scilex.yml", _config(search={"apis": ["Nope"]}))
    assert cli.config_check() == 1
    assert "unknown API 'Nope'" in capsys.readouterr().err


def test_unknown_keys_block_warns_with_suggestion(isolated, caplog):
    config = _write(isolated / "scilex.yml", _config())
    keys = _write(isolated / "keys.yml", {"Crossref": {"mailto": "a@b.c"}})
    with caplog.at_level(logging.WARNING):
        loaded = load_settings(config, keys)
    assert "Did you mean 'CrossRef'" in caplog.text
    assert "Crossref" in loaded.keys.model_extra  # warned, not refused


# ---------------------------------------------------------------------------
# 4. Environment overrides use the canonical block names
# ---------------------------------------------------------------------------


def _api_config(isolated, keys_data=None):
    _write(isolated / "scilex.yml", _config())
    keys = _write(isolated / "keys.yml", keys_data or {})
    return resolve.resolve_legacy_configs(None, keys)[1]


@pytest.mark.parametrize(
    ("variable", "block", "field"),
    [
        ("SCILEX_CROSSREF_MAILTO", "CrossRef", "mailto"),
        ("SCILEX_UNPAYWALL_EMAIL", "Unpaywall", "email"),
        ("SCILEX_OPENROUTER_API_KEY", "openrouter", "api_key"),
        ("SCILEX_ZOTERO_USER_ID", "Zotero", "user_id"),
        ("SCILEX_SEMANTICSCHOLAR_API_KEY", "SemanticScholar", "api_key"),
        ("SCILEX_ELSEVIER_INST_TOKEN", "Elsevier", "inst_token"),
    ],
)
def test_env_override_creates_canonical_block(
    isolated, monkeypatch, variable, block, field
):
    monkeypatch.setenv(variable, "value")
    api_config = _api_config(isolated)
    assert api_config[block][field] == "value"
    assert "Crossref" not in api_config


def test_env_override_merges_into_existing_canonical_block(isolated, monkeypatch):
    monkeypatch.setenv("SCILEX_CROSSREF_MAILTO", "new@x.org")
    api_config = _api_config(isolated, {"CrossRef": {"mailto": "old", "other": 1}})
    assert api_config["CrossRef"] == {"mailto": "new@x.org", "other": 1}


def test_unknown_api_in_env_warns(isolated, monkeypatch, caplog):
    monkeypatch.setenv("SCILEX_OPENALX_API_KEY", "k")
    with caplog.at_level(logging.WARNING):
        api_config = _api_config(isolated)
    assert "SCILEX_OPENALX_API_KEY" in caplog.text
    assert "Did you mean 'OpenAlex'" in caplog.text
    assert "OpenAlx" not in api_config


def test_reserved_variables_do_not_warn(isolated, monkeypatch, caplog):
    monkeypatch.setenv("SCILEX_CORS_ORIGINS", "*")
    monkeypatch.setenv("SCILEX_PROFILES_DIR", "/x")
    with caplog.at_level(logging.WARNING):
        _api_config(isolated)
    assert "SCILEX_CORS_ORIGINS" not in caplog.text
    assert "SCILEX_PROFILES_DIR" not in caplog.text
