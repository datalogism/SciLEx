"""Regression tests for the legacy to ``scilex.yml`` migration."""

import logging

import pytest
import yaml

from scilex.settings.loader import to_legacy
from scilex.settings.migrate import legacy_to_settings
from scilex.settings.schema import ScilexSettings

BASE = {
    "collect_name": "x",
    "keywords": [["a"], ["b"]],
    "years": [2020, 2021],
    "apis": ["OpenAlex"],
}


def _migrate_and_load(**overrides):
    """Migrate a legacy dict, dump it as YAML, and load it back."""
    new_format = legacy_to_settings({**BASE, **overrides})
    reloaded = yaml.safe_load(yaml.safe_dump(new_format))
    settings = ScilexSettings.model_validate(reloaded)
    return new_format, settings, to_legacy(settings)[0]


@pytest.mark.parametrize("value", [0, -1])
def test_unlimited_max_papers_becomes_none(value):
    _, settings, legacy = _migrate_and_load(quality_filters={"max_papers": value})
    assert settings.ranking.max_papers is None
    assert legacy["quality_filters"]["max_papers"] is None


def test_trailing_empty_keyword_groups_are_dropped():
    new_format, settings, _ = _migrate_and_load(keywords=[["a"], []])
    assert new_format["search"]["keywords"] == [["a"]]
    assert settings.search.keywords == [["a"]]


def test_llm_screening_unknown_key_is_reported(caplog):
    with caplog.at_level(logging.WARNING):
        _, settings, _ = _migrate_and_load(
            llm_screening={"enabled": True, "topic": "t", "foo": 1}
        )
    assert "llm_screening.foo" in caplog.text
    assert settings.llm_screening.topic == "t"


def test_llm_screening_enabled_without_topic_is_reported(caplog):
    with caplog.at_level(logging.WARNING):
        _, settings, _ = _migrate_and_load(llm_screening={"enabled": True})
    assert "without a topic" in caplog.text
    assert settings.llm_screening.enabled is False


def test_each_ignored_legacy_key_is_logged_with_its_name(caplog):
    with caplog.at_level(logging.WARNING):
        _migrate_and_load(
            enable_text_filter=True,
            another_unknown="x",
            quality_filters={"enable_text_filter": False, "mystery": 1},
            pwc_enrichment={"enabled": True, "weird": 2},
        )
    messages = [record.getMessage() for record in caplog.records]
    for name in (
        "'enable_text_filter'",
        "'another_unknown'",
        "quality_filters.enable_text_filter",
        "quality_filters.mystery",
        "pwc_enrichment.weird",
    ):
        assert any(name in message for message in messages), name


def test_known_legacy_keys_do_not_warn(caplog):
    with caplog.at_level(logging.WARNING):
        _migrate_and_load(
            quality_filters={"max_papers": 10, "require_doi": True},
            pwc_enrichment={"enabled": True},
            output_dir="out",
        )
    assert caplog.text == ""


def test_empty_allowed_item_types_with_filter_on_migrates_to_all(caplog):
    with caplog.at_level(logging.WARNING):
        _, settings, _ = _migrate_and_load(
            quality_filters={"enable_itemtype_filter": True, "allowed_item_types": []}
        )
    assert settings.filters.item_types is None
    assert "allowed_item_types is empty" in caplog.text


def test_unknown_relevance_weight_is_reported_and_dropped(caplog):
    with caplog.at_level(logging.WARNING):
        _, settings, _ = _migrate_and_load(
            quality_filters={"relevance_weights": {"keywords": 0.5, "foo": 1}}
        )
    assert "relevance_weights.foo" in caplog.text
    assert settings.ranking.weights == {"keywords": 0.5}


@pytest.mark.parametrize(
    "overrides",
    [
        {"quality_filters": {"max_papers": 0}},
        {"keywords": [["a"], []]},
        {"llm_screening": {"enabled": True, "topic": "t", "foo": 1}},
        {"enable_text_filter": True, "quality_filters": {"enable_text_filter": 1}},
        {"quality_filters": {"enable_itemtype_filter": True, "allowed_item_types": []}},
    ],
)
def test_migrated_valid_legacy_file_always_loads(overrides):
    _migrate_and_load(**overrides)
