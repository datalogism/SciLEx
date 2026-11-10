"""Tests for analysis/report functions in scilex/duplicate_tracking.py"""

import pandas as pd

from scilex.duplicate_tracking import (
    DuplicateSourceAnalyzer,
    analyze_and_report_duplicates,
    analyze_api_metadata_quality,
    generate_itemtype_distribution_report,
    generate_metadata_quality_report,
)


def _make_df(rows=None):
    if rows is None:
        rows = [
            {
                "archive": "SemanticScholar*",
                "DOI": "10.1/a",
                "title": "Paper A",
                "authors": "Author One",
                "date": "2022",
                "abstract": "Some abstract",
                "journalAbbreviation": "J. Test",
                "itemType": "journalArticle",
            },
            {
                "archive": "OpenAlex*",
                "DOI": "10.2/b",
                "title": "Paper B",
                "authors": "Author Two",
                "date": "2021",
                "abstract": "Another abstract",
                "journalAbbreviation": "NA",
                "itemType": "conferencePaper",
            },
            {
                "archive": "SemanticScholar*;OpenAlex",
                "DOI": "10.3/c",
                "title": "Paper C",
                "authors": "Author Three",
                "date": "2020",
                "abstract": "Third abstract",
                "journalAbbreviation": "J. Test",
                "itemType": "journalArticle",
            },
        ]
    return pd.DataFrame(rows)


class TestAnalyzeApiMetadataQuality:
    def test_returns_dict(self):
        df = _make_df()
        result = analyze_api_metadata_quality(df)
        assert isinstance(result, dict)

    def test_known_apis_in_result(self):
        df = _make_df()
        result = analyze_api_metadata_quality(df)
        assert "SemanticScholar" in result or "OpenAlex" in result

    def test_total_papers_counted(self):
        df = _make_df()
        result = analyze_api_metadata_quality(df)
        totals = sum(v["total_papers"] for v in result.values())
        assert totals >= 2

    def test_field_completeness_structure(self):
        df = _make_df()
        result = analyze_api_metadata_quality(df)
        for _api, stats in result.items():
            assert "total_papers" in stats
            assert "field_completeness" in stats

    def test_empty_df_returns_empty_dict(self):
        df = pd.DataFrame()
        result = analyze_api_metadata_quality(df)
        assert result == {}

    def test_missing_archive_skipped(self):
        df = pd.DataFrame([{"archive": "NA", "DOI": "10.1/x", "title": "T"}])
        result = analyze_api_metadata_quality(df)
        assert isinstance(result, dict)


class TestGenerateMetadataQualityReport:
    def test_empty_stats_returns_no_data_message(self):
        result = generate_metadata_quality_report({})
        assert "No metadata quality data available" in result

    def test_report_contains_api_name(self):
        stats = {
            "SemanticScholar": {
                "total_papers": 5,
                "field_completeness": {
                    "DOI": {"count": 4, "percentage": 80.0},
                    "title": {"count": 5, "percentage": 100.0},
                    "authors": {"count": 3, "percentage": 60.0},
                    "date": {"count": 5, "percentage": 100.0},
                    "abstract": {"count": 2, "percentage": 40.0},
                    "journalAbbreviation": {"count": 1, "percentage": 20.0},
                    "itemType": {"count": 5, "percentage": 100.0},
                },
            }
        }
        result = generate_metadata_quality_report(stats)
        assert "SemanticScholar" in result

    def test_report_contains_header(self):
        stats = {
            "TestAPI": {
                "total_papers": 1,
                "field_completeness": {
                    "DOI": {"count": 1, "percentage": 100.0},
                    "title": {"count": 1, "percentage": 100.0},
                    "authors": {"count": 1, "percentage": 100.0},
                    "date": {"count": 1, "percentage": 100.0},
                    "abstract": {"count": 1, "percentage": 100.0},
                    "journalAbbreviation": {"count": 1, "percentage": 100.0},
                    "itemType": {"count": 1, "percentage": 100.0},
                },
            }
        }
        result = generate_metadata_quality_report(stats)
        assert "METADATA QUALITY BY API" in result


class TestGenerateItemtypeDistributionReport:
    def test_empty_df_returns_no_data_message(self):
        result = generate_itemtype_distribution_report(pd.DataFrame())
        assert "No data available" in result

    def test_report_contains_itemtype(self):
        df = _make_df()
        result = generate_itemtype_distribution_report(df)
        assert "journalArticle" in result or "conferencePaper" in result

    def test_report_contains_header(self):
        df = _make_df()
        result = generate_itemtype_distribution_report(df)
        assert "ITEMTYPE DISTRIBUTION BY API" in result

    def test_report_contains_api_name(self):
        df = _make_df()
        result = generate_itemtype_distribution_report(df)
        assert "SemanticScholar" in result or "OpenAlex" in result

    def test_missing_archive_rows_skipped(self):
        df = pd.DataFrame(
            [
                {"archive": "NA", "itemType": "journalArticle"},
                {"archive": "TestAPI*", "itemType": "conferencePaper"},
            ]
        )
        result = generate_itemtype_distribution_report(df)
        assert isinstance(result, str)


class TestAnalyzeAndReportDuplicates:
    def test_returns_tuple(self):
        df = _make_df()
        result = analyze_and_report_duplicates(df, generate_report=False)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_analyzer_instance(self):
        df = _make_df()
        analyzer, _ = analyze_and_report_duplicates(df, generate_report=False)
        assert isinstance(analyzer, DuplicateSourceAnalyzer)

    def test_returns_metadata_quality_dict(self):
        df = _make_df()
        _, metadata_quality = analyze_and_report_duplicates(df, generate_report=False)
        assert isinstance(metadata_quality, dict)

    def test_with_report_generation(self):
        df = _make_df()
        analyzer, _ = analyze_and_report_duplicates(df, generate_report=True)
        assert isinstance(analyzer, DuplicateSourceAnalyzer)
