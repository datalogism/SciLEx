"""Tests for scilex.config_defaults module."""

import pytest

from scilex.config_defaults import (
    DEFAULT_RELEVANCE_WEIGHTS,
    QUALITY_FILTER_SCHEMA,
    get_default_quality_filters,
    get_rate_limit,
)


# -------------------------------------------------------------------------
# TestGetDefaultQualityFilters
# -------------------------------------------------------------------------
class TestGetDefaultQualityFilters:
    def test_all_schema_keys_present(self):
        defaults = get_default_quality_filters()
        for key in QUALITY_FILTER_SCHEMA:
            assert key in defaults, f"Missing key: {key}"

    def test_require_abstract_default_true(self):
        defaults = get_default_quality_filters()
        assert defaults["require_abstract"] is True

    def test_require_doi_default_false(self):
        defaults = get_default_quality_filters()
        assert defaults["require_doi"] is False

    def test_validate_abstracts_default_false(self):
        defaults = get_default_quality_filters()
        assert defaults["validate_abstracts"] is False

    def test_relevance_weights_is_dict(self):
        defaults = get_default_quality_filters()
        assert isinstance(defaults["relevance_weights"], dict)

    def test_returns_new_dict_each_call(self):
        d1 = get_default_quality_filters()
        d2 = get_default_quality_filters()
        d1["require_abstract"] = False
        assert d2["require_abstract"] is True

    def test_nested_dict_not_shared_between_calls(self):
        """Mutating a nested dict in one call's return value must not affect another."""
        d1 = get_default_quality_filters()
        d2 = get_default_quality_filters()
        original = d2["relevance_weights"].copy()
        first_key = next(iter(d1["relevance_weights"]))
        d1["relevance_weights"][first_key] = 0.0
        assert d2["relevance_weights"][first_key] == original[first_key]


# -------------------------------------------------------------------------
# TestDefaultRelevanceWeights
# -------------------------------------------------------------------------
class TestDefaultRelevanceWeights:
    def test_weights_sum_to_one(self):
        total = sum(DEFAULT_RELEVANCE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_keywords_weight_dominant(self):
        assert (
            DEFAULT_RELEVANCE_WEIGHTS["keywords"]
            > DEFAULT_RELEVANCE_WEIGHTS["citations"]
        )

    def test_all_weights_positive(self):
        for key, val in DEFAULT_RELEVANCE_WEIGHTS.items():
            assert val > 0, f"Weight for '{key}' is not positive"


# -------------------------------------------------------------------------
# TestGetRateLimit
# -------------------------------------------------------------------------
class TestGetRateLimit:
    def test_crossref_with_key_faster(self):
        without = get_rate_limit("Crossref", has_api_key=False)
        with_key = get_rate_limit("Crossref", has_api_key=True)
        assert with_key > without

    def test_hal_symmetric(self):
        without = get_rate_limit("HAL", has_api_key=False)
        with_key = get_rate_limit("HAL", has_api_key=True)
        assert without == with_key

    def test_istex_symmetric(self):
        without = get_rate_limit("Istex", has_api_key=False)
        with_key = get_rate_limit("Istex", has_api_key=True)
        assert without == with_key

    def test_unknown_api_returns_five(self):
        assert get_rate_limit("UnknownAPI") == 5.0

    def test_returns_float(self):
        result = get_rate_limit("SemanticScholar")
        assert isinstance(result, float)

    @pytest.mark.parametrize(
        "api", ["SemanticScholar", "OpenAlex", "IEEE", "Springer", "HAL"]
    )
    def test_known_apis_return_positive(self, api):
        assert get_rate_limit(api) > 0
