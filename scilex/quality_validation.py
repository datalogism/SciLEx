"""Quality validation module for SciLEx.

This module provides functions to validate paper metadata quality based on
configurable thresholds. It helps filter out incomplete or low-quality records
during the aggregation phase.
"""

import logging

import pandas as pd

from scilex.constants import (
    is_missing,
    is_valid,
    normalize_text_field,
    split_semicolon_field,
)


class QualityReport:
    """Tracks quality validation statistics during filtering."""

    def __init__(self):
        self.total_papers = 0
        self.papers_kept = 0
        self.papers_filtered = 0
        self.filter_reasons = {
            "missing_doi": 0,
            "empty_doi": 0,  # NEW: Enhanced DOI validation
            "missing_abstract": 0,
            "abstract_too_short": 0,
            "abstract_too_long": 0,
            "missing_year": 0,
            "outside_year_range": 0,  # NEW: Year range validation
            "invalid_year_format": 0,  # NEW: Year format validation
            "not_open_access": 0,  # NEW: Open access filter
            "insufficient_authors": 0,
        }

    def add_filtered(self, reason: str):
        """Record a paper being filtered with the given reason."""
        self.papers_filtered += 1
        if reason in self.filter_reasons:
            self.filter_reasons[reason] += 1

    def add_kept(self):
        """Record a paper being kept."""
        self.papers_kept += 1

    def generate_report(self) -> str:
        """Generate a human-readable quality report."""
        if self.total_papers == 0:
            return "No papers processed."

        report_lines = [
            "\n" + "=" * 70,
            "QUALITY VALIDATION REPORT",
            "=" * 70,
            f"Total papers processed: {self.total_papers}",
            f"Papers kept: {self.papers_kept} ({self.papers_kept / self.total_papers * 100:.1f}%)",
            f"Papers filtered: {self.papers_filtered} ({self.papers_filtered / self.total_papers * 100:.1f}%)",
            "",
            "Filter reasons:",
        ]

        for reason, count in sorted(
            self.filter_reasons.items(), key=lambda x: x[1], reverse=True
        ):
            if count > 0:
                percentage = count / self.total_papers * 100
                reason_label = reason.replace("_", " ").title()
                report_lines.append(f"  - {reason_label}: {count} ({percentage:.1f}%)")

        report_lines.append("=" * 70 + "\n")
        return "\n".join(report_lines)


def count_words(text: str) -> int:
    """Count words in text (handles various formats)."""
    return len(normalize_text_field(text).split())


def count_authors(authors_value) -> int:
    """Count number of authors (handles various formats)."""
    # Handle list format first (before is_missing which doesn't handle lists)
    if isinstance(authors_value, list):
        return len(authors_value)

    if is_missing(authors_value):
        return 0

    # Handle string format (semicolon or comma separated)
    authors_str = str(authors_value)

    # Semicolon is the clearest separator
    if ";" in authors_str:
        return len(split_semicolon_field(authors_str))

    # If no semicolon but has comma, check if it's a single "Last, First" author
    # or multiple authors
    if "," in authors_str:
        # Count number of commas - if odd, likely single author "Last, First"
        # if even, likely multiple comma-separated authors
        comma_count = authors_str.count(",")
        if comma_count == 1:
            # Single author in "Last, First" format
            return 1
        else:
            # Multiple authors, but be conservative since format is ambiguous
            # Assume pairs if even count
            return (comma_count + 1) // 2

    # Single author without separators
    return 1 if authors_str.strip() else 0


def validate_abstract(abstract, min_words: int, max_words: int) -> tuple[bool, str]:
    """Validate abstract quality.

    Returns:
        (is_valid, reason): Tuple of validation result and reason if invalid
    """
    if is_missing(abstract):
        return False, "missing_abstract"

    word_count = count_words(abstract)

    if min_words > 0 and word_count < min_words:
        return False, "abstract_too_short"

    if max_words > 0 and word_count > max_words:
        return False, "abstract_too_long"

    return True, ""


