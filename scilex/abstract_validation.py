"""Advanced abstract quality validation for SciLEx.

This module provides sophisticated abstract quality checks beyond basic length validation:
- Truncation detection (incomplete abstracts)
- Language detection (non-English when English expected)
- Boilerplate detection (generic publisher text)
- Sentence completeness checks
- Quality scoring
"""

import logging
import re
from collections import Counter

import pandas as pd

from scilex.constants import normalize_text_field

# Common truncation indicators
TRUNCATION_PATTERNS = [
    r"\.\.\.$",  # Ends with ...
    r"\.\.\. $",  # Ends with ... and space
    r"\[more\]$",  # Ends with [more]
    r"\[continued\]$",  # Ends with [continued]
    r"\(continued\)$",  # Ends with (continued)
    r" et\.?$",  # Ends with " et" or " et."
    r"\bet al$",  # Ends with "et al" (incomplete citation)
    r"see more at",  # "see more at..."
    r"read more",  # "read more..."
    r"^\[truncated\]",  # Starts with [truncated]
    r"\[truncated\]$",  # Ends with [truncated]
]

# Boilerplate patterns (generic publisher text)
BOILERPLATE_PATTERNS = [
    r"^this (?:paper|article|study) (?:presents|describes|discusses|explores)",
    r"^(?:in|at) this (?:paper|article|study)",
    r"^(?:the|a) (?:paper|article|study) (?:presents|describes|discusses)",
    r"^abstract:?\s*$",  # Just the word "Abstract:"
    r"^no abstract available",
    r"^abstract not available",
    r"^copyright.*all rights reserved",
    r"^©.*all rights reserved",
]

# Patterns indicating incomplete sentences
INCOMPLETE_SENTENCE_PATTERNS = [
    r"[,;:]$",  # Ends with comma, semicolon, or colon
    r"\b(?:and|or|but|however|therefore|thus|hence|moreover|furthermore)$",  # Ends with conjunction
    r"\b(?:the|a|an|of|in|on|at|to|for|with|by|from)$",  # Ends with preposition/article
]

# Precompiled once at import (detectors run once per abstract, thousands of times)
_TRUNCATION_REGEXES = [(p, re.compile(p, re.IGNORECASE)) for p in TRUNCATION_PATTERNS]
_BOILERPLATE_REGEXES = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]
_INCOMPLETE_SENTENCE_REGEXES = [
    re.compile(p, re.IGNORECASE) for p in INCOMPLETE_SENTENCE_PATTERNS
]
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPECIAL_CHAR_RE = re.compile(r'[^\w\s.,;:!?()\-\'"]')
_REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")


# Common English words used by the language heuristic
_COMMON_ENGLISH_WORDS = frozenset(
    {
        "the",
        "be",
        "to",
        "of",
        "and",
        "a",
        "in",
        "that",
        "have",
        "i",
        "it",
        "for",
        "not",
        "on",
        "with",
        "he",
        "as",
        "you",
        "do",
        "at",
        "this",
        "but",
        "his",
        "by",
        "from",
        "they",
        "we",
        "say",
        "her",
        "she",
        "or",
        "an",
        "will",
        "my",
        "one",
        "all",
        "would",
        "there",
        "their",
        "is",
        "are",
        "was",
        "were",
        "been",
        "has",
        "had",
        "having",
    }
)


class AbstractQualityIssue:
    """Represents a quality issue found in an abstract."""

    # Issue severity levels
    CRITICAL = "CRITICAL"  # Abstract unusable
    WARNING = "WARNING"  # Abstract usable but has issues
    INFO = "INFO"  # Minor issue, probably fine

    def __init__(self, issue_type: str, severity: str, description: str):
        self.issue_type = issue_type
        self.severity = severity
        self.description = description

    def __repr__(self):
        return f"[{self.severity}] {self.issue_type}: {self.description}"


