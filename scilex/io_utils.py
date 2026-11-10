"""Shared I/O helpers for the aggregated results CSV.

The aggregated CSV is read by several CLI tools (BibTeX export, Zotero push,
Papers with Code enrichment). This module centralises path resolution, delimiter
detection and atomic writing so they cannot drift apart.
"""

import csv
import logging
import os
import tempfile
import time

import pandas as pd

from scilex.config_defaults import DEFAULT_AGGREGATED_FILENAME, DEFAULT_OUTPUT_DIR
from scilex.constants import normalize_path_component

logger = logging.getLogger(__name__)

CSV_DELIMITERS = (";", "\t", ",")
AGGREGATED_CSV_SEP = ";"
REQUIRED_COLUMNS = ("itemType", "title")


def resolve_aggregate_path(config: dict, collect_dir: str | None = None) -> str:
    """Return the path of the aggregated CSV described by ``config``.

    Args:
        config: Configuration with ``collect_name`` and optionally ``output_dir``
            and ``aggregate_file`` (defaults from config_defaults otherwise).
        collect_dir: Direct collect directory; overrides ``config["_collect_dir"]``
            and the ``output_dir`` + ``collect_name`` derivation.

    Returns:
        Path to the aggregated CSV file.
    """
    aggregate_file = config.get("aggregate_file", DEFAULT_AGGREGATED_FILENAME)
    directory = collect_dir or config.get("_collect_dir")
    if not directory:
        output_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
        directory = os.path.join(
            output_dir, normalize_path_component(config["collect_name"])
        )
    return os.path.join(directory, normalize_path_component(aggregate_file))


def load_aggregated_data(
    config: dict,
    collect_dir: str | None = None,
    preserve_missing_marker: bool = False,
) -> pd.DataFrame:
    """Load the aggregated CSV, trying ``;``, tab then ``,`` as delimiter.

    Args:
        config: Configuration dictionary (see ``resolve_aggregate_path``).
        collect_dir: Optional direct collect directory.
        preserve_missing_marker: When True, the literal ``"NA"`` (MISSING_VALUE)
            is kept as a string instead of being parsed as NaN; only empty
            cells become NaN. Needed when the frame is written back.

    Returns:
        DataFrame with at least the ``itemType`` and ``title`` columns.

    Raises:
        ValueError: If no delimiter yields the expected columns; the message
            includes the last underlying read error.
    """
    file_path = resolve_aggregate_path(config, collect_dir)
    logger.info(f"Loading data from: {file_path}")

    read_options = (
        {"keep_default_na": False, "na_values": [""]} if preserve_missing_marker else {}
    )
    last_error: Exception | None = None
    for delimiter in CSV_DELIMITERS:
        try:
            data = pd.read_csv(file_path, delimiter=delimiter, **read_options)
        except Exception as error:
            last_error = error
            logger.debug(f"Failed to load with delimiter '{delimiter}': {error}")
            continue
        if all(column in data.columns for column in REQUIRED_COLUMNS):
            logger.info(f"Loaded {len(data)} papers (delimiter: '{delimiter}')")
            return data
        last_error = ValueError(f"missing columns {REQUIRED_COLUMNS}")

    raise ValueError(
        f"Could not load CSV file with any delimiter (tried: ';', '\\t', ','). "
        f"File: {file_path}. Last error: {last_error}"
    )


REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05


def _replace_with_retry(source: str, target: str) -> None:
    """``os.replace`` that waits for a reader to close ``target`` (Windows).

    On Windows a file open for reading cannot be replaced: another job (or the
    page) reading the results for a moment would make the write fail.
    """
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS * (attempt + 1))


def write_aggregated_csv(
    data: pd.DataFrame, path: str, quoting: int = csv.QUOTE_MINIMAL
) -> None:
    """Write ``data`` to ``path`` atomically (temp file in same dir + os.replace).

    Args:
        data: Papers to write (the index is not written).
        path: Destination file.
        quoting: ``csv`` quoting mode passed to ``DataFrame.to_csv``.
    """
    directory = os.path.dirname(os.path.abspath(path))
    file_descriptor, temp_path = tempfile.mkstemp(
        dir=directory, prefix=".aggregated_", suffix=".tmp"
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            data.to_csv(handle, sep=AGGREGATED_CSV_SEP, index=False, quoting=quoting)
        _replace_with_retry(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
