"""Extend collect: run new queries on a review that already has papers.

Two modes, chosen in ② Extend collect:

- ``add``: collect, aggregate, then keep the review's papers as they are and
  append only the papers they do not have yet (same DOI, or same title + year:
  :func:`scilex.gui.services.screening.paper_key`). Rankings and screening of the
  existing papers do not move.
- ``reaggregate``: collect, then deduplicate, filter and rank the whole raw
  collection again. Papers that do not come from the raw collection (imported
  from Zotero, added by a snowball or an earlier ``add``) cannot be produced by
  the aggregation, so they are carried over when it drops them.

Either way the previous results are saved in ``previous_results/`` first.
"""

from __future__ import annotations

import csv
import datetime as dt
import shutil
from pathlib import Path

import pandas as pd

from scilex.constants import is_valid
from scilex.gui.services.screening import paper_key

ADD_NEW, REAGGREGATE = "add", "reaggregate"
MODES = (ADD_NEW, REAGGREGATE)
# Where a row comes from when it was not produced by the aggregation.
ORIGIN_COLUMN = "extension_origin"
BACKUP_DIRNAME = "previous_results"
BACKUP_FILENAME = "aggregated_results_before_extension.csv"


def read_results(path: Path) -> pd.DataFrame | None:
    """Read an aggregated results file exactly as written (None when absent)."""
    from scilex.io_utils import load_aggregated_data

    if not Path(path).is_file():
        return None
    return load_aggregated_data(
        {"collect_name": Path(path).parent.name},
        collect_dir=str(Path(path).parent),
        preserve_missing_marker=True,
    )


def write_results(data: pd.DataFrame, path: Path) -> None:
    """Write aggregated results atomically."""
    from scilex.io_utils import write_aggregated_csv

    write_aggregated_csv(data, str(path), quoting=csv.QUOTE_NONNUMERIC)


def backup(path: Path) -> Path | None:
    """Copy the current results to ``previous_results/`` before they change."""
    if not Path(path).is_file():
        return None
    target = Path(path).parent / BACKUP_DIRNAME / BACKUP_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def _keys(data: pd.DataFrame) -> list[str]:
    return [paper_key(record) for record in data.to_dict("records")]


def is_outside_collection(row: dict) -> bool:
    """True for a paper the aggregation of the raw collection cannot produce."""
    if str(row.get("archive", "")).strip() == "Zotero":
        return True
    origin = row.get(ORIGIN_COLUMN)
    if is_valid(origin) and str(origin).strip():
        return True
    depth = pd.to_numeric(row.get("snowball_depth"), errors="coerce")
    return bool(pd.notna(depth) and depth > 0)


def add_new_only(
    previous: pd.DataFrame, current: pd.DataFrame, origin: str | None = None
) -> tuple[pd.DataFrame, int]:
    """Return ``previous`` + the rows of ``current`` it does not have, and their count."""
    known = set(_keys(previous))
    current_keys = _keys(current)
    seen: set[str] = set()
    keep = []
    for key in current_keys:
        keep.append(key not in known and key not in seen)
        seen.add(key)
    new_rows = current.loc[keep].copy()
    origin = origin or f"query {dt.date.today().isoformat()}"
    new_rows[ORIGIN_COLUMN] = origin
    if ORIGIN_COLUMN not in previous.columns:
        previous = previous.copy()
        previous[ORIGIN_COLUMN] = ""
    merged = pd.concat([previous, new_rows], ignore_index=True)
    return merged, len(new_rows)


def keep_outside_rows(
    previous: pd.DataFrame, current: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    """Return ``current`` + the papers of ``previous`` from outside the collection it lost."""
    present = set(_keys(current))
    records = previous.to_dict("records")
    carried = [
        index
        for index, (record, key) in enumerate(zip(records, _keys(previous), strict=True))
        if key not in present and is_outside_collection(record)
    ]
    if not carried:
        return current, 0
    merged = pd.concat([current, previous.iloc[carried]], ignore_index=True)
    return merged, len(carried)


def apply_extension(mode: str, previous: pd.DataFrame | None, results_path: Path) -> str:
    """Merge the fresh aggregation at ``results_path`` with ``previous``; return a summary."""
    if mode not in MODES:
        raise ValueError(f"Unknown extension mode {mode!r}")
    current = read_results(results_path)
    if previous is None or current is None:
        return ""
    if mode == ADD_NEW:
        merged, count = add_new_only(previous, current)
        summary = f"{count} new papers added to the {len(previous)} already in the review."
    else:
        merged, count = keep_outside_rows(previous, current)
        summary = (
            f"Re-aggregated: {len(current)} papers from the collection"
            + (f", plus {count} imported or snowballed papers kept." if count else ".")
        )
    write_results(merged, results_path)
    return summary