class AbstractQualityScore:
    """Represents quality assessment of an abstract."""

    def __init__(self, abstract: str):
        self.abstract = abstract
        self.issues: list[AbstractQualityIssue] = []
        self.quality_score = 100  # Start at 100, deduct for issues

    def add_issue(self, issue: AbstractQualityIssue):
        """Add a quality issue and adjust score."""
        self.issues.append(issue)

        # Deduct points based on severity
        if issue.severity == AbstractQualityIssue.CRITICAL:
            self.quality_score -= 40
        elif issue.severity == AbstractQualityIssue.WARNING:
            self.quality_score -= 15
        else:  # INFO
            self.quality_score -= 5

        # Keep score >= 0
        self.quality_score = max(0, self.quality_score)

    def get_score(self) -> int:
        """Get overall quality score (0-100)."""
        return self.quality_score

    def has_critical_issues(self) -> bool:
        """Check if abstract has critical quality issues."""
        return any(
            issue.severity == AbstractQualityIssue.CRITICAL for issue in self.issues
        )

    def is_acceptable(self, min_score: int = 50) -> bool:
        """Check if abstract quality is acceptable."""
        return self.quality_score >= min_score and not self.has_critical_issues()


def normalize_abstract(abstract) -> str:
    """Normalize abstract text for analysis."""
    text = normalize_text_field(abstract)

    # Clean up whitespace
    text = _WHITESPACE_RE.sub(" ", text).strip()

    return text


def detect_truncation(abstract: str) -> AbstractQualityIssue | None:
    """Detect if abstract appears truncated.

    Returns:
        AbstractQualityIssue if truncation detected, None otherwise
    """
    text = normalize_abstract(abstract)

    if not text:
        return None

    # Check for explicit truncation indicators
    for pattern, regex in _TRUNCATION_REGEXES:
        if regex.search(text):
            return AbstractQualityIssue(
                issue_type="TRUNCATED",
                severity=AbstractQualityIssue.CRITICAL,
                description=f"Abstract appears truncated (matches pattern: {pattern})",
            )

    # Check for incomplete sentences (ends with preposition/conjunction)
    for regex in _INCOMPLETE_SENTENCE_REGEXES:
        if regex.search(text):
            return AbstractQualityIssue(
                issue_type="INCOMPLETE_SENTENCE",
                severity=AbstractQualityIssue.WARNING,
                description="Abstract may end with incomplete sentence",
            )

    return None


def detect_boilerplate(abstract: str) -> AbstractQualityIssue | None:
    """Detect generic publisher boilerplate text.

    Returns:
        AbstractQualityIssue if boilerplate detected, None otherwise
    """
    text = normalize_abstract(abstract).lower()

    if not text:
        return None

    for regex in _BOILERPLATE_REGEXES:
        if regex.search(text):
            return AbstractQualityIssue(
                issue_type="BOILERPLATE",
                severity=AbstractQualityIssue.WARNING,
                description="Abstract contains generic boilerplate text",
            )

    return None


def detect_length_issues(
    abstract: str, min_words: int = 30, max_words: int = 1000
) -> AbstractQualityIssue | None:
    """Detect length-related quality issues.

    Args:
        abstract: Abstract text
        min_words: Minimum acceptable word count
        max_words: Maximum acceptable word count

    Returns:
        AbstractQualityIssue if length issue detected, None otherwise
    """
    text = normalize_abstract(abstract)

    if not text:
        return AbstractQualityIssue(
            issue_type="MISSING",
            severity=AbstractQualityIssue.CRITICAL,
            description="Abstract is missing or empty",
        )

    word_count = len(text.split())

    if word_count < min_words:
        return AbstractQualityIssue(
            issue_type="TOO_SHORT",
            severity=AbstractQualityIssue.WARNING,
            description=f"Abstract too short ({word_count} words, minimum {min_words})",
        )

    if max_words > 0 and word_count > max_words:
        return AbstractQualityIssue(
            issue_type="TOO_LONG",
            severity=AbstractQualityIssue.WARNING,
            description=f"Abstract too long ({word_count} words, maximum {max_words}) - may be full text",
        )

    return None


