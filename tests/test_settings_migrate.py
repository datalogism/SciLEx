"""Tests for the legacy -> new format migration."""

from pathlib import Path

import yaml

import scilex
from scilex.config import SciLExConfig
from scilex.settings import (
    legacy_to_settings,
    load_settings,
    loader,
    migrate_files,
    to_legacy,
)

PACKAGE = Path(scilex.__file__).parent


def _legacy_dir(tmp_path: Path, advanced: str | None = None) -> Path:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "scilex.config.yml").write_text(
        (PACKAGE / "scilex.config.yml.example").read_text()
    )
    (legacy / "api.config.yml").write_text(
        (PACKAGE / "api.config.yml.example").read_text()
    )
    if advanced is not None:
        (legacy / "scilex.advanced.yml").write_text(advanced)
    return legacy


def _effective(quality_filters: dict) -> dict:
    """Drop lists that legacy consumers ignore when their feature flag is off."""
    result = dict(quality_filters)
    if not result["enable_itemtype_filter"]:
        result.pop("allowed_item_types")
    if not result["enable_itemtype_bypass"]:
        result.pop("bypass_item_types")
    return result


def _roundtrip(tmp_path, monkeypatch, legacy: Path):
    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", tmp_path / "none.yml")
    new_file = tmp_path / "scilex.yml"
    new_file.write_text(migrate_files(legacy))
    loaded = load_settings(config_path=new_file, keys_path=legacy / "api.config.yml")
    main, api = to_legacy(loaded.settings, loaded.keys)
    return main, api, SciLExConfig.from_files(legacy)


def test_examples_roundtrip(tmp_path, monkeypatch):
    main, api, expected = _roundtrip(tmp_path, monkeypatch, _legacy_dir(tmp_path))
    for key in (
        "collect_name",
        "keywords",
        "bonus_keywords",
        "years",
        "apis",
        "semantic_scholar_mode",
        "aggregate_get_citations",
        "pwc_enrichment",
    ):
        assert main[key] == expected.main[key], key
    assert _effective(main["quality_filters"]) == _effective(expected.quality_filters)
    assert api == expected.api
    assert "max_articles_per_query" not in main


def test_roundtrip_with_advanced(tmp_path, monkeypatch):
    advanced = """
collect: false
quality_filters:
  validate_abstracts: true
  min_abstract_quality_score: 75
  require_open_access: true
  enable_itemtype_bypass: false
  relevance_weights: {keywords: 0.35, quality: 0.20, itemtype: 0.15, citations: 0.30}
  itemtype_relevance_weights: {journalArticle: true, conferencePaper: true, bookSection: true, book: true, preprint: false}
"""
    legacy = _legacy_dir(tmp_path, advanced)
    main, _, expected = _roundtrip(tmp_path, monkeypatch, legacy)
    assert main["collect"] is False
    assert _effective(main["quality_filters"]) == _effective(expected.quality_filters)


def test_migrated_output_is_short(tmp_path):
    text = migrate_files(_legacy_dir(tmp_path))
    data = yaml.safe_load(text)
    assert data["name"] == "my_research_project"
    assert "min_authors" not in data.get("filters", {})
    assert len(text.splitlines()) < 30


def test_legacy_to_settings_omits_defaults():
    result = legacy_to_settings(
        {"collect_name": "x", "keywords": [["a"]], "years": [2024], "apis": ["Arxiv"]}
    )
    assert result == {
        "name": "x",
        "search": {"keywords": [["a"]], "years": [2024], "apis": ["Arxiv"]},
        "enrichment": {"paperswithcode": True},
    }


def test_legacy_hf_and_pwc_blocks_map_to_paperswithcode():
    base = {
        "collect_name": "x",
        "keywords": [["a"]],
        "years": [2024],
        "apis": ["Arxiv"],
    }
    for key in ("hf_enrichment", "pwc_enrichment"):
        result = legacy_to_settings(
            {**base, key: {"enabled": True, "use_papers_api": False, "workers": 8}}
        )
        assert result["enrichment"]["paperswithcode"] == {
            "enabled": True,
            "workers": 8,
        }
