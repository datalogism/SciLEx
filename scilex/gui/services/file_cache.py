"""Parse a review file once, until it changes on disk.

The pages and services of a review read the same files many times per action
(the aggregated results above all: Explore, Screen, Overview, the analyses,
the sync…). Each read is a full CSV parse. This cache keeps the parsed value
of a file keyed by its modification time and size: any write (by SciLEx, a
job, or another program) changes the key, so a read never returns stale
data. SciLEx's own writers also :func:`forget` the file explicitly.

Values are returned as copies when they are mutable (DataFrames): callers
change the tables they read.
"""

from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pandas as pd

T = TypeVar("T")
MAX_ENTRIES = 32  # a few reviews' files; least recently used dropped first

_lock = threading.Lock()
_entries: OrderedDict[str, tuple[tuple[int, int], object]] = OrderedDict()
_stats = {"hits": 0, "misses": 0}


def _key(path: Path) -> str:
    return str(Path(path).resolve())


def _copy(value):
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, (dict, list, set)):
        return copy.deepcopy(value)
    return value  # immutable values (frozen dataclasses, strings…)


def load(path: Path, loader: Callable[[Path], T]) -> T | None:
    """``loader(path)``, parsed once per version of the file (None when absent)."""
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        forget(path)
        return None
    version = (stat.st_mtime_ns, stat.st_size)
    key = _key(path)
    with _lock:
        entry = _entries.get(key)
        if entry is not None and entry[0] == version:
            _entries.move_to_end(key)
            _stats["hits"] += 1
            return _copy(entry[1])
    value = loader(path)
    with _lock:
        _stats["misses"] += 1
        _entries[key] = (version, value)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return _copy(value)


def forget(path: Path) -> None:
    """Drop the cached value of ``path`` (after writing it)."""
    with _lock:
        _entries.pop(_key(path), None)


def clear() -> None:
    """Drop everything (tests)."""
    with _lock:
        _entries.clear()
        _stats.update(hits=0, misses=0)


def stats() -> dict[str, int]:
    """Hits and misses since the start (or the last :func:`clear`)."""
    with _lock:
        return dict(_stats, entries=len(_entries))