def detect_language_issues(
    abstract: str, expected_language: str = "english"
) -> AbstractQualityIssue | None:
    """Detect if abstract appears to be in wrong language.

    Uses simple heuristic based on common English words.

    Args:
        abstract: Abstract text
        expected_language: Expected language (currently only "english" supported)

    Returns:
        AbstractQualityIssue if language issue detected, None otherwise
    """
    text = normalize_abstract(abstract)

    if not text or expected_language != "english":
        return None

    words = text.lower().split()
    if len(words) < 10:
        return None  # Too short to reliably detect language

    # Count how many common English words appear
    english_word_count = sum(1 for word in words if word in _COMMON_ENGLISH_WORDS)
    english_word_ratio = english_word_count / len(words)

    # If less than 10% are common English words, likely non-English
    if english_word_ratio < 0.10:
        return AbstractQualityIssue(
            issue_type="LANGUAGE",
            severity=AbstractQualityIssue.INFO,
            description=f"Abstract may not be in English ({english_word_ratio:.1%} common English words)",
        )

    return None


def detect_formatting_issues(abstract: str) -> AbstractQualityIssue | None:
    """Detect formatting problems that indicate data quality issues.

    Returns:
        AbstractQualityIssue if formatting issue detected, None otherwise
    """
    text = normalize_abstract(abstract)

    if not text:
        return None

    # Check for excessive HTML/XML tags
    if _HTML_TAG_RE.search(text):
        return AbstractQualityIssue(
            issue_type="FORMATTING",
            severity=AbstractQualityIssue.WARNING,
            description="Abstract contains HTML/XML tags",
        )

    # Check for excessive special characters (indicates encoding issues)
    special_char_count = len(_SPECIAL_CHAR_RE.findall(text))
    if special_char_count > len(text) * 0.05:  # More than 5% special chars
        return AbstractQualityIssue(
            issue_type="ENCODING",
            severity=AbstractQualityIssue.WARNING,
            description="Abstract may have encoding issues (many special characters)",
        )

    # Check for repeated characters (often indicates errors)
    if _REPEATED_CHAR_RE.search(text):  # Same character repeated 6+ times
        return AbstractQualityIssue(
            issue_type="FORMATTING",
            severity=AbstractQualityIssue.INFO,
            description="Abstract contains repeated characters",
        )

    return None


def validate_abstract_quality(
    abstract: str,
    min_words: int = 30,
    max_words: int = 1000,
    check_language: bool = True,
    expected_language: str = "english",
) -> AbstractQualityScore:
    """Perform comprehensive quality validation on an abstract.

    Args:
        abstract: Abstract text to validate
        min_words: Minimum word count
        max_words: Maximum word count (0 for no limit)
        check_language: Whether to check language
        expected_language: Expected language

    Returns:
        AbstractQualityScore with issues and overall score
    """
    quality = AbstractQualityScore(abstract)

    # Run all checks
    checks = [
        detect_length_issues(abstract, min_words, max_words),
        detect_truncation(abstract),
        detect_boilerplate(abstract),
        detect_formatting_issues(abstract),
    ]

    if check_language:
        checks.append(detect_language_issues(abstract, expected_language))

    # Add all detected issues
    for issue in checks:
        if issue is not None:
            quality.add_issue(issue)

    return quality


_ISSUE_TO_STAT = {
    "TRUNCATED": "truncated",
    "TOO_SHORT": "too_short",
    "TOO_LONG": "too_long",
    "BOILERPLATE": "boilerplate",
    "ENCODING": "encoding_issues",
    "FORMATTING": "encoding_issues",
    "LANGUAGE": "language_issues",
}
_STAT_KEYS = (
    "truncated",
    "too_short",
    "too_long",
    "boilerplate",
    "encoding_issues",
    "language_issues",
)


