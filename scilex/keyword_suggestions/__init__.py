"""Keyword suggestion module for expanding SciLEx search queries.

Extracts frequent terms from clustered papers and compares them with
the existing search keywords to suggest new terms for future collections.
"""

from scilex.keyword_suggestions.extractor import (
    configured_keywords,
    extract_suggestions,
)
from scilex.keyword_suggestions.report import generate_keyword_report

__all__ = [
    "configured_keywords",
    "extract_suggestions",
    "generate_keyword_report",
]
