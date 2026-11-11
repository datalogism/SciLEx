"""Merge snowballed papers with the existing corpus."""

import csv
import logging
import os
import shutil

import pandas as pd

from scilex.constants import is_valid
from scilex.io_utils import write_aggregated_csv

logger = logging.getLogger(__name__)


def merge_with_corpus(
    corpus_df: pd.DataFrame,
    snowball_df: pd.DataFrame,
    doi_column: str = "DOI",
) -> pd.DataFrame:
    """Merge snowballed papers into the corpus, deduplicating by DOI.

    Adds a ``snowball_depth`` column: 0 for original corpus papers,
    1 for snowballed papers. Depths from an earlier snowball run are kept.

    Args:
        corpus_df: Original aggregated DataFrame.
        snowball_df: Snowballed papers DataFrame.
        doi_column: Column containing DOIs.

    Returns:
        Merged DataFrame with duplicates removed (corpus papers take priority).
    """
    corpus_df = corpus_df.copy()
    previous_depth = corpus_df.get("snowball_depth")
    corpus_df["snowball_depth"] = (
        pd.to_numeric(previous_depth, errors="coerce").fillna(0).astype(int)
        if previous_depth is not None
        else 0
    )
    if snowball_df.empty:
        return corpus_df

    snowball_df = snowball_df.copy()
    max_depth = int(corpus_df["snowball_depth"].max()) if len(corpus_df) else 0
    snowball_df["snowball_depth"] = max_depth + 1

    # Remove snowball papers already in corpus (by DOI)
    corpus_dois = set()
    if doi_column in corpus_df.columns:
        corpus_dois = {
            str(d).strip().lower() for d in corpus_df[doi_column] if is_valid(d)
        }

    if doi_column in snowball_df.columns:
        snowball_df = snowball_df[
            ~snowball_df[doi_column].apply(
                lambda x: (
                    str(x).strip().lower() in corpus_dois if is_valid(x) else False
                )
            )
        ]

    n_new = len(snowball_df)
    merged = pd.concat([corpus_df, snowball_df], ignore_index=True)

    logger.info(
        f"Merged: {len(corpus_df)} corpus + {n_new} new snowball = {len(merged)} total"
    )
    return merged


def separate_path_for(aggregate_path: str) -> str:
    """Return the path of the standalone snowball file next to ``aggregate_path``."""
    stem, extension = os.path.splitext(aggregate_path)
    return f"{stem}_snowball{extension}"


def backup_path_for(aggregate_path: str) -> str:
    """Return the path of the pre-snowball backup of ``aggregate_path``."""
    stem, extension = os.path.splitext(aggregate_path)
    return f"{stem}_pre_snowball{extension}"


def save_merged_corpus(merged_df: pd.DataFrame, aggregate_path: str) -> str:
    """Write the merged corpus over the aggregated file, after a one-time backup.

    The snowballed papers must land in the aggregated file itself, since every
    later step (Zotero, BibTeX, Turtle, GUI, web API) reads that file. The
    first run copies the original to ``*_pre_snowball.csv``; later runs keep
    that first backup so the pure aggregation output is never lost.

    Args:
        merged_df: Corpus plus snowballed papers.
        aggregate_path: Path of the aggregated CSV to replace.

    Returns:
        Path of the backup file.
    """
    backup_path = backup_path_for(aggregate_path)
    if os.path.isfile(aggregate_path) and not os.path.exists(backup_path):
        shutil.copy2(aggregate_path, backup_path)
        logger.info(f"Original aggregated file backed up to {backup_path}")
    write_aggregated_csv(merged_df, aggregate_path, quoting=csv.QUOTE_NONNUMERIC)
    logger.info(f"Snowballed papers written to {aggregate_path}")
    return backup_path


def write_snowball_output(
    merged_df: pd.DataFrame, aggregate_path: str, add_to_collection: bool = True
) -> tuple[str, str | None]:
    """Write the merged corpus, into the collection or to a separate file.

    Args:
        merged_df: Corpus plus snowballed papers.
        aggregate_path: Path of the collection's aggregated CSV.
        add_to_collection: True replaces the aggregated file (after a one-time
            backup); False writes ``*_snowball.csv`` and leaves the collection as is.

    Returns:
        ``(output_path, backup_path)``; ``backup_path`` is None for a separate file.
    """
    if add_to_collection:
        return aggregate_path, save_merged_corpus(merged_df, aggregate_path)
    output_path = separate_path_for(aggregate_path)
    write_aggregated_csv(merged_df, output_path, quoting=csv.QUOTE_NONNUMERIC)
    logger.info(f"Snowballed papers written to {output_path} (collection unchanged)")
    return output_path, None
