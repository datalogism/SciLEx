"""Tests for scilex.quality_validation module."""

from scilex.quality_validation import (
    QualityReport,
    count_authors,
    count_words,
    passes_quality_filters,
    validate_abstract,
)


# -------------------------------------------------------------------------
# count_words
# -------------------------------------------------------------------------
class TestCountWords:
    def test_simple_sentence(self):
        assert count_words("hello world") == 2

    def test_longer_text(self):
        assert count_words("one two three four five") == 5

    def test_na_returns_zero(self):
        assert count_words("NA") == 0

    def test_none_returns_zero(self):
        assert count_words(None) == 0

    def test_empty_string_returns_zero(self):
        assert count_words("") == 0

    def test_dict_format(self):
        text = {"p": ["First paragraph here.", "Second paragraph."]}
        assert count_words(text) == 5

    def test_whitespace_only(self):
        # "   " splits into empty strings, but split() handles it
        assert count_words("   ") == 0


# -------------------------------------------------------------------------
# count_authors
# -------------------------------------------------------------------------
class TestCountAuthors:
    def test_semicolon_separated(self):
        assert count_authors("Alice;Bob;Charlie") == 3

    def test_single_author(self):
        assert count_authors("Alice Smith") == 1

    def test_na_returns_zero(self):
        assert count_authors("NA") == 0

    def test_none_returns_zero(self):
        assert count_authors(None) == 0

    def test_list_format(self):
        assert count_authors(["Alice", "Bob"]) == 2

    def test_empty_list(self):
        assert count_authors([]) == 0

    def test_last_first_format(self):
        """Single author in 'Last, First' format."""
        assert count_authors("Smith, John") == 1

    def test_multiple_comma_separated(self):
        """Multiple authors with commas (ambiguous format)."""
        # "Smith, John, Doe, Jane" has 3 commas -> (3+1)//2 = 2
        assert count_authors("Smith, John, Doe, Jane") == 2

    def test_empty_string(self):
        assert count_authors("") == 0

    def test_semicolon_with_spaces(self):
        assert count_authors("Alice Smith ; Bob Jones ; Charlie") == 3


# -------------------------------------------------------------------------
# validate_abstract
# -------------------------------------------------------------------------
class TestValidateAbstract:
    def test_valid_abstract(self):
        abstract = " ".join(["word"] * 100)
        is_valid, reason = validate_abstract(abstract, min_words=50, max_words=500)
        assert is_valid is True
        assert reason == ""

    def test_missing_abstract(self):
        is_valid, reason = validate_abstract("NA", min_words=50, max_words=500)
        assert is_valid is False
        assert reason == "missing_abstract"

    def test_too_short(self):
        abstract = "Short abstract."
        is_valid, reason = validate_abstract(abstract, min_words=50, max_words=500)
        assert is_valid is False
        assert reason == "abstract_too_short"

    def test_too_long(self):
        abstract = " ".join(["word"] * 600)
        is_valid, reason = validate_abstract(abstract, min_words=50, max_words=500)
        assert is_valid is False
        assert reason == "abstract_too_long"

    def test_min_zero_disables_check(self):
        is_valid, reason = validate_abstract("Short.", min_words=0, max_words=500)
        assert is_valid is True

    def test_max_zero_disables_check(self):
        abstract = " ".join(["word"] * 2000)
        is_valid, reason = validate_abstract(abstract, min_words=0, max_words=0)
        assert is_valid is True

    def test_none_abstract(self):
        is_valid, reason = validate_abstract(None, min_words=50, max_words=500)
        assert is_valid is False


# -------------------------------------------------------------------------
# passes_quality_filters
# -------------------------------------------------------------------------
class TestPassesQualityFilters:
    def _make_record(self, **overrides):
        defaults = {
            "DOI": "10.1234/test",
            "abstract": " ".join(["word"] * 100),
            "date": "2024-01-15",
            "authors": "Alice;Bob",
            "rights": "open",
        }
        defaults.update(overrides)
        return defaults

    def test_passes_all_filters(self):
        record = self._make_record()
        filters = {
            "require_doi": True,
            "require_abstract": True,
            "min_abstract_words": 50,
            "require_year": True,
        }
        passes, reason = passes_quality_filters(record, filters)
        assert passes is True
        assert reason == ""

    def test_fails_missing_doi(self):
        record = self._make_record(DOI="NA")
        filters = {"require_doi": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "missing_doi"

    def test_fails_empty_doi(self):
        """Whitespace-only DOI is caught by is_missing check as missing_doi."""
        record = self._make_record(DOI="   ")
        filters = {"require_doi": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "missing_doi"

    def test_fails_missing_abstract(self):
        record = self._make_record(abstract="NA")
        filters = {"require_abstract": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "missing_abstract"

    def test_fails_short_abstract(self):
        record = self._make_record(abstract="Too short.")
        filters = {"min_abstract_words": 50}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "abstract_too_short"

    def test_fails_missing_year(self):
        record = self._make_record(date="NA")
        filters = {"require_year": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "missing_year"

    def test_fails_outside_year_range(self):
        record = self._make_record(date="2020-01-01")
        filters = {"validate_year_range": True, "year_range": [2023, 2024]}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "outside_year_range"

    def test_passes_within_year_range(self):
        record = self._make_record(date="2024-01-01")
        filters = {"validate_year_range": True, "year_range": [2023, 2024]}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is True

    def test_fails_not_open_access(self):
        record = self._make_record(rights="closed")
        filters = {"require_open_access": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "not_open_access"

    def test_passes_open_access(self):
        record = self._make_record(rights="open")
        filters = {"require_open_access": True}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is True

    def test_fails_insufficient_authors(self):
        record = self._make_record(authors="Solo Author")
        filters = {"min_author_count": 2}
        passes, reason = passes_quality_filters(record, filters)
        assert passes is False
        assert reason == "insufficient_authors"

    def test_no_filters_passes(self):
        record = self._make_record()
        passes, reason = passes_quality_filters(record, {})
        assert passes is True

    def test_invalid_year_format_silently_passes(self):
        """Non-numeric year prefix silently passes (isdigit check fails, no error)."""
        record = self._make_record(date="not-a-date")
        filters = {"validate_year_range": True, "year_range": [2023, 2024]}
        passes, reason = passes_quality_filters(record, filters)
        # "not".isdigit() is False so year extraction is skipped entirely
        assert passes is True


# -------------------------------------------------------------------------
# QualityReport
# -------------------------------------------------------------------------
class TestQualityReport:
    def test_initial_state(self):
        report = QualityReport()
        assert report.total_papers == 0
        assert report.papers_kept == 0
        assert report.papers_filtered == 0

    def test_add_kept(self):
        report = QualityReport()
        report.add_kept()
        assert report.papers_kept == 1

    def test_add_filtered(self):
        report = QualityReport()
        report.add_filtered("missing_doi")
        assert report.papers_filtered == 1
        assert report.filter_reasons["missing_doi"] == 1

    def test_unknown_reason_ignored(self):
        report = QualityReport()
        report.add_filtered("unknown_reason")
        assert report.papers_filtered == 1

    def test_generate_report_empty(self):
        report = QualityReport()
        assert report.generate_report() == "No papers processed."

    def test_generate_report_with_data(self):
        report = QualityReport()
        report.total_papers = 10
        report.add_kept()
        report.add_kept()
        report.add_filtered("missing_doi")
        result = report.generate_report()
        assert "QUALITY VALIDATION REPORT" in result
        assert "Missing Doi" in result
