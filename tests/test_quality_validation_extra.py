"""Additional tests for scilex/quality_validation.py — apply_quality_filters, completeness report."""

import pandas as pd

from scilex.quality_validation import (
    QualityReport,
    apply_quality_filters,
    generate_data_completeness_report,
)


def _paper(
    doi="10.1/a",
    abstract="A long enough abstract with sufficient words to pass the check",
    date="2022",
    rights="open-access",
    authors="Smith J;Doe A",
):
    return {
        "DOI": doi,
        "abstract": abstract,
        "date": date,
        "rights": rights,
        "authors": authors,
        "title": "Test paper",
        "journalAbbreviation": "J.Test",
        "volume": "1",
        "issue": "1",
        "publisher": "Pub",
    }


class TestApplyQualityFilters:
    def test_empty_df_returns_empty(self):
        df = pd.DataFrame()
        result, report = apply_quality_filters(df, {})
        assert result.empty

    def test_no_filters_returns_all(self):
        df = pd.DataFrame([_paper(), _paper(doi="10.2/b")])
        result, report = apply_quality_filters(df, {})
        assert len(result) == 2

    def test_require_doi_removes_missing(self):
        rows = [_paper(), _paper(doi="NA")]
        df = pd.DataFrame(rows)
        result, report = apply_quality_filters(df, {"require_doi": True})
        assert len(result) == 1

    def test_require_abstract_removes_missing(self):
        rows = [_paper(), _paper(abstract="NA")]
        df = pd.DataFrame(rows)
        result, report = apply_quality_filters(df, {"require_abstract": True})
        assert len(result) == 1

    def test_min_abstract_words_filter(self):
        short = _paper(abstract="too short")
        long = _paper(
            doi="10.2/b",
            abstract="this is a very long abstract with many words and content",
        )
        df = pd.DataFrame([short, long])
        result, _ = apply_quality_filters(df, {"min_abstract_words": 5})
        assert len(result) == 1

    def test_require_year_removes_missing_date(self):
        rows = [_paper(), _paper(doi="10.2/b", date="NA")]
        df = pd.DataFrame(rows)
        result, _ = apply_quality_filters(df, {"require_year": True})
        assert len(result) == 1

    def test_validate_year_range_removes_outside(self):
        rows = [_paper(date="2022"), _paper(doi="10.2/b", date="2015")]
        df = pd.DataFrame(rows)
        result, _ = apply_quality_filters(
            df,
            {
                "validate_year_range": True,
                "year_range": [2020, 2021, 2022, 2023],
            },
        )
        assert len(result) == 1

    def test_require_open_access_filter(self):
        # quality_validation checks rights.lower() in ["open", "true"]
        rows = [_paper(rights="open"), _paper(doi="10.2/b", rights="closed")]
        df = pd.DataFrame(rows)
        result, _ = apply_quality_filters(df, {"require_open_access": True})
        assert len(result) == 1

    def test_min_author_count_filter(self):
        rows = [
            _paper(authors="Smith J;Doe A;Lee B"),
            _paper(doi="10.2/b", authors="Smith J"),
        ]
        df = pd.DataFrame(rows)
        result, _ = apply_quality_filters(df, {"min_author_count": 2})
        assert len(result) == 1

    def test_report_returned_is_quality_report(self):
        df = pd.DataFrame([_paper()])
        _, report = apply_quality_filters(df, {})
        assert isinstance(report, QualityReport)

    def test_report_total_papers_correct(self):
        df = pd.DataFrame([_paper(), _paper(doi="10.2/b")])
        _, report = apply_quality_filters(df, {})
        assert report.total_papers == 2

    def test_generate_report_false_no_error(self):
        df = pd.DataFrame([_paper()])
        result, report = apply_quality_filters(df, {}, generate_report=False)
        assert len(result) == 1


class TestGenerateDataCompletenessReport:
    def test_empty_df_returns_no_papers_message(self):
        result = generate_data_completeness_report(pd.DataFrame())
        assert "No papers to analyze" in result

    def test_report_contains_total_papers(self):
        df = pd.DataFrame([_paper(), _paper(doi="10.2/b")])
        result = generate_data_completeness_report(df)
        assert "Total papers: 2" in result

    def test_report_contains_field_names(self):
        df = pd.DataFrame([_paper()])
        result = generate_data_completeness_report(df)
        assert "DOI" in result
        assert "title" in result
        assert "abstract" in result

    def test_report_header_present(self):
        df = pd.DataFrame([_paper()])
        result = generate_data_completeness_report(df)
        assert "DATA COMPLETENESS REPORT" in result

    def test_missing_columns_show_not_present(self):
        df = pd.DataFrame([{"DOI": "10.1/a", "title": "Test"}])
        result = generate_data_completeness_report(df)
        assert "Field not present" in result

    def test_returns_string(self):
        df = pd.DataFrame([_paper()])
        result = generate_data_completeness_report(df)
        assert isinstance(result, str)