def validate_dataframe_abstracts(
    df: pd.DataFrame,
    abstract_column: str = "abstract",
    min_quality_score: int = 50,
    generate_report: bool = True,
    min_words: int = 30,
    max_words: int = 1000,
) -> tuple[pd.DataFrame, dict]:
    """Validate abstract quality for all records in DataFrame.

    Each abstract is scored once. A paper is "acceptable" when
    ``AbstractQualityScore.is_acceptable(min_quality_score)`` holds (score at
    or above the threshold and no critical issue); this single definition is
    used both for the statistics and for the ``abstract_quality_acceptable``
    column.

    Args:
        df: DataFrame with paper records
        abstract_column: Name of abstract column
        min_quality_score: Minimum acceptable quality score
        generate_report: Whether to generate report
        min_words: Minimum abstract word count (configured threshold)
        max_words: Maximum abstract word count (0 for no limit)

    Returns:
        (df_with_scores, report_dict): DataFrame with the columns
        ``abstract_quality_score``, ``abstract_quality_issues`` and
        ``abstract_quality_acceptable``, and statistics.
    """
    if len(df) == 0 or abstract_column not in df.columns:
        return df, {}

    qualities = [
        validate_abstract_quality(abstract, min_words=min_words, max_words=max_words)
        for abstract in df[abstract_column]
    ]
    scores = [quality.get_score() for quality in qualities]
    acceptable = [quality.is_acceptable(min_quality_score) for quality in qualities]

    df_result = df.copy()
    df_result["abstract_quality_score"] = scores
    df_result["abstract_quality_issues"] = [
        "; ".join(issue.issue_type for issue in quality.issues) for quality in qualities
    ]
    df_result["abstract_quality_acceptable"] = acceptable

    issue_counts = Counter(
        _ISSUE_TO_STAT[issue.issue_type]
        for quality in qualities
        for issue in quality.issues
        if issue.issue_type in _ISSUE_TO_STAT
    )
    stats = {
        "total": len(df),
        "acceptable": sum(acceptable),
        "poor_quality": len(acceptable) - sum(acceptable),
        **{stat_key: issue_counts[stat_key] for stat_key in _STAT_KEYS},
        "average_score": sum(scores) / len(scores),
    }

    if generate_report:
        logging.info(_generate_abstract_quality_report(stats))

    return df_result, stats


def _generate_abstract_quality_report(stats: dict) -> str:
    """Generate human-readable abstract quality report."""
    report_lines = [
        "\n" + "=" * 70,
        "ABSTRACT QUALITY VALIDATION REPORT",
        "=" * 70,
        f"Total papers analyzed: {stats['total']}",
        f"Acceptable quality: {stats['acceptable']} ({stats['acceptable'] / stats['total'] * 100:.1f}%)",
        f"Poor quality: {stats['poor_quality']} ({stats['poor_quality'] / stats['total'] * 100:.1f}%)",
        f"Average quality score: {stats['average_score']:.1f}/100",
        "",
        "Quality issues detected:",
        f"  - Truncated abstracts: {stats['truncated']}",
        f"  - Too short: {stats['too_short']}",
        f"  - Too long: {stats['too_long']}",
        f"  - Boilerplate text: {stats['boilerplate']}",
        f"  - Encoding/formatting: {stats['encoding_issues']}",
        f"  - Language issues: {stats['language_issues']}",
        "",
        "Interpretation:",
    ]

    if stats["average_score"] >= 80:
        report_lines.append("  ✓ EXCELLENT: Abstract quality is very high")
    elif stats["average_score"] >= 60:
        report_lines.append("  ✓ GOOD: Abstract quality is acceptable")
    elif stats["average_score"] >= 40:
        report_lines.append("  ⚠️  MODERATE: Many abstracts have quality issues")
    else:
        report_lines.append("  ⚠️  POOR: Serious abstract quality problems detected")

    if stats["truncated"] > stats["total"] * 0.1:
        report_lines.append(
            f"  ⚠️  WARNING: {stats['truncated'] / stats['total'] * 100:.1f}% of abstracts are truncated"
        )

    report_lines.append("=" * 70 + "\n")
    return "\n".join(report_lines)


SCORING_COLUMNS = [
    "abstract_quality_score",
    "abstract_quality_issues",
    "abstract_quality_acceptable",
]
