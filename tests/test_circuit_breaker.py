"""Tests for scilex.crawlers.circuit_breaker module."""

from datetime import datetime, timedelta
from unittest.mock import patch

from scilex.crawlers.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)


# -------------------------------------------------------------------------
# CircuitState enum
# -------------------------------------------------------------------------
class TestCircuitState:
    def test_closed_value(self):
        assert CircuitState.CLOSED.value == "closed"

    def test_open_value(self):
        assert CircuitState.OPEN.value == "open"

    def test_half_open_value(self):
        assert CircuitState.HALF_OPEN.value == "half_open"


# -------------------------------------------------------------------------
# CircuitBreaker
# -------------------------------------------------------------------------
class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_is_zero(self):
        cb = CircuitBreaker(name="test")
        assert cb.failure_count == 0

    def test_is_available_when_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.is_available() is True

    def test_record_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=5, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_blocks_requests(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_available() is False

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate timeout expiry by patching datetime.now
        future_time = datetime.now() + timedelta(seconds=61)
        with patch("scilex.crawlers.circuit_breaker.datetime") as mock_dt:
            mock_dt.now.return_value = future_time
            assert cb.is_available() is True
            assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60, name="test")
        cb.record_failure()
        cb.record_failure()

        # Force to half-open
        future_time = datetime.now() + timedelta(seconds=61)
        with patch("scilex.crawlers.circuit_breaker.datetime") as mock_dt:
            mock_dt.now.return_value = future_time
            cb.is_available()  # triggers transition to HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60, name="test")
        cb.record_failure()
        cb.record_failure()

        future_time = datetime.now() + timedelta(seconds=61)
        with patch("scilex.crawlers.circuit_breaker.datetime") as mock_dt:
            mock_dt.now.return_value = future_time
            cb.is_available()

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=2, name="test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_get_stats(self):
        cb = CircuitBreaker(failure_threshold=5, timeout_seconds=30, name="myapi")
        stats = cb.get_stats()
        assert stats["name"] == "myapi"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 5
        assert stats["timeout_seconds"] == 30
        assert stats["last_failure_time"] is None

    def test_get_stats_after_failure(self):
        cb = CircuitBreaker(name="test")
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["failure_count"] == 1
        assert stats["last_failure_time"] is not None


# -------------------------------------------------------------------------
# CircuitBreakerRegistry
# -------------------------------------------------------------------------
class TestCircuitBreakerRegistry:
    def setup_method(self):
        # Reset singleton for test isolation
        CircuitBreakerRegistry._instance = None

    def test_singleton(self):
        r1 = CircuitBreakerRegistry()
        r2 = CircuitBreakerRegistry()
        assert r1 is r2

    def test_get_breaker_creates_new(self):
        registry = CircuitBreakerRegistry()
        cb = registry.get_breaker("TestAPI")
        assert isinstance(cb, CircuitBreaker)
        assert cb.name == "TestAPI"

    def test_get_breaker_returns_same_instance(self):
        registry = CircuitBreakerRegistry()
        cb1 = registry.get_breaker("TestAPI")
        cb2 = registry.get_breaker("TestAPI")
        assert cb1 is cb2

    def test_different_apis_get_different_breakers(self):
        registry = CircuitBreakerRegistry()
        cb1 = registry.get_breaker("API1")
        cb2 = registry.get_breaker("API2")
        assert cb1 is not cb2

    def teardown_method(self):
        # Clean up singleton
        CircuitBreakerRegistry._instance = None


# -------------------------------------------------------------------------
# CircuitBreakerOpenError
# -------------------------------------------------------------------------
class TestCircuitBreakerOpenError:
    def test_error_message(self):
        err = CircuitBreakerOpenError("MyAPI", 60)
        assert "MyAPI" in str(err)
        assert "60" in str(err)
        assert err.breaker_name == "MyAPI"
        assert err.timeout_seconds == 60
