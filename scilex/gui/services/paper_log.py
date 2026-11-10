"""When and how each paper entered a review, kept across re-aggregations.

``aggregated_results.csv`` is rewritten by every collection, aggregation,
extension or import, so it cannot remember when a paper first appeared. This
log, ``paper_log.json`` in the review folder, maps each paper key (see
:func:`scilex.gui.services.screening.paper_key`) to the date it was first seen
and its origin (Collect, Extend collect, Zotero import, Snowball…).

Papers that were already in the review before the log existed get no date
("Before tracking"), except those an extension dated itself ("query YYYY-MM-DD").
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

import pandas as pd

from scilex.constants import is_valid

logger = logging.getLogger(__name__)

LOG_FILENAME = "paper_log.json"
ORIGIN_COLUMN = "extension_origin"  # same column as scilex.gui.services.extend

COLLECT = "Collect"
EXTEND = "Extend collect"
ZOTERO = "Zotero import"
KG = "Knowledge graph import"
BIBTEX = "BibTeX import"
SNOWBALL = "Snowball"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_lock = threading.Lock()


def log_path(folder: Path) -> Path:
    """Return the log file of the review in ``folder``."""
    return Path(folder) / LOG_FILENAME


def load(folder: Path) -> dict[str, dict]:
    """Read the log (empty if missing or damaged)."""
    path = log_path(folder)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring the damaged paper log %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save(folder: Path, log: dict[str, dict]) -> None:
    path = log_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".paper_log-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(log, handle, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def origin_of(record: dict) -> str:
    """How a results row entered the review, deduced from its columns."""
    archive = str(record.get("archive", "")).strip()
    if archive == "Zotero":
        return ZOTERO
    if archive == "KG":
        return KG
    if archive == "BibTeX":
        return BIBTEX
    depth = pd.to_numeric(record.get("snowball_depth"), errors="coerce")
    if pd.notna(depth) and depth > 0:
        return SNOWBALL
    origin = record.get(ORIGIN_COLUMN)
    if is_valid(origin) and str(origin).strip():
        origin = str(origin).strip()
        return EXTEND if origin.startswith("query") else origin
    return COLLECT


def _date_in_origin(record: dict) -> str | None:
    """The date an extension wrote in the row ("query 2026-11-10"), if any."""
    origin = record.get(ORIGIN_COLUMN)
    if not is_valid(origin):
        return None
    match = _DATE.search(str(origin))
    return match.group(0) if match else None


def update(
    folder: Path,
    results: pd.DataFrame,
    *,
    when: dt.date | None,
    fresh: bool = False,
) -> dict[str, dict]:
    """Add the papers of ``results`` the log does not know yet; return the log.

    Args:
        folder: Review folder.
        results: Aggregated results (a ``paper_key`` column is computed if absent).
        when: Date given to the new papers (None: unknown).
        fresh: Every paper of ``results`` was just added (a new review). Without
            it, the papers found when the log does not exist yet predate the
            log and get no date.
    """
    from scilex.gui.services.screening import paper_key

    with _lock:
        existed = log_path(folder).is_file()
        log = load(folder)
        records = results.to_dict("records")
        added = 0
        for record in records:
            key = record.get("paper_key")
            if not isinstance(key, str) or not key:
                key = paper_key(record)
            if key in log:
                continue
            date = _date_in_origin(record)
            if date is None and when is not None and (existed or fresh):
                date = when.isoformat()
            log[key] = {"imported_at": date, "origin": origin_of(record)}
            added += 1
        if added or not existed:
            try:
                _save(folder, log)
            except OSError as exc:  # read-only folder: filters still work in memory
                logger.warning("Cannot save the paper log in %s: %s", folder, exc)
    return log


def update_from_file(
    folder: Path, results_path: Path, *, when: dt.date | None, fresh: bool = False
) -> None:
    """:func:`update` from a results file (nothing when it is missing)."""
    from scilex.gui.services.extend import read_results

    data = read_results(results_path)
    if data is not None:
        update(folder, data, when=when, fresh=fresh)


def mtime_date(path: Path) -> dt.date | None:
    """Date of the last change of ``path`` (None when missing)."""
    try:
        return dt.date.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return None
