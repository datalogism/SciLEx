"""Tests for the single configuration resolution point and the new schema keys."""

import logging
import os

import pytest
import yaml

from scilex.config import SciLExConfig
from scilex.crawlers.utils import load_all_configs
from scilex.settings import SettingsError, loader, resolve, to_legacy
from scilex.settings.loader import load_settings
from scilex.settings.migrate import legacy_to_settings
from scilex.settings.resolve import resolve_legacy_configs

NEW_FORMAT = {
    "name": "new_review",
    "search": {"keywords": [["a"]], "years": [2024], "apis": ["OpenAlex"]},
}
LEGACY_FORMAT = {
    "collect_name": "old_review",
    "keywords": [["a"]],
    "years": [2024],
    "apis": ["OpenAlex"],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Isolate HOME, cwd, SCILEX_* variables and the legacy package files."""
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
    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", package / "api.config.yml")
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def test_local_scilex_yml_is_used(isolated):
    _write(isolated / "scilex.yml", NEW_FORMAT)
    main, api = resolve_legacy_configs()
    assert main["collect_name"] == "new_review"
    assert api == {}


def test_cli_beats_env_beats_local(isolated, monkeypatch):
    _write(isolated / "scilex.yml", {**NEW_FORMAT, "name": "local"})
    _write(isolated / "env.yml", {**NEW_FORMAT, "name": "env"})
    _write(isolated / "cli.yml", {**NEW_FORMAT, "name": "cli"})
    monkeypatch.setenv("SCILEX_CONFIG", str(isolated / "env.yml"))
    assert resolve_legacy_configs()[0]["collect_name"] == "env"
    cli_main = resolve_legacy_configs(str(isolated / "cli.yml"))[0]
    assert cli_main["collect_name"] == "cli"


def test_keys_priority_and_env_override(isolated, monkeypatch):
    _write(isolated / "scilex.yml", NEW_FORMAT)
    _write(isolated / "home/.config/scilex/keys.yml", {"OpenAlex": {"api_key": "home"}})
    _write(isolated / "env_keys.yml", {"OpenAlex": {"api_key": "envfile"}})
    _write(isolated / "cli_keys.yml", {"OpenAlex": {"api_key": "cli"}})
    assert resolve_legacy_configs()[1]["OpenAlex"]["api_key"] == "home"
    monkeypatch.setenv("SCILEX_KEYS", str(isolated / "env_keys.yml"))
    assert resolve_legacy_configs()[1]["OpenAlex"]["api_key"] == "envfile"
    cli_api = resolve_legacy_configs(keys_path=str(isolated / "cli_keys.yml"))[1]
    assert cli_api["OpenAlex"]["api_key"] == "cli"
    monkeypatch.setenv("SCILEX_OPENALEX_API_KEY", "fromenv")
    assert resolve_legacy_configs()[1]["OpenAlex"]["api_key"] == "fromenv"


def test_legacy_fallback_warns_and_merges_advanced(caplog):
    package = resolve.PACKAGE_DIR
    _write(package / "scilex.config.yml", LEGACY_FORMAT)
    _write(package / "scilex.advanced.yml", {"quality_filters": {"max_papers": 7}})
    _write(package / "api.config.yml", {"SemanticScholar": {"api_key": "k"}})
    with caplog.at_level(logging.WARNING):
        main, api = resolve_legacy_configs()
    assert main["collect_name"] == "old_review"
    assert main["quality_filters"]["max_papers"] == 7
    assert api["SemanticScholar"]["api_key"] == "k"
    assert "scilex config migrate" in caplog.text


def test_explicit_legacy_file_is_accepted_with_warning(isolated, caplog):
    path = _write(isolated / "job" / "legacy.yml", LEGACY_FORMAT)
    with caplog.at_level(logging.WARNING):
        main, _ = resolve_legacy_configs(str(path))
    assert main["collect_name"] == "old_review"
    assert "scilex config migrate" in caplog.text


def test_nothing_found_raises():
    with pytest.raises(FileNotFoundError):
        resolve_legacy_configs()


def test_missing_explicit_file_raises(isolated):
    with pytest.raises(FileNotFoundError):
        resolve_legacy_configs(str(isolated / "nope.yml"))


def test_invalid_new_format_raises_settings_error(isolated):
    _write(isolated / "scilex.yml", {**NEW_FORMAT, "bogus": 1})
    with pytest.raises(SettingsError):
        resolve_legacy_configs()


def test_from_files_and_load_all_configs_share_the_resolver(isolated):
    _write(isolated / "scilex.yml", NEW_FORMAT)
    assert SciLExConfig.from_files().main["collect_name"] == "new_review"
    configs = load_all_configs({"main_config": "x.yml", "api_config": "y.yml"})
    assert configs["main_config"]["collect_name"] == "new_review"
    assert configs["api_config"] == {}
    only_main = load_all_configs({"main_config": "x.yml"})
    assert only_main["main_config"]["collect_name"] == "new_review"


def test_from_files_config_dir_forces_legacy(isolated):
    legacy_dir = isolated / "legacy"
    _write(legacy_dir / "scilex.config.yml", LEGACY_FORMAT)
    _write(legacy_dir / "api.config.yml", {})
    _write(isolated / "scilex.yml", NEW_FORMAT)
    config = SciLExConfig.from_files(legacy_dir)
    assert config.main["collect_name"] == "old_review"


# ---------------------------------------------------------------------------
# New keys
# ---------------------------------------------------------------------------

NEW_KEYS = {
    **NEW_FORMAT,
    "search": {**NEW_FORMAT["search"], "since": "2024-03-01"},
    "citations": {"discrepancy_threshold": 0.3},
    "enrichment": {
        "recover_dois": True,
        "doi_recovery_min_similarity": 0.8,
        "unpaywall": True,
        "author_hindex": True,
    },
    "ranking": {"venue_ranking": True},
    "report": {"prisma": False},
    "llm_screening": {"enabled": True, "topic": "KG", "threshold": 3, "workers": 2},
}


def _load_main(isolated, data):
    _write(isolated / "scilex.yml", data)
    loaded = load_settings()
    return to_legacy(loaded.settings, loaded.keys)[0]


def test_new_keys_map_to_legacy_names(isolated):
    main = _load_main(isolated, NEW_KEYS)
    qf = main["quality_filters"]
    assert main["since"] == "2024-03-01"
    assert main["generate_prisma_report"] is False
    assert qf["canonical_citation_discrepancy_threshold"] == 0.3
    assert qf["recover_missing_dois"] is True
    assert qf["doi_recovery_min_similarity"] == 0.8
    assert qf["enrich_unpaywall"] is True
    assert qf["enrich_author_hindex"] is True
    assert qf["use_venue_ranking"] is True
    assert main["llm_screening"]["topic"] == "KG"
    assert main["llm_screening"]["workers"] == 2


def test_new_keys_roundtrip_through_migration(isolated):
    main = _load_main(isolated, NEW_KEYS)
    migrated = legacy_to_settings(main)
    assert migrated["search"]["since"] == "2024-03-01"
    assert migrated["citations"]["discrepancy_threshold"] == 0.3
    assert migrated["enrichment"]["recover_dois"] is True
    assert migrated["enrichment"]["unpaywall"] is True
    assert migrated["ranking"]["venue_ranking"] is True
    assert migrated["report"]["prisma"] is False
    assert migrated["llm_screening"] == {
        "enabled": True,
        "topic": "KG",
        "threshold": 3,
        "workers": 2,
    }
    assert _load_main(isolated, migrated) == main


def test_no_new_key_emitted_when_default(isolated):
    main = _load_main(isolated, NEW_FORMAT)
    qf = main["quality_filters"]
    for key in (
        "canonical_citation_discrepancy_threshold",
        "recover_missing_dois",
        "doi_recovery_min_similarity",
        "enrich_unpaywall",
        "enrich_author_hindex",
        "use_venue_ranking",
    ):
        assert key not in qf
    for key in ("since", "generate_prisma_report", "llm_screening"):
        assert key not in main


def test_since_accepts_yaml_date_and_rejects_garbage(isolated):
    (isolated / "scilex.yml").write_text(
        "name: x\nsearch: {keywords: [[a]], years: [2024], apis: [OpenAlex], "
        "since: 2024-03-01}\n"
    )
    assert load_settings().settings.search.since == "2024-03-01"
    _write(
        isolated / "scilex.yml",
        {**NEW_FORMAT, "search": {**NEW_FORMAT["search"], "since": "yesterday"}},
    )
    with pytest.raises(SettingsError, match="YYYY-MM-DD"):
        load_settings()


def test_key_formats_stay_valid(isolated):
    _write(isolated / "scilex.yml", NEW_FORMAT)
    _write(
        isolated / "keys.yml",
        {
            "SemanticScholar": {"api_key": ["k1", "k2"]},
            "Springer": {"api_key": {"meta_api_key": "m", "openaccess_api_key": "o"}},
            "Elsevier": {"api_key": "e", "inst_token": "t"},
            "openrouter": {"api_key": "sk"},
            "Unpaywall": {"email": "a@b.c"},
            "rate_limits": {"OpenAlex": 5},
        },
    )
    api = resolve_legacy_configs(keys_path=str(isolated / "keys.yml"))[1]
    assert api["SemanticScholar"]["api_key"] == ["k1", "k2"]
    assert api["Springer"]["api_key"]["meta_api_key"] == "m"
    assert api["Elsevier"]["inst_token"] == "t"
    assert api["openrouter"]["api_key"] == "sk"
    assert api["Unpaywall"]["email"] == "a@b.c"
    assert api["rate_limits"] == {"OpenAlex": 5}


def test_example_files_are_valid_and_match_defaults(isolated):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    (isolated / "scilex.yml").write_text((root / "scilex.yml.example").read_text())
    (isolated / "keys.yml").write_text((root / "keys.yml.example").read_text())
    main, api = resolve_legacy_configs(keys_path=str(isolated / "keys.yml"))
    # the example only restates defaults: no optional legacy key is emitted
    for key in ("since", "generate_prisma_report", "llm_screening", "vpn"):
        assert key not in main
    assert not {"recover_missing_dois", "use_venue_ranking"} & set(
        main["quality_filters"]
    )
    assert {"Zotero", "openrouter", "Unpaywall"} <= set(api)
