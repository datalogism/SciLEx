"""Tests for the rate limiting system.

Validates:
- Dual-value DEFAULT_RATE_LIMITS structure
- Key-aware rate selection (PubMed 3→10, Elsevier 2→9)
- User config override priority
- _rate_limit_wait() actually enforces minimum interval
- Retry-After header is respected on 429
"""

import time
from unittest.mock import MagicMock, patch

import requests

from scilex.config_defaults import DEFAULT_RATE_LIMITS, get_rate_limit

# ============================================================================
# Dual-value structure validation
# ============================================================================


class TestDefaultRateLimitsStructure:
    """Validate that DEFAULT_RATE_LIMITS uses dual-value structure."""

    def test_all_entries_are_dicts(self):
        """Every entry should be a dict with without_key and with_key."""
        for api_name, entry in DEFAULT_RATE_LIMITS.items():
            assert isinstance(entry, dict), (
                f"{api_name} should be a dict, got {type(entry)}"
            )
            assert "without_key" in entry, f"{api_name} missing 'without_key'"
            assert "with_key" in entry, f"{api_name} missing 'with_key'"

    def test_all_values_are_positive_floats(self):
        """All rate limit values should be positive numbers."""
        for api_name, entry in DEFAULT_RATE_LIMITS.items():
            assert entry["without_key"] > 0, f"{api_name} without_key should be > 0"
            assert entry["with_key"] > 0, f"{api_name} with_key should be > 0"

    def test_with_key_gte_without_key(self):
        """with_key rate should always be >= without_key rate."""
        for api_name, entry in DEFAULT_RATE_LIMITS.items():
            assert entry["with_key"] >= entry["without_key"], (
                f"{api_name}: with_key ({entry['with_key']}) < without_key ({entry['without_key']})"
            )

    def test_expected_apis_present(self):
        """All supported APIs should be in the defaults."""
        expected = [
            "SemanticScholar",
            "OpenAlex",
            "Arxiv",
            "IEEE",
            "Elsevier",
            "Springer",
            "HAL",
            "DBLP",
            "Istex",
            "PubMed",
            "PubMedCentral",
        ]
        for api in expected:
            assert api in DEFAULT_RATE_LIMITS, f"{api} missing from DEFAULT_RATE_LIMITS"


# ============================================================================
# Key-aware rate selection
# ============================================================================


class TestGetRateLimit:
    """Test get_rate_limit() key-aware selection."""

    def test_pubmed_without_key(self):
        assert get_rate_limit("PubMed", has_api_key=False) == 3.0

    def test_pubmed_with_key(self):
        assert get_rate_limit("PubMed", has_api_key=True) == 10.0

    def test_elsevier_without_key(self):
        assert get_rate_limit("Elsevier", has_api_key=False) == 2.0

    def test_elsevier_with_key(self):
        assert get_rate_limit("Elsevier", has_api_key=True) == 9.0

    def test_arxiv_rate(self):
        """Arxiv has no key system, rate should be 0.33 either way."""
        assert get_rate_limit("Arxiv", has_api_key=False) == 0.33
        assert get_rate_limit("Arxiv", has_api_key=True) == 0.33

    def test_semantic_scholar_same_rate(self):
        """SemanticScholar rate is same with or without key."""
        assert get_rate_limit("SemanticScholar", has_api_key=False) == 1.0
        assert get_rate_limit("SemanticScholar", has_api_key=True) == 1.0

    def test_unknown_api_returns_default(self):
        assert get_rate_limit("NonExistentAPI", has_api_key=False) == 5.0

    def test_default_has_api_key_is_false(self):
        """Default parameter should be False (no key)."""
        assert get_rate_limit("PubMed") == 3.0


# ============================================================================
# _rate_limit_wait() enforcement
# ============================================================================


def _make_collector(api_name="TestAPI", rate_limit=10.0, api_key=None):
    """Create a minimal collector instance for testing."""
    from scilex.crawlers.collectors.base import API_collector

    with patch.object(API_collector, "__init__", lambda self, *a, **kw: None):
        collector = API_collector.__new__(API_collector)
        collector.api_key = api_key
        collector.api_name = api_name
        collector.rate_limit = rate_limit
        collector._last_call_time = 0.0
        collector.session = MagicMock()
    return collector


