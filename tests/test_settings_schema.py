"""Tests for scilex.settings schema, presets and error formatting."""

import pytest
from pydantic import ValidationError

from scilex.config import SciLExConfig
from scilex.config_defaults import get_default_quality_filters
from scilex.settings import ScilexSettings, SettingsError, to_legacy
from scilex.settings.schema import format_validation_error

MINIMAL = {
    "name": "review",
    "search": {"keywords": [["a", "b"]], "years": [2024], "apis": ["OpenAlex"]},
}


def _validate(raw):
    try:
        return ScilexSettings.model_validate(raw)
    except ValidationError as exc:
        raise SettingsError(format_validation_error(exc, raw)) from exc


def test_minimal_valid():
    settings = _validate(MINIMAL)
    assert settings.search.years == [2024]
    assert settings.filters.require == ["abstract", "year"]


def test_full_file():
    raw = {
        **MINIMAL,
        "output_dir": "out",
        "preset": "literature_review",
        "filters": {
            "item_types": ["journalArticle"],
            "always_keep": [],
            "require": ["abstract", "doi"],
            "min_authors": 1,
            "abstract_words": [10, 500],
            "abstract_quality": 70,
            "check_year_range": False,
            "citations": False,
        },
        "citations": {"fetch": False, "fallbacks": ["openalex"]},
        "ranking": {"enabled": True, "max_papers": None, "weights": {"keywords": 0.5}},
        "enrichment": {"paperswithcode": {"enabled": True, "cache_ttl_days": 5}},
        "report": {"quality_report": False, "track_duplicates": False},
        "collect": {"enabled": False, "vpn": {"enabled": True}},
    }
    settings = _validate(raw)
    assert settings.enrichment.paperswithcode.cache_ttl_days == 5
    assert settings.collect.vpn == {"enabled": True}


def test_years_range_string():
    raw = {**MINIMAL, "search": {**MINIMAL["search"], "years": "2022-2024"}}
    assert _validate(raw).search.years == [2022, 2023, 2024]


def test_flat_keywords_is_one_group():
    raw = {**MINIMAL, "search": {**MINIMAL["search"], "keywords": ["a", "b"]}}
    assert _validate(raw).search.keywords == [["a", "b"]]


def test_three_groups_rejected():
    raw = {
        **MINIMAL,
        "search": {**MINIMAL["search"], "keywords": [["a"], ["b"], ["c"]]},
    }
    with pytest.raises(SettingsError, match="search.keywords"):
        _validate(raw)


def test_unknown_key_suggestion():
    raw = {**MINIMAL, "filters": {"max_paper": 5}}
    with pytest.raises(SettingsError) as info:
        _validate(raw)
    assert "filters.max_paper: unknown key. Did you mean ranking.max_papers?" in str(
        info.value
    )


def test_wrong_type_message():
    raw = {**MINIMAL, "ranking": {"max_papers": "lots"}}
    with pytest.raises(SettingsError) as info:
        _validate(raw)
    assert "ranking.max_papers:" in str(info.value)
    assert "(got: 'lots')" in str(info.value)


def test_require_subset_and_words_order():
    with pytest.raises(SettingsError, match="filters.require"):
        _validate({**MINIMAL, "filters": {"require": ["title"]}})
    with pytest.raises(SettingsError, match="filters.abstract_words"):
        _validate({**MINIMAL, "filters": {"abstract_words": [500, 10]}})


def test_paperswithcode_bool_shorthand():
    raw = {**MINIMAL, "enrichment": {"paperswithcode": True}}
    assert _validate(raw).enrichment.paperswithcode.enabled is True


def test_no_preset_invariant():
    main, _ = to_legacy(_validate(MINIMAL))
    assert main["quality_filters"] == get_default_quality_filters()
    assert main["quality_filters"] == SciLExConfig.from_dicts(main).quality_filters


def test_deprecated_huggingface_key_is_translated_with_warning(caplog):
    raw = {
        **MINIMAL,
        "enrichment": {"huggingface": {"enabled": True, "use_papers_api": False}},
    }
    with caplog.at_level("WARNING"):
        settings = _validate(raw)
    assert settings.enrichment.paperswithcode.enabled is True
    assert "deprecated" in caplog.text


def test_deprecated_huggingface_bool_is_translated():
    settings = _validate({**MINIMAL, "enrichment": {"huggingface": True}})
    assert settings.enrichment.paperswithcode.enabled is True


def test_huggingface_and_paperswithcode_together_is_an_error():
    raw = {**MINIMAL, "enrichment": {"huggingface": True, "paperswithcode": True}}
    with pytest.raises(SettingsError, match="both set"):
        _validate(raw)


def test_to_legacy_emits_pwc_enrichment():
    main, _ = to_legacy(_validate({**MINIMAL, "enrichment": {"paperswithcode": True}}))
    assert main["pwc_enrichment"]["enabled"] is True
    assert "hf_enrichment" not in main
