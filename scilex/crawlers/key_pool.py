"""Round-robin API key pool with temporary blacklisting (issue #6).

In ``api.config.yml`` an API key may be one string or a list of strings. With a list,
each request uses the next key; a key that triggers a throttle (429) or an
authentication error (401/403) is set aside for a while and the next key is used.
"""

from __future__ import annotations

import threading
import time

THROTTLE_COOLDOWN_SECONDS = 60.0
AUTH_COOLDOWN_SECONDS = 3600.0

_SHARED_POOLS: dict[tuple[str, ...], KeyPool] = {}
_SHARED_LOCK = threading.Lock()


def normalize_keys(value) -> list[str]:
    """Turn a config value (None, str or list of str) into a list of non-empty keys."""
    if value is None:
        return []
    candidates = value if isinstance(value, (list, tuple)) else [value]
    return [key for key in candidates if isinstance(key, str) and key.strip()]


def first_key(value) -> str | None:
    """Return the first configured key (for code paths that use a single key)."""
    keys = normalize_keys(value)
    return keys[0] if keys else None


class KeyPool:
    """Thread-safe round-robin pool of API keys."""

    def __init__(self, keys: list[str], clock=time.monotonic):
        if not keys:
            raise ValueError("KeyPool needs at least one key")
        self._keys = list(dict.fromkeys(keys))
        self._unavailable_until: dict[str, float] = {}
        self._cursor = 0
        self._lock = threading.Lock()
        self._clock = clock

    @property
    def keys(self) -> list[str]:
        """All keys of the pool (including temporarily unavailable ones)."""
        return list(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def _is_available(self, key: str, now: float) -> bool:
        return self._unavailable_until.get(key, 0.0) <= now

    def next_key(self) -> str:
        """Return the next available key (round-robin).

        When every key is cooling down, the one that recovers first is returned so
        the run keeps progressing instead of stalling.
        """
        with self._lock:
            now = self._clock()
            for offset in range(len(self._keys)):
                index = (self._cursor + offset) % len(self._keys)
                key = self._keys[index]
                if self._is_available(key, now):
                    self._cursor = (index + 1) % len(self._keys)
                    return key
            soonest = min(self._keys, key=lambda k: self._unavailable_until.get(k, 0.0))
            self._cursor = (self._keys.index(soonest) + 1) % len(self._keys)
            return soonest

    def mark_failed(
        self, key: str, cooldown: float = THROTTLE_COOLDOWN_SECONDS
    ) -> None:
        """Make ``key`` unavailable for ``cooldown`` seconds."""
        if key not in self._keys:
            return
        with self._lock:
            self._unavailable_until[key] = self._clock() + cooldown

    def has_other_available(self, current: str) -> bool:
        """True if some key other than ``current`` is currently usable."""
        with self._lock:
            now = self._clock()
            return any(k != current and self._is_available(k, now) for k in self._keys)

    def replace_keys(self, text: str, new_key: str) -> str:
        """Substitute any pool key found in ``text`` by ``new_key``."""
        for key in self._keys:
            if key != new_key and key in text:
                text = text.replace(key, new_key)
        return text


def get_shared_pool(keys: list[str]) -> KeyPool:
    """Return the process-wide pool for this key set (shared by all queries/threads)."""
    identity = tuple(dict.fromkeys(keys))
    with _SHARED_LOCK:
        if identity not in _SHARED_POOLS:
            _SHARED_POOLS[identity] = KeyPool(list(identity))
        return _SHARED_POOLS[identity]
