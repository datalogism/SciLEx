"""Tests for scilex.crawlers.collectors.base module.

Uses __new__ to bypass __init__ and avoid filesystem/HTTP side effects.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.crawlers.circuit_breaker import CircuitBreakerOpenError
from scilex.crawlers.collectors.base import API_collector
from scilex.crawlers.collectors.elsevier import Elsevier_collector
from scilex.crawlers.collectors.ieee import IEEE_collector
from scilex.crawlers.collectors.springer import Springer_collector


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _make_collector(api_name="TestAPI", tmp_path=None, collector_class=API_collector):
    """Instantiate a collector without __init__ filesystem/HTTP side effects."""
    collector = collector_class.__new__(collector_class)
    collector.api_name = api_name
    collector.api_key = "test-key"
    collector.rate_limit = 0  # Disable rate limiting
    collector._last_call_time = 0.0
    collector.session = MagicMock()
    collector._result_buffer = []
    collector._buffer_size = 10
    collector.collectId = 0
    if tmp_path is not None:
        collector.datadir = str(tmp_path)
    return collector


def _make_http_error(status_code, headers=None):
    """Build a requests.HTTPError with the given status code."""
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    error = requests.exceptions.HTTPError(response=mock_response)
    mock_response.raise_for_status.side_effect = error
    return mock_response, error


def _make_mock_cb(available=True):
    """Build a mock circuit breaker registry + breaker pair."""
    mock_breaker = MagicMock()
    mock_breaker.is_available.return_value = available
    mock_breaker.timeout_seconds = 60
    mock_registry = MagicMock()
    mock_registry.get_breaker.return_value = mock_breaker
    return mock_registry, mock_breaker


# -------------------------------------------------------------------------
# TestSanitizeUrl
# -------------------------------------------------------------------------
class TestSanitizeUrl:
    def test_api_key_mixed_case_redacted(self):
        url = "https://api.example.com/search?q=test&apiKey=SECRET123"
        result = API_collector._sanitize_url(url)
        assert "SECRET123" not in result
        assert "***REDACTED***" in result

    def test_apikey_lowercase_redacted(self):
        url = "https://api.example.com/search?apikey=mysecret&format=json"
        result = API_collector._sanitize_url(url)
        assert "mysecret" not in result
        assert "***REDACTED***" in result

    def test_api_key_with_underscore_redacted(self):
        url = "https://api.example.com/data?api_key=abc123&limit=10"
        result = API_collector._sanitize_url(url)
        assert "abc123" not in result
        assert "***REDACTED***" in result

    def test_key_param_redacted(self):
        url = "https://api.example.com/v1/search?key=topsecret&q=ml"
        result = API_collector._sanitize_url(url)
        assert "topsecret" not in result
        assert "***REDACTED***" in result

    def test_token_param_redacted(self):
        url = "https://api.example.com/data?token=mytoken&page=1"
        result = API_collector._sanitize_url(url)
        assert "mytoken" not in result
        assert "***REDACTED***" in result

    def test_clean_url_unchanged(self):
        url = "https://api.example.com/search?q=knowledge+graph&limit=20"
        result = API_collector._sanitize_url(url)
        assert result == url

    def test_multiple_params_all_redacted(self):
        url = "https://api.example.com/?apiKey=k1&token=t1&q=test"
        result = API_collector._sanitize_url(url)
        assert "k1" not in result
        assert "t1" not in result

    def test_non_sensitive_params_preserved(self):
        url = "https://api.example.com/?apiKey=secret&q=graph&format=json"
        result = API_collector._sanitize_url(url)
        assert "q=graph" in result
        assert "format=json" in result


# -------------------------------------------------------------------------
# TestGetAuthRecoveryActions
# -------------------------------------------------------------------------
class TestGetAuthRecoveryActions:
    def test_401_mentions_api_key(self):
        collector = _make_collector("TestAPI")
        result = collector._get_auth_recovery_actions(401)
        assert "API key" in result or "api.config.yml" in result

    def test_403_mentions_permissions(self):
        collector = _make_collector("TestAPI")
        result = collector._get_auth_recovery_actions(403)
        assert "permissions" in result or "whitelist" in result

    def test_403_elsevier_specific_guidance(self):
        collector = _make_collector("Elsevier", collector_class=Elsevier_collector)
        result = collector._get_auth_recovery_actions(403)
        assert "Elsevier" in result
        assert "inst_token" in result

    def test_403_ieee_specific_guidance(self):
        collector = _make_collector("IEEE", collector_class=IEEE_collector)
        result = collector._get_auth_recovery_actions(403)
        assert "IEEE" in result

    def test_403_springer_specific_guidance(self):
        collector = _make_collector("Springer", collector_class=Springer_collector)
        result = collector._get_auth_recovery_actions(403)
        assert "Springer" in result

    def test_result_is_string(self):
        collector = _make_collector("TestAPI")
        result = collector._get_auth_recovery_actions(401)
        assert isinstance(result, str)


# -------------------------------------------------------------------------
# TestSavePageResultsAndBuffer
# -------------------------------------------------------------------------
class TestSavePageResultsAndBuffer:
    def test_buffer_accumulates_without_flush(self, tmp_path):
        collector = _make_collector(tmp_path=tmp_path)
        collector._buffer_size = 10
        collector.savePageResults({"key": "value"}, page=1)
        assert len(collector._result_buffer) == 1
        # No files written yet
        assert not list(tmp_path.rglob("page_*"))

    def test_flush_triggered_at_buffer_size(self, tmp_path):
        collector = _make_collector(tmp_path=tmp_path)
        collector._buffer_size = 3
        for i in range(3):
            collector.savePageResults({"page": i}, page=i)
        # Buffer should be empty after flush
        assert len(collector._result_buffer) == 0
        # Files should exist
        collect_dir = tmp_path / "TestAPI" / "0"
        files = list(collect_dir.glob("page_*"))
        assert len(files) == 3

    def test_close_session_flushes_remainder(self, tmp_path):
        collector = _make_collector(tmp_path=tmp_path)
        collector._buffer_size = 10
        collector.savePageResults({"data": "test"}, page=5)
        collector.close_session()
        # Buffer cleared after close
        assert len(collector._result_buffer) == 0
        collect_dir = tmp_path / "TestAPI" / "0"
        assert (collect_dir / "page_5").exists()

    def test_flush_writes_valid_json(self, tmp_path):
        collector = _make_collector(tmp_path=tmp_path)
        collector._buffer_size = 1
        data = {"results": [1, 2, 3], "count": 3}
        collector.savePageResults(data, page=0)
        collect_dir = tmp_path / "TestAPI" / "0"
        written = json.loads((collect_dir / "page_0").read_text())
        assert written == data

    def test_flush_empty_buffer_no_error(self, tmp_path):
        collector = _make_collector(tmp_path=tmp_path)
        # Should not raise
        collector._flush_buffer()


# -------------------------------------------------------------------------
# TestApiCallDecoratorErrorPaths
# -------------------------------------------------------------------------
class TestApiCallDecoratorErrorPaths:
    """Tests for api_call_decorator retry/circuit breaker behavior."""

    URL = "https://api.example.com/search"

    def _call(self, collector, mock_registry, **kwargs):
        with patch(
            "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
            return_value=mock_registry,
        ):
            return collector.api_call_decorator(self.URL, **kwargs)

    def test_circuit_breaker_open_raises(self):
        collector = _make_collector()
        mock_registry, _ = _make_mock_cb(available=False)
        with pytest.raises(CircuitBreakerOpenError):
            self._call(collector, mock_registry)

    def test_success_calls_record_success(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        collector.session.get.return_value = mock_response

        result = self._call(collector, mock_registry)
        assert result is mock_response
        mock_breaker.record_success.assert_called_once()

    def test_401_no_retry_raises(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(401)
        collector.session.get.side_effect = error

        with pytest.raises(requests.exceptions.HTTPError):
            self._call(collector, mock_registry)

        # No retry and NO circuit-breaker failure: auth errors are permanent config
        # failures, not transient endpoint failures
        assert collector.session.get.call_count == 1
        mock_breaker.record_failure.assert_not_called()

    def test_403_no_retry_raises(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(403)
        collector.session.get.side_effect = error

        with pytest.raises(requests.exceptions.HTTPError):
            self._call(collector, mock_registry)

        assert collector.session.get.call_count == 1
        mock_breaker.record_failure.assert_not_called()

    def test_500_retries_max_retries_times(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(500)
        collector.session.get.side_effect = error

        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch("scilex.crawlers.collectors.base.time.sleep"),
            pytest.raises(requests.exceptions.HTTPError),
        ):
            collector.api_call_decorator(self.URL, max_retries=3)

        assert collector.session.get.call_count == 3
        # Exactly one breaker failure per exhausted call (not one per attempt)
        mock_breaker.record_failure.assert_called_once()

    def test_500_then_200_succeeds(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(500)
        mock_success = MagicMock()
        mock_success.raise_for_status.return_value = None
        collector.session.get.side_effect = [error, mock_success]

        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch("scilex.crawlers.collectors.base.time.sleep"),
        ):
            result = collector.api_call_decorator(self.URL, max_retries=3)

        assert result is mock_success
        mock_breaker.record_success.assert_called_once()

    def test_timeout_retries_then_raises(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        collector.session.get.side_effect = requests.exceptions.Timeout("timeout")

        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch("scilex.crawlers.collectors.base.time.sleep"),
            pytest.raises(requests.exceptions.Timeout),
        ):
            collector.api_call_decorator(self.URL, max_retries=3)

        assert collector.session.get.call_count == 3
        mock_breaker.record_failure.assert_called_once()

    def test_429_with_retry_after_header_uses_header(self):
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(429, headers={"Retry-After": "45"})
        mock_success = MagicMock()
        mock_success.raise_for_status.return_value = None
        collector.session.get.side_effect = [error, mock_success]

        sleep_calls = []
        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch(
                "scilex.crawlers.collectors.base.time.sleep",
                side_effect=lambda t: sleep_calls.append(t),
            ),
        ):
            result = collector.api_call_decorator(self.URL, max_retries=3)

        assert result is mock_success
        # Should have slept for 45 seconds (from Retry-After header)
        assert any(s == 45 for s in sleep_calls)

    def test_429_with_non_numeric_retry_after_falls_back(self):
        """Non-numeric Retry-After header should not crash; falls back to default."""
        collector = _make_collector()
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(429, headers={"Retry-After": "invalid"})
        mock_success = MagicMock()
        mock_success.raise_for_status.return_value = None
        collector.session.get.side_effect = [error, mock_success]

        sleep_calls = []
        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch(
                "scilex.crawlers.collectors.base.time.sleep",
                side_effect=lambda t: sleep_calls.append(t),
            ),
        ):
            result = collector.api_call_decorator(self.URL, max_retries=3)

        # Must succeed and have slept (not crashed on invalid header)
        assert result is mock_success
        assert len(sleep_calls) > 0

    def test_429_without_retry_after_uses_api_specific_backoff(self):
        """DBLP uses fixed 30s backoff (no exponential)."""
        collector = _make_collector("DBLP")
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(429)
        mock_success = MagicMock()
        mock_success.raise_for_status.return_value = None
        collector.session.get.side_effect = [error, mock_success]

        sleep_calls = []
        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch(
                "scilex.crawlers.collectors.base.time.sleep",
                side_effect=lambda t: sleep_calls.append(t),
            ),
        ):
            result = collector.api_call_decorator(self.URL, max_retries=3)

        assert result is mock_success
        # DBLP uses fixed 30s wait
        assert any(s == 30 for s in sleep_calls)

    def _run_exhausted(self, status, headers=None, api_name="TestAPI"):
        collector = _make_collector(api_name)
        mock_registry, mock_breaker = _make_mock_cb()
        _, error = _make_http_error(status, headers=headers)
        collector.session.get.side_effect = error
        sleeps = []
        with (
            patch(
                "scilex.crawlers.collectors.base.CircuitBreakerRegistry",
                return_value=mock_registry,
            ),
            patch(
                "scilex.crawlers.collectors.base.time.sleep",
                side_effect=sleeps.append,
            ),
            # Keep the process-wide limiter untouched (on_throttle adds delay)
            patch(
                "scilex.crawlers.collectors.base.AdaptiveRateLimiterRegistry"
            ) as mock_limiters,
            pytest.raises(requests.exceptions.HTTPError),
        ):
            mock_limiters.return_value.get.return_value.on_throttle.return_value = 10.0
            collector.api_call_decorator(self.URL, max_retries=3)
        return collector, mock_breaker, sleeps

    def test_429_exhausted_records_exactly_one_failure(self):
        collector, breaker, _ = self._run_exhausted(429)
        assert collector.session.get.call_count == 3
        breaker.record_failure.assert_called_once()

    def test_503_exhausted_records_exactly_one_failure(self):
        collector, breaker, _ = self._run_exhausted(503)
        assert collector.session.get.call_count == 3
        breaker.record_failure.assert_called_once()

    def test_non_retryable_4xx_not_retried_one_failure(self):
        collector, breaker, sleeps = self._run_exhausted(404)
        assert collector.session.get.call_count == 1
        assert sleeps == []
        breaker.record_failure.assert_called_once()

    def test_retry_after_is_capped(self):
        _, _, sleeps = self._run_exhausted(429, headers={"Retry-After": "300"})
        assert sleeps
        assert max(sleeps) <= 120

    def test_quota_exhausted_retry_after_gives_up_at_once(self):
        # A Retry-After beyond 10 min means quota exhaustion: no pointless
        # retries, so the caller can rotate the VPN IP immediately.
        collector, breaker, sleeps = self._run_exhausted(
            429, headers={"Retry-After": "86400"}
        )
        assert collector.session.get.call_count == 1
        assert sleeps == []
        breaker.record_failure.assert_called_once()


class TestLogApiUsageHeaders:
    def test_non_numeric_remaining_header_does_not_crash(self):
        collector = _make_collector()
        response = MagicMock()
        response.status_code = 200
        response.elapsed.total_seconds.return_value = 0.1
        response.headers = {"X-RateLimit-Remaining": "n/a"}
        collector.log_api_usage(response, 1, 5)  # must not raise
