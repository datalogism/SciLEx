"""Snowball sampling module for extending SciLEx collections via citations.

Identifies highly-connected papers outside the corpus by analyzing
citation caches, fetches their metadata, and merges them with the
existing collection after quality filtering.
"""

from scilex.snowball.candidates import extract_candidates
from scilex.snowball.fetcher import fetch_metadata_batch
from scilex.snowball.filter import apply_snowball_filters
from scilex.snowball.merge import (
    merge_with_corpus,
    save_merged_corpus,
    write_snowball_output,
)

__all__ = [
    "apply_snowball_filters",
    "extract_candidates",
    "fetch_metadata_batch",
    "merge_with_corpus",
    "save_merged_corpus",
    "write_snowball_output",
]