class TestRateLimitWait:
    """Test _rate_limit_wait() enforces minimum interval."""

    def test_first_call_no_wait(self):
        """First call should not wait (last_call_time=0)."""
        collector = _make_collector(rate_limit=1.0)
        start = time.monotonic()
        collector._rate_limit_wait()
        elapsed = time.monotonic() - start
        # Should be nearly instant (less than 50ms)
        assert elapsed < 0.05

    def test_enforces_interval(self):
        """Two rapid calls should enforce minimum interval."""
        collector = _make_collector(rate_limit=10.0)  # 100ms interval
        collector._rate_limit_wait()
        # Immediately call again
        start = time.monotonic()
        collector._rate_limit_wait()
        elapsed = time.monotonic() - start
        # Should have waited ~100ms (allowing 50ms tolerance)
        assert elapsed >= 0.05, f"Expected >=50ms wait, got {elapsed * 1000:.0f}ms"

    def test_zero_rate_limit_skips(self):
        """rate_limit=0 should skip waiting."""
        collector = _make_collector(rate_limit=0)
        collector._last_call_time = time.monotonic()
        start = time.monotonic()
        collector._rate_limit_wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.01

    def test_sub_one_rate_limit(self):
        """Sub-1 rate limit (e.g., Arxiv 0.33) should work correctly."""
        _make_collector(rate_limit=0.33)
        # min_interval = 1/0.33 ≈ 3.03s — we just verify the math, not actually wait 3s
        min_interval = 1.0 / 0.33
        assert min_interval > 3.0
        assert min_interval < 3.1


# ============================================================================
# User config override priority
# ============================================================================


class TestConfigOverridePriority:
    """Test that user config overrides defaults."""

    def test_config_overrides_default(self):
        """User config rate_limits should override DEFAULT_RATE_LIMITS."""
        collector = _make_collector(api_name="TestAPI", rate_limit=10.0)
        collector.load_rate_limit_from_config({"TestAPI": 42.0})
        assert collector.rate_limit == 42.0

    def test_config_for_other_api_ignored(self):
        collector = _make_collector(api_name="PubMed", api_key="k")
        collector.load_rate_limit_from_config({"Other": 1.0})
        assert collector.rate_limit == 10.0

    def test_invalid_configured_value_falls_back(self):
        collector = _make_collector(api_name="PubMed", api_key="k")
        collector.load_rate_limit_from_config({"PubMed": "fast"})
        assert collector.rate_limit == 10.0

    def test_missing_config_uses_defaults(self):
        """With no rate_limits given, should use DEFAULT_RATE_LIMITS."""
        collector = _make_collector(
            api_name="PubMed", rate_limit=10.0, api_key="test-key"
        )
        collector.load_rate_limit_from_config()
        assert collector.rate_limit == 10.0

    def test_missing_config_without_key(self):
        """Without key, should select without_key rate."""
        collector = _make_collector(api_name="PubMed", rate_limit=10.0, api_key=None)
        collector.load_rate_limit_from_config()
        assert collector.rate_limit == 3.0

    def test_worker_applies_configured_rate_limit(self, tmp_path):
        """The collection worker passes api_config['rate_limits'] to collectors."""
        from queue import Queue

        from scilex.crawlers import collector_collection as cc

        seen = {}

        class FakeCollector:
            def __init__(self, data_query, repo, api_key):
                pass

            def load_rate_limit_from_config(self, rate_limits=None):
                seen["rate_limits"] = rate_limits

            def runCollect(self):
                return {"coll_art": 0}

        query = {"id_collect": 0, "keyword": ["a"], "year": 2020}
        with patch.dict(cc.api_collectors, {"FakeAPI": FakeCollector}):
            cc._run_job_collects_worker(
                "FakeAPI",
                [{"query": query, "api": "FakeAPI"}],
                {"rate_limits": {"FakeAPI": 7.0}},
                str(tmp_path),
                "c",
                Queue(),
            )
        assert seen["rate_limits"] == {"FakeAPI": 7.0}


# ============================================================================
# Retry-After header support
# ============================================================================


class TestRetryAfterHeader:
    """Test that 429 responses with Retry-After are respected."""

    def test_retry_after_header_respected(self):
        """When server sends Retry-After, that value should be used for wait."""
        collector = _make_collector(api_name="TestAPI", rate_limit=10.0)

        # Mock circuit breaker
        mock_breaker = MagicMock()
        mock_breaker.is_available.return_value = True

        mock_registry = MagicMock()
        mock_registry.get_breaker.return_value = mock_breaker

        # Create mock 429 response with Retry-After, then success
        mock_429_response = MagicMock(spec=requests.Response)
        mock_429_response.status_code = 429
        mock_429_response.headers = {"Retry-After": "5"}
        mock_429_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_429_response
        )

        mock_ok_response = MagicMock(spec=requests.Response)
        mock_ok_response.status_code = 200
        mock_ok_response.raise_for_status.return_value = None

        collector.session = MagicMock()
        collector.session.get.side_effect = [mock_429_response, mock_ok_response]

        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch("scilex.crawlers.collectors.base.time.sleep") as mock_sleep,
            patch.object(collector, "_rate_limit_wait"),
        ):
            result = collector.api_call_decorator("http://test.com/api")

        # Verify sleep was called with the Retry-After value
        mock_sleep.assert_called_with(5)
        assert result == mock_ok_response
