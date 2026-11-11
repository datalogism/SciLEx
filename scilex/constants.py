"""Constants and helper functions for SciLEx.

This module centralizes commonly used constants and provides helper functions
for consistent data validation across the codebase.
"""

import re

import pandas as pd

# Missing value indicator
MISSING_VALUE = "NA"


# Circuit breaker configuration
class CircuitBreakerConfig:
    """Circuit breaker pattern configuration for API resilience."""

    FAILURE_THRESHOLD = 5  # Open circuit after N consecutive failures
    TIMEOUT_SECONDS = 60  # Wait time before attempting retry from OPEN state
    MAX_RETRIES = 3  # Maximum number of retry attempts per request


# Rate limit backoff configuration
class RateLimitBackoffConfig:
    """Rate limit backoff strategies for different APIs."""

    # Default exponential backoff: 2s, 4s, 8s
    DEFAULT_BASE_WAIT = 2
    DEFAULT_USE_EXPONENTIAL = True

    # API-specific configurations
    # Format: {api_name: (base_wait_seconds, use_exponential_backoff)}
    API_SPECIFIC = {
        "DBLP": (30, False),  # DBLP: Fixed 30s wait (no exponential)
        "Springer": (15, True),  # Springer: 15s, 30s, 60s
        "IEEE": (10, True),  # IEEE: 10s, 20s, 40s
        "Elsevier": (20, True),  # Elsevier: 20s, 40s, 80s
        "Arxiv": (30, False),  # Arxiv: fixed 30s — strict rate limits in parallel runs
        "OpenAIRE": (
            15,
            False,
        ),  # OpenAIRE: fixed 15s — 409 Conflict from parallel scroll contexts
        # Others use default (2s exponential)
    }


# Citation filter configuration
class CitationFilterConfig:
    """Time-aware citation filtering thresholds for paper quality assessment."""

    # Age thresholds (in months)
    GRACE_PERIOD_MONTHS = 18  # Very recent papers (0-18 months) - no filtering
    EARLY_THRESHOLD_MONTHS = 21  # Early stage papers (18-21 months)
    MEDIUM_THRESHOLD_MONTHS = 24  # Medium age papers (21-24 months)
    MATURE_THRESHOLD_MONTHS = 36  # Mature papers (24-36 months)

    # Citation count requirements by age group
    GRACE_PERIOD_CITATIONS = 0  # 0-18 months: 0 citations required
    EARLY_CITATIONS = 1  # 18-21 months: 1+ citations required
    MEDIUM_CITATIONS = 3  # 21-24 months: 3+ citations required
    MATURE_BASE_CITATIONS = 5  # 24-36 months: starts at 5, increases to 8
    ESTABLISHED_BASE_CITATIONS = 10  # 36+ months: starts at 10, increases gradually

    # Warning threshold for zero-citation rate
    HIGH_ZERO_CITATION_RATE = 80  # Warn if >80% of papers have 0 citations


class ZoteroConstants:
    """Zotero-related constants."""

    DEFAULT_COLLECTION_NAME = "new_models"
    API_BASE_URL = "https://api.zotero.org"
    WRITE_TOKEN_LENGTH = 32


def is_valid(value) -> bool:
    """Check if a value is not null, NaN, or the missing value string.

    This function provides a consistent way to check for missing data across
    the codebase, handling both string "NA" values and pandas NaN values.

    Args:
        value: The value to check

    Returns:
        bool: True if the value is valid (not missing), False otherwise

    Examples:
        >>> is_valid("some text")
        True
        >>> is_valid("NA")
        False
        >>> is_valid("")
        False
        >>> is_valid(None)
        False
        >>> is_valid(pd.NA)
        False
    """
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return len(value) > 0

    if pd.isna(value):
        return False

    str_value = str(value).strip()
    return str_value != "" and str_value.upper() != MISSING_VALUE.upper()


def is_missing(value) -> bool:
    """Check if a value is missing (null, NaN, or the missing value string).

    This is the inverse of is_valid() for cases where checking for
    missing values is more intuitive.

    Args:
        value: The value to check

    Returns:
        bool: True if the value is missing, False otherwise
    """
    return not is_valid(value)


def safe_str(value, default: str = MISSING_VALUE) -> str:
    """Safely convert a value to string, returning default if value is missing.

    Args:
        value: The value to convert
        default: The default string to return if value is missing

    Returns:
        str: String representation of value, or default if missing
    """
    if is_missing(value):
        return default
    return str(value)


