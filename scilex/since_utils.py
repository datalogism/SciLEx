"""Helpers for incremental re-collection from a date (``since``, issue #31).

A collection run started with ``since`` queries the years ``year(since)..current``,
asks each API for records published on or after the date when the API supports it,
and writes into a sibling directory ``<collect_name>_since_<YYYY-MM-DD>``. The
aggregation then merges those sibling directories into the main collection (the
existing deduplication removes overlaps) after post-filtering by date.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime

import yaml

from scilex.constants import is_valid

SINCE_DIR_MARKER = "_since_"
_DATE_PARTS = re.compile(r"^\s*(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?")


def parse_since(value: str | date | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` string (or date) into a date; None stays None.

    Raises:
        ValueError: If the value is not a valid ISO date.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def years_since(since: date, today: date | None = None) -> list[int]:
    """Years to query for a since-run: ``year(since)..current year`` inclusive."""
    current_year = (today or date.today()).year
    return list(range(since.year, max(since.year, current_year) + 1))


def query_start_date(year: int, since: date | None) -> date | None:
    """Return ``since`` when it falls inside ``year`` (native filter lower bound)."""
    if since is not None and since.year == int(year):
        return since
    return None


def since_collect_name(collect_name: str, since: date) -> str:
    """Name of the sibling directory holding the since-run of ``collect_name``."""
    return f"{collect_name}{SINCE_DIR_MARKER}{since.isoformat()}"


def passes_since(date_value, since: date) -> bool:
    """Keep a record unless its known date is before ``since``.

    Partial dates are compared at their precision: a bare year is kept when
    ``year >= since.year``, a year-month when it is not before ``since``'s month.
    Unknown or unparsable dates are kept (conservative).
    """
    if not is_valid(date_value):
        return True
    match = _DATE_PARTS.match(str(date_value))
    if not match:
        return True
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if month is None:
        return year >= since.year
    if day is None:
        return (year, month) >= (since.year, since.month)
    return (year, month, day) >= (since.year, since.month, since.day)


def find_since_collections(dir_collect: str) -> list[str]:
    """List sibling ``<collect>_since_<date>`` directories that hold a config snapshot."""
    parent, base = os.path.split(os.path.normpath(dir_collect))
    prefix = f"{base}{SINCE_DIR_MARKER}"
    try:
        names = sorted(os.listdir(parent or "."))
    except OSError:
        return []
    return [
        os.path.join(parent, name)
        for name in names
        if name.startswith(prefix)
        and os.path.isfile(os.path.join(parent, name, "config_used.yml"))
    ]


def load_since_collection_papers(since_dir: str) -> list[tuple[dict, str, list[str]]]:
    """Load a since-run directory and post-filter its papers by date.

    Returns ``(raw_paper, api_name, keywords)`` tuples, like the loader of the main
    collection. APIs that filtered natively already return only recent records; the
    others are filtered here using the date produced by their format converter.
    """
    from scilex.crawlers.aggregate import FORMAT_CONVERTERS
    from scilex.crawlers.aggregate_parallel import parallel_load_all_files

    with open(os.path.join(since_dir, "config_used.yml"), encoding="utf-8") as handle:
        since_config = yaml.safe_load(handle) or {}
    since = parse_since(since_config.get("since"))

    papers, _stats = parallel_load_all_files(since_dir, since_config)
    if since is None:
        return papers

    kept = []
    for paper, api_name, keywords in papers:
        converter = FORMAT_CONVERTERS.get(api_name)
        try:
            paper_date = converter(paper).get("date") if converter else None
        except Exception as error:  # a broken record is left to the main pipeline
            logging.debug(f"since filter: converter failed for {api_name}: {error}")
            paper_date = None
        if passes_since(paper_date, since):
            kept.append((paper, api_name, keywords))
    logging.info(
        f"Since-collection {os.path.basename(since_dir)}: kept {len(kept):,}/"
        f"{len(papers):,} records on or after {since.isoformat()}"
    )
    return kept


def prepare_since_config(
    main_config: dict, since: date, today: date | None = None
) -> dict:
    """Return a copy of ``main_config`` configured for a since-run.

    Years become ``year(since)..current``, the collection is redirected to the
    sibling ``<collect_name>_since_<date>`` directory (idempotent when resuming),
    and ``since`` is stored as an ISO string so it lands in ``config_used.yml``.
    """
    prepared = dict(main_config)
    prepared["since"] = since.isoformat()
    prepared["years"] = years_since(since, today)
    collect_name = str(prepared.get("collect_name", "unknown"))
    if SINCE_DIR_MARKER not in collect_name:
        prepared["collect_name"] = since_collect_name(collect_name, since)
    return prepared
