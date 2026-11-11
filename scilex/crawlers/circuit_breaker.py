"""Circuit Breaker pattern for API calls.

Prevents wasting time on repeatedly failing API endpoints by "opening the circuit"
after a threshold of consecutive failures.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Circuit is open, requests fail immediately
- HALF_OPEN: Test state, allows one request to check if endpoint recovered
"""

import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Optional


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing if endpoint recovered


class CircuitBreaker:
    """Circuit breaker for API calls with failure threshold and timeout.

    Thread-safe implementation using locks.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        name: str = "default",
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            timeout_seconds: Seconds to wait before attempting half-open state
            name: Name for this circuit (for logging)
        """
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.name = name

        # State tracking (thread-safe)
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._success_count = 0

    @property
    def state(self) -> CircuitState:
        """Get current circuit state (thread-safe)."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count (thread-safe)."""
        with self._lock:
            return self._failure_count

    def is_available(self) -> bool:
        """Check if circuit allows requests.

        Returns:
            True if request can proceed, False if circuit is open
        """
        with self._lock:
            # CLOSED: Always allow
            if self._state == CircuitState.CLOSED:
                return True

            # HALF_OPEN: Allow (testing recovery)
            if self._state == CircuitState.HALF_OPEN:
                return True

            # OPEN: Check if timeout expired
            if self._state == CircuitState.OPEN:
                if self._last_failure_time is None:
                    return False

                time_since_failure = datetime.now() - self._last_failure_time
                if time_since_failure.total_seconds() >= self.timeout_seconds:
                    # Timeout expired, transition to HALF_OPEN for test
                    logging.info(
                        f"Circuit breaker '{self.name}': Timeout expired, "
                        f"transitioning to HALF_OPEN for recovery test"
                    )
                    self._state = CircuitState.HALF_OPEN
                    return True

                # Still in timeout period
                return False

            return False

    def record_success(self):
        """Record successful API call."""
        with self._lock:
            self._failure_count = 0  # Reset failure counter

            if self._state == CircuitState.HALF_OPEN:
                # Recovery test succeeded, close circuit
                logging.info(
                    f"Circuit breaker '{self.name}': Recovery test successful, "
                    f"closing circuit"
                )
                self._state = CircuitState.CLOSED
                self._success_count += 1

    def record_failure(self):
        """Record failed API call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                # Recovery test failed, re-open circuit
                logging.warning(
                    f"Circuit breaker '{self.name}': Recovery test failed, "
                    f"re-opening circuit"
                )
                self._state = CircuitState.OPEN
                return

            if (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                # Threshold reached, open circuit
                logging.warning(
                    f"Circuit breaker '{self.name}': Failure threshold reached "
                    f"({self._failure_count} consecutive failures), OPENING CIRCUIT"
                )
                logging.warning(
                    f"Circuit breaker '{self.name}': Will retry after "
                    f"{self.timeout_seconds}s timeout"
                )
                self._state = CircuitState.OPEN

    def reset(self):
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            logging.info(f"Circuit breaker '{self.name}': Manual reset to CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure_time": self._last_failure_time.isoformat()
                if self._last_failure_time
                else None,
                "failure_threshold": self.failure_threshold,
                "timeout_seconds": self.timeout_seconds,
            }


class CircuitBreakerRegistry:
    """Global registry for circuit breakers (one per API).

    Thread-safe singleton pattern.
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._breakers: dict[str, CircuitBreaker] = {}
                    cls._instance._registry_lock = threading.Lock()
        return cls._instance

    def get_breaker(
        self, api_name: str, failure_threshold: int = 5, timeout_seconds: int = 60
    ) -> CircuitBreaker:
        """Get or create circuit breaker for an API.

        Args:
            api_name: API name
            failure_threshold: Number of consecutive failures before opening
            timeout_seconds: Seconds to wait before retry

        Returns:
            CircuitBreaker instance
        """
        with self._registry_lock:
            if api_name not in self._breakers:
                self._breakers[api_name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    timeout_seconds=timeout_seconds,
                    name=api_name,
                )
                logging.debug(
                    f"Created circuit breaker for '{api_name}' "
                    f"(threshold={failure_threshold}, timeout={timeout_seconds}s)"
                )
            return self._breakers[api_name]


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and blocks request."""

    def __init__(self, breaker_name: str, timeout_seconds: int):
        self.breaker_name = breaker_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN due to repeated failures. "
            f"Will retry after {timeout_seconds}s timeout."
        )