def passes_quality_filters(record: dict, filters: dict) -> tuple[bool, str]:
    """Check if a paper record passes all quality filters.

    Args:
        record: Dictionary containing paper metadata
        filters: Dictionary with quality filter settings

    Returns:
        (passes, reason): Tuple of whether record passes and reason if it fails
    """
    # Check DOI requirement (enhanced validation)
    if filters.get("require_doi", False):
        doi = record.get("DOI")
        if is_missing(doi):
            return False, "missing_doi"
        # Enhanced DOI validation: non-empty after stripping whitespace
        if isinstance(doi, str) and not doi.strip():
            return False, "empty_doi"

    # Check abstract requirement
    require_abstract = filters.get("require_abstract", False)
    min_abstract_words = filters.get("min_abstract_words", 0)
    max_abstract_words = filters.get("max_abstract_words", 0)

    if require_abstract or min_abstract_words > 0 or max_abstract_words > 0:
        abstract = record.get("abstract")
        is_valid_abstract, reason = validate_abstract(
            abstract, min_abstract_words, max_abstract_words
        )
        if not is_valid_abstract:
            return False, reason

    # Check year requirement
    if filters.get("require_year", False) and is_missing(record.get("date")):
        return False, "missing_year"

    # Check year range (NEW - validates year is in allowed range)
    if filters.get("validate_year_range", False):
        year_range = filters.get("year_range", [])
        if year_range:
            date_str = record.get("date")
            if is_valid(date_str):
                try:
                    # Extract year from ISO date (YYYY-MM-DD) or year string (YYYY)
                    if isinstance(date_str, str):
                        year_match = date_str.split("-")[0]
                        if year_match.isdigit():
                            year = int(year_match)
                            if year not in year_range:
                                return False, "outside_year_range"
                except (ValueError, AttributeError, IndexError):
                    # If year extraction fails, treat as missing year
                    return False, "invalid_year_format"

    # Check open access requirement (NEW)
    if filters.get("require_open_access", False):
        rights = record.get("rights")
        # Check if rights field indicates open access
        # Valid open access indicators: 'open', True, 'True'
        is_open = False
        if isinstance(rights, str):
            is_open = rights.lower() in ["open", "true"]
        elif isinstance(rights, bool):
            is_open = rights

        if not is_open:
            return False, "not_open_access"

    # Check minimum author count
    min_authors = filters.get("min_author_count", 0)
    if min_authors > 0:
        author_count = count_authors(record.get("authors"))
        if author_count < min_authors:
            return False, "insufficient_authors"

    return True, ""


def apply_quality_filters(
    df: pd.DataFrame, filters: dict, generate_report: bool = True
) -> tuple[pd.DataFrame, QualityReport]:
    """Apply quality filters to a DataFrame of papers.

    Args:
        df: DataFrame with paper records
        filters: Dictionary with quality filter settings
        generate_report: Whether to generate and log a quality report

    Returns:
        (filtered_df, report): Tuple of filtered DataFrame and QualityReport object
    """
    report = QualityReport()
    report.total_papers = len(df)

    if report.total_papers == 0:
        logging.info("No papers to filter.")
        return df, report

    # Track which rows to keep
    keep_mask = []

    for record in df.to_dict("records"):
        passes, reason = passes_quality_filters(record, filters)

        if passes:
            keep_mask.append(True)
            report.add_kept()
        else:
            keep_mask.append(False)
            report.add_filtered(reason)

    # Filter the DataFrame
    df_filtered = df[keep_mask].copy()

    # Generate and log report
    if generate_report:
        report_str = report.generate_report()
        logging.info(report_str)

    return df_filtered, report


def generate_data_completeness_report(df: pd.DataFrame) -> str:
    """Generate a report showing data completeness for key fields.

    Args:
        df: DataFrame with paper records

    Returns:
        String containing the completeness report
    """
    if len(df) == 0:
        return "No papers to analyze."

    key_fields = [
        "DOI",
        "title",
        "authors",
        "date",
        "abstract",
        "journalAbbreviation",
        "volume",
        "issue",
        "publisher",
    ]

    report_lines = [
        "\n" + "=" * 70,
        "DATA COMPLETENESS REPORT",
        "=" * 70,
        f"Total papers: {len(df)}",
        "",
        "Field completeness:",
    ]

    for field in key_fields:
        if field in df.columns:
            non_missing = df[field].apply(is_valid).sum()
            percentage = non_missing / len(df) * 100
            report_lines.append(
                f"  {field:25s}: {non_missing:5d} / {len(df):5d} ({percentage:5.1f}%)"
            )
        else:
            report_lines.append(f"  {field:25s}: Field not present")

    report_lines.append("=" * 70 + "\n")
    return "\n".join(report_lines)
