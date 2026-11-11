"""
Adaptive rate limiter registry for SciLEx API collectors.

Solves two problems:
1. Per-instance _last_call_time resets to 0 on every new query, leaving
   a gap of zero wait between consecutive queries for the same API.
   The registry is process-wide (singleton), so all collector instances
   of the same API share a single timer — inter-query delays are enforced.

2. Fixed rate limits don't respond to throttle signals. When an API returns
   persistent 429s, extra_delay doubles (10s → 20s → 40s … ≤ 300s). After
   every SUCCESS_DECAY_INTERVAL successful requests the extra delay halves,
   so the limiter self-heals once the API cools down.
"""

import logging
import threading
import time


class AdaptiveRateLimiter:
    """Adaptive rate limiter for a single API (not intended for direct use)."""

    MAX_EXTRA_DELAY = 300.0
    SUCCESS_DECAY_INTERVAL = 5

    def __init__(self, api_name: str):
        self.api_name = api_name
        self._lock = threading.Lock()
        self._last_call_time: float = 0.0
        self._extra_delay: float = 0.0
        self._consecutive_throttles: int = 0
        self._consecutive_successes: int = 0

    def wait(self, base_rate: float, cancel_event=None) -> None:
        """Block until the next request is allowed, then mark the call time.

        A set ``cancel_event`` ends the wait early (the caller then stops).
        """
        with self._lock:
            min_interval = (1.0 / base_rate) if base_rate > 0 else 0.0
            total_interval = min_interval + self._extra_delay
            elapsed = time.monotonic() - self._last_call_time
            wait_needed = total_interval - elapsed

        if wait_needed > 0:
            if cancel_event is not None:
                cancel_event.wait(wait_needed)
            else:
                time.sleep(wait_needed)

        with self._lock:
            self._last_call_time = time.monotonic()

    def on_throttle(self) -> float:
        """Called when all retries fail with 429/409. Returns the new extra delay."""
        with self._lock:
            self._consecutive_throttles += 1
            self._consecutive_successes = 0
            n = self._consecutive_throttles
            self._extra_delay = min(10.0 * (2 ** (n - 1)), self.MAX_EXTRA_DELAY)
            delay = self._extra_delay
        logging.warning(
            f"{self.api_name}: adaptive rate limit → +{delay:.0f}s extra inter-request "
            f"delay (throttle #{n})"
        )
        return delay

    def on_success(self) -> None:
        """Called after every successful request. Gradually reduces extra delay."""
        with self._lock:
            self._consecutive_successes += 1
            self._consecutive_throttles = 0
            if (
                self._extra_delay > 0
                and self._consecutive_successes % self.SUCCESS_DECAY_INTERVAL == 0
            ):
                self._extra_delay = max(0.0, self._extra_delay * 0.5)
                if self._extra_delay < 0.5:
                    self._extra_delay = 0.0
                logging.info(
                    f"{self.api_name}: adaptive rate limit reduced to "
                    f"+{self._extra_delay:.1f}s extra delay "
                    f"(after {self._consecutive_successes} successes)"
                )


class AdaptiveRateLimiterRegistry:
    """
    Process-wide singleton registry of per-API adaptive rate limiters.

    Survives across collector instances: when a worker finishes query N and
    starts query N+1 (creating a fresh collector), the registry remembers
    when the last request fired and enforces the correct wait.

    Usage::

        registry = AdaptiveRateLimiterRegistry()
        limiter = registry.get("Arxiv")
        limiter.wait(base_rate)          # before each HTTP call
        limiter.on_success()             # on 2xx response
        limiter.on_throttle()            # when 429 persists after all retries
    """

    _instance: "AdaptiveRateLimiterRegistry | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "AdaptiveRateLimiterRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._limiters: dict[str, AdaptiveRateLimiter] = {}
                obj._limiters_lock = threading.Lock()
                cls._instance = obj
        return cls._instance

    def get(self, api_name: str) -> AdaptiveRateLimiter:
        """Return (or create) the AdaptiveRateLimiter for *api_name*."""
        with self._limiters_lock:
            if api_name not in self._limiters:
                self._limiters[api_name] = AdaptiveRateLimiter(api_name)
            return self._limiters[api_name]
