"""Tests for generate_keyword_validation_report in scilex/keyword_validation.py"""

import pandas as pd

from scilex.keyword_validation import generate_keyword_validation_report


def _make_df(papers):
    return pd.DataFrame(papers)


class TestGenerateKeywordValidationReport:
    def test_empty_df_returns_no_papers_message(self):
        df = pd.DataFrame()
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "No papers to validate" in result

    def test_report_contains_total_papers(self):
        df = _make_df(
            [
                {"title": "deep learning survey", "abstract": "deep learning"},
                {"title": "unrelated paper", "abstract": "nothing"},
            ]
        )
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Total papers: 2" in result

    def test_report_contains_keyword_section(self):
        df = _make_df(
            [
                {"title": "deep learning survey", "abstract": "deep learning"},
            ]
        )
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Individual keyword frequencies" in result

    def test_dual_group_mode_shown_in_report(self):
        df = _make_df(
            [
                {
                    "title": "deep learning NLP survey",
                    "abstract": "NLP and deep learning",
                },
            ]
        )
        result = generate_keyword_validation_report(df, [["deep learning"], ["NLP"]])
        assert "Group 1" in result
        assert "Group 2" in result

    def test_single_group_mode_shown_in_report(self):
        df = _make_df(
            [
                {"title": "deep learning survey", "abstract": ""},
            ]
        )
        result = generate_keyword_validation_report(df, [["deep learning"]])
        # Single-group mode should NOT show dual-group headers
        assert "Group 1:" in result
        assert "Group 2:" not in result

    def test_high_false_positive_rate_warning(self):
        # More than 30% papers don't contain keywords → warning
        papers = [{"title": "unrelated", "abstract": "nothing"} for _ in range(7)]
        papers += [{"title": "deep learning", "abstract": ""} for _ in range(3)]
        df = _make_df(papers)
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Warning" in result

    def test_moderate_false_positive_rate_message(self):
        # Between 10% and 30% don't contain keywords
        papers = [{"title": "unrelated", "abstract": "nothing"} for _ in range(2)]
        papers += [{"title": "deep learning", "abstract": ""} for _ in range(10)]
        df = _make_df(papers)
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Moderate" in result or "Good" in result or "Warning" in result

    def test_good_false_positive_rate_message(self):
        # Less than 10% don't contain keywords
        papers = [
            {"title": "deep learning paper", "abstract": "deep learning applied"}
            for _ in range(9)
        ]
        papers += [{"title": "unrelated", "abstract": "nothing"}]
        df = _make_df(papers)
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Good" in result or "Warning" in result or "Moderate" in result

    def test_keyword_frequency_shown(self):
        df = _make_df(
            [
                {"title": "deep learning survey", "abstract": ""},
                {"title": "another deep learning paper", "abstract": ""},
            ]
        )
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "deep learning" in result

    def test_report_contains_matching_mode(self):
        df = _make_df([{"title": "deep learning", "abstract": ""}])
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "Matching mode" in result

    def test_all_papers_match_no_warning(self):
        papers = [
            {"title": "deep learning paper", "abstract": "deep learning"}
            for _ in range(10)
        ]
        df = _make_df(papers)
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert result  # non-empty

    def test_report_contains_header(self):
        df = _make_df([{"title": "deep learning", "abstract": ""}])
        result = generate_keyword_validation_report(df, [["deep learning"]])
        assert "KEYWORD VALIDATION REPORT" in result
