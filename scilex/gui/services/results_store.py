"""Safe concurrent writes to a review's ``aggregated_results.csv``.

Several jobs may run on the same review at once (see the resources of
:mod:`scilex.gui.services.jobs`). The row-changing ones (aggregation, extension,
consolidation, imports) are exclusive; the column enrichers (Crossref, LPWC,
ORKG, Papers with Code, search keywords…) may run together. Each enricher reads
the results when it starts and works for minutes, so writing its whole table at
the end would erase what another enricher wrote meanwhile.

So enrichers write through this module: under a per-file lock, the current file
is read again and only what the job changed is copied into it:

- :func:`write_changes` copies the *cells* that differ between the table the job
  read (``before``) and the table it produced (``after``);
- :func:`write_columns` copies whole columns.

Rows are matched by paper key (DOI, else title and year) and occurrence: the
second row of a paper in the job's table is the second row of that paper in the
file (a review may keep a paper twice on purpose). Rows the job does not know
(added meanwhile) are kept as they are.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from scilex.constants import is_valid

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def lock_for(path: str | Path) -> threading.RLock:
    """The lock of one results file (same lock for every spelling of the path)."""
    key = str(Path(path).resolve()).casefold()
    with _guard:
        return _locks.setdefault(key, threading.RLock())


def _keys(data: pd.DataFrame) -> list[tuple[str, int]]:
    """``(paper key, occurrence)`` of each row, in order."""
    from scilex.gui.services.screening import paper_key

    seen: dict[str, int] = {}
    keys = []
    for record in data.to_dict("records"):
        key = paper_key(record)
        keys.append((key, seen.get(key, 0)))
        seen[key] = seen.get(key, 0) + 1
    return keys


def _same(a, b) -> bool:
    if not is_valid(a) and not is_valid(b):
        return True
    return is_valid(a) and is_valid(b) and str(a) == str(b)


def _merge(
    path: Path, after: pd.DataFrame, cells: dict[tuple[str, int], dict[str, object]]
) -> int:
    """Write ``cells`` (row key -> {column: value}) into the current file."""
    from scilex.gui.services.extend import read_results, write_results

    current = read_results(path)
    if current is None:
        write_results(after, path)
        return len(after)
    columns = {column for values in cells.values() for column in values}
    for column in columns:
        if column not in current.columns:
            current[column] = ""
        current[column] = current[column].astype(object)
    position = {
        key: index for key, index in zip(_keys(current), current.index, strict=True)
    }
    written = 0
    for key, values in cells.items():
        index = position.get(key)
        if index is None:  # the paper left the file meanwhile: nothing to update
            continue
        for column, value in values.items():
            current.at[index, column] = value
        written += 1
    write_results(current, path)
    return written


def write_changes(path: str | Path, before: pd.DataFrame, after: pd.DataFrame) -> int:
    """Copy into the file the cells ``after`` changed relative to ``before``.

    ``before`` is the table as the job read it, ``after`` the same rows once
    enriched (same order; new columns allowed). Returns the number of rows
    written. With no file yet, ``after`` is written as it is.
    """
    path = Path(path)
    if len(before) != len(after):
        raise ValueError("write_changes: before and after must have the same rows")
    cells: dict[tuple[str, int], dict[str, object]] = {}
    keys = _keys(before)
    before_records = before.to_dict("records")
    for key, old, new in zip(
        keys, before_records, after.to_dict("records"), strict=True
    ):
        changed = {
            column: value
            for column, value in new.items()
            if not _same(value, old.get(column))
        }
        if changed:
            cells[key] = changed
    with lock_for(path):
        if not cells and path.is_file():
            return 0
        return _merge(path, after, cells)


def write_columns(path: str | Path, data: pd.DataFrame, columns: Iterable[str]) -> int:
    """Copy ``columns`` of ``data`` into the file, for the rows it has.

    For a job that owns those columns (e.g. the Papers with Code ones): every
    other column of the file stays as it is now.
    """
    path = Path(path)
    columns = [column for column in columns if column in data.columns]
    cells = {
        key: {column: record[column] for column in columns}
        for key, record in zip(_keys(data), data.to_dict("records"), strict=True)
    }
    with lock_for(path):
        return _merge(path, data, cells)


# Whole-file reads and writes (row-changing jobs) go through
# scilex.gui.services.extend.read_results / write_results, which take the same lock.