def normalize_text_field(value) -> str:
    """Normalize a text field (abstract, title...) to a plain string.

    Handles the ``{"p": [...]}`` paragraph format returned by some APIs, plain
    lists/tuples (joined with spaces), NaN/None/``"NA"`` (returned as ``""``).
    Case and whitespace are left untouched.

    Args:
        value: Raw field value.

    Returns:
        The text, or ``""`` if missing.
    """
    if is_missing(value):
        return ""
    if isinstance(value, dict):
        value = value.get("p", value)
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    return str(value)


def normalize_path_component(path_component: str) -> str:
    """Remove leading/trailing slashes from path components.

    Ensures os.path.join() works correctly by preventing absolute path behavior
    when config values mistakenly contain leading slashes (e.g., "/aggregated_results.csv").

    Python's os.path.join() treats paths starting with "/" as absolute paths and
    discards all previous path components. This function strips leading and trailing
    slashes to ensure path components are always treated as relative paths.

    Args:
        path_component: Path component from config or user input

    Returns:
        str: Normalized path component without leading/trailing slashes

    Examples:
        >>> normalize_path_component("/aggregated_results.csv")
        'aggregated_results.csv'
        >>> normalize_path_component("collect_name/")
        'collect_name'
        >>> normalize_path_component("/dirname/")
        'dirname'
        >>> normalize_path_component("normal_path")
        'normal_path'
    """
    return path_component.strip("/")


_DOI_PREFIX_PATTERN = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|(?:dx\.)?doi\.org/|doi:)\s*", re.IGNORECASE
)


def normalize_doi(doi) -> str | None:
    """Normalize a DOI to its bare lowercase form.

    Strips whitespace and the ``https://doi.org/``, ``http://dx.doi.org/``,
    ``doi.org/`` and ``doi:`` prefixes (case-insensitive), then lowercases.

    Args:
        doi: DOI string in any common form (may be None, NaN or MISSING_VALUE)

    Returns:
        The normalized DOI, or None if the value is missing/empty.

    Examples:
        >>> normalize_doi("https://doi.org/10.1/ABC")
        '10.1/abc'
        >>> normalize_doi("NA") is None
        True
    """
    stripped = strip_doi_prefix(doi)
    return stripped.lower() if stripped else None


def strip_doi_prefix(doi) -> str | None:
    """Remove the doi.org / ``doi:`` prefix from a DOI, keeping its case.

    Use this where the stored value must stay as the API returned it;
    use ``normalize_doi`` for comparisons and cache keys.

    Args:
        doi: DOI string in any common form (may be None, NaN or MISSING_VALUE)

    Returns:
        The bare DOI, or None if the value is missing/empty.
    """
    if is_missing(doi):
        return None
    stripped = _DOI_PREFIX_PATTERN.sub("", str(doi).strip()).strip()
    return stripped or None


def doi_to_url(doi) -> str | None:
    """Build a resolvable ``https://doi.org/`` URL from a DOI.

    A value that is already a non-doi.org URL is returned unchanged.

    Args:
        doi: DOI string in any common form

    Returns:
        The URL, or None if the DOI is missing.
    """
    stripped = strip_doi_prefix(doi)
    if stripped is None:
        return None
    if stripped.lower().startswith(("http://", "https://")):
        return stripped
    return f"https://doi.org/{stripped}"


_YEAR_PATTERN = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def extract_year(value) -> int | None:
    """Extract a publication year (1800-2099) from a date-like value.

    Args:
        value: int year, ISO date, free-text date, or missing value

    Returns:
        The year as int, or None when no plausible year is found.

    Examples:
        >>> extract_year("2023-05-01")
        2023
        >>> extract_year("NA") is None
        True
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1800 <= value <= 2099 else None
    if is_missing(value):
        return None
    match = _YEAR_PATTERN.search(str(value))
    return int(match.group(1)) if match else None


def split_semicolon_field(value) -> list[str]:
    """Split a ``;``-joined field (authors, tags, keywords) into clean parts.

    Args:
        value: the joined string, or a missing value

    Returns:
        Stripped, non-empty parts in their original order.
    """
    if is_missing(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def parse_archive_apis(value) -> list[str]:
    """Return the API names from an ``archive`` value like ``"OpenAlex*;HAL"``.

    The ``*`` marking the winning source during deduplication is removed.

    Args:
        value: the archive column value, or a missing value

    Returns:
        API names in their original order.
    """
    return [
        name
        for name in (
            part.replace("*", "").strip() for part in split_semicolon_field(value)
        )
        if name
    ]


# Marker files written in each query directory by the collectors (not result pages)
COMPLETE_FILE_NAME = "_complete"  # query fully collected
STATE_FILE_NAME = "_state"  # query started but not finished
QUERY_MARKER_FILES = frozenset({COMPLETE_FILE_NAME, STATE_FILE_NAME})
