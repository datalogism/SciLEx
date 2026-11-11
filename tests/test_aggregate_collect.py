"""Tests for the citation and text filters (scilex.pipeline.*)."""

from scilex.constants import CitationFilterConfig
from scilex.pipeline.citation_filter import (
    apply_time_aware_citation_filter as _apply_time_aware_citation_filter,
)
from scilex.pipeline.citation_filter import (
    calculate_required_citations as _calculate_required_citations,
)
from scilex.pipeline.text_filter import (
    record_passes_text_filter as _record_passes_text_filter,
)
from scilex.pipeline.tracker import FilteringTracker


# -------------------------------------------------------------------------
# _calculate_required_citations
# -------------------------------------------------------------------------
class TestCalculateRequiredCitations:
    def test_none_returns_grace_period(self):
        assert (
            _calculate_required_citations(None)
            == CitationFilterConfig.GRACE_PERIOD_CITATIONS
        )

    def test_nan_returns_grace_period(self):
        assert (
            _calculate_required_citations(float("nan"))
            == CitationFilterConfig.GRACE_PERIOD_CITATIONS
        )

    def test_grace_period(self):
        """Papers 0-18 months old require 0 citations."""
        assert _calculate_required_citations(0) == 0
        assert _calculate_required_citations(12) == 0
        assert _calculate_required_citations(18) == 0

    def test_early_threshold(self):
        """Papers 18-21 months old require 1+ citations."""
        assert _calculate_required_citations(19) == CitationFilterConfig.EARLY_CITATIONS
        assert _calculate_required_citations(21) == CitationFilterConfig.EARLY_CITATIONS

    def test_medium_threshold(self):
        """Papers 21-24 months old require 3+ citations."""
        assert (
            _calculate_required_citations(22) == CitationFilterConfig.MEDIUM_CITATIONS
        )
        assert (
            _calculate_required_citations(24) == CitationFilterConfig.MEDIUM_CITATIONS
        )

    def test_mature_threshold(self):
        """Papers 24-36 months old start at 5, increase gradually."""
        result = _calculate_required_citations(25)
        assert result >= CitationFilterConfig.MATURE_BASE_CITATIONS

    def test_established_threshold(self):
        """Papers 36+ months require 10+ citations."""
        result = _calculate_required_citations(40)
        assert result >= CitationFilterConfig.ESTABLISHED_BASE_CITATIONS

    def test_very_old_paper(self):
        """Very old papers (60+ months) need even more citations."""
        result_60 = _calculate_required_citations(60)
        result_36 = _calculate_required_citations(37)
        assert result_60 >= result_36

    def test_monotonic_increase(self):
        """Required citations should never decrease as age increases."""
        prev = 0
        for months in range(0, 60, 3):
            current = _calculate_required_citations(months)
            assert current >= prev, f"Decreased at {months} months: {current} < {prev}"
            prev = current


# -------------------------------------------------------------------------
# _record_passes_text_filter
# -------------------------------------------------------------------------
class TestRecordPassesTextFilter:
    def test_keyword_in_title(self):
        record = {"title": "Machine learning for NLP", "abstract": "NA"}
        assert _record_passes_text_filter(record, ["machine learning"]) is True

    def test_keyword_in_abstract(self):
        record = {"title": "A study", "abstract": "We use deep learning techniques."}
        assert _record_passes_text_filter(record, ["deep learning"]) is True

    def test_no_match(self):
        record = {"title": "Biology paper", "abstract": "Protein folding."}
        assert _record_passes_text_filter(record, ["machine learning"]) is False

    def test_empty_keywords_passes(self):
        record = {"title": "Any paper", "abstract": "Any content."}
        assert _record_passes_text_filter(record, []) is True

    def test_dual_keyword_groups_both_match(self):
        record = {
            "title": "Knowledge graph with LLM",
            "abstract": "We combine knowledge graphs and large language models.",
        }
        keyword_groups = [["knowledge graph"], ["LLM", "large language model"]]
        assert (
            _record_passes_text_filter(record, [], keyword_groups=keyword_groups)
            is True
        )

    def test_dual_keyword_groups_only_first_matches(self):
        record = {
            "title": "Knowledge graph survey",
            "abstract": "We survey graph methods.",
        }
        keyword_groups = [["knowledge graph"], ["LLM"]]
        assert (
            _record_passes_text_filter(record, [], keyword_groups=keyword_groups)
            is False
        )

    def test_dual_keyword_groups_one_empty_fallback(self):
        """If one group is empty, falls back to single-group mode."""
        record = {
            "title": "Machine learning paper",
            "abstract": "Deep learning study.",
        }
        keyword_groups = [["machine learning"], []]
        assert (
            _record_passes_text_filter(record, [], keyword_groups=keyword_groups)
            is True
        )

    def test_case_insensitive(self):
        record = {"title": "MACHINE LEARNING Paper", "abstract": "NA"}
        assert _record_passes_text_filter(record, ["machine learning"]) is True


# -------------------------------------------------------------------------
# FilteringTracker
# -------------------------------------------------------------------------
class TestFilteringTracker:
    def test_set_initial(self):
        tracker = FilteringTracker()
        tracker.set_initial(100, "Raw papers")
        assert tracker.initial_count == 100
        assert len(tracker.stages) == 1
        assert tracker.stages[0]["papers"] == 100

    def test_add_stage(self):
        tracker = FilteringTracker()
        tracker.set_initial(100)
        tracker.add_stage("Dedup", 80, "Removed duplicates")
        assert len(tracker.stages) == 2
        assert tracker.stages[1]["papers"] == 80
        assert tracker.stages[1]["removed"] == 20
        assert tracker.stages[1]["removal_rate"] == 20.0

    def test_add_stage_without_initial(self):
        """First add_stage call sets initial if not yet set."""
        tracker = FilteringTracker()
        tracker.add_stage("Initial", 100)
        assert tracker.initial_count == 100

    def test_generate_report(self):
        tracker = FilteringTracker()
        tracker.set_initial(100)
        tracker.add_stage("Dedup", 80)
        tracker.add_stage("Quality", 60)
        report = tracker.generate_report()
        assert "FILTERING PIPELINE SUMMARY" in report
        assert "100" in report
        assert "60" in report

    def test_generate_report_empty(self):
        tracker = FilteringTracker()
        assert "No filtering data" in tracker.generate_report()

    def test_multiple_stages_cumulative(self):
        tracker = FilteringTracker()
        tracker.set_initial(1000)
        tracker.add_stage("Step 1", 800)
        tracker.add_stage("Step 2", 500)
        tracker.add_stage("Step 3", 300)
        report = tracker.generate_report()
        assert "300" in report
        assert "Retention rate" in report


# -------------------------------------------------------------------------
# _apply_time_aware_citation_filter
# -------------------------------------------------------------------------
class TestApplyTimeAwareCitationFilter:
    def _make_df(self, papers):
        import pandas as pd

        return pd.DataFrame(papers)

    def test_recent_paper_passes_with_zero_citations(self):
        """Papers <18 months old should not be filtered."""
        from datetime import date, timedelta

        # Use 90 days ago — unambiguously within the 18-month grace period
        recent_date = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        df = self._make_df([{"DOI": "10.1/a", "nb_citation": "0", "date": recent_date}])
        result = _apply_time_aware_citation_filter(df)
        assert len(result) == 1

    def test_old_paper_with_zero_citations_filtered(self):
        """Papers >36 months old with 0 citations should be removed."""
        df = self._make_df(
            [{"DOI": "10.1/a", "nb_citation": "0", "date": "2020-01-01"}]
        )
        result = _apply_time_aware_citation_filter(df)
        assert len(result) == 0

    def test_no_doi_bypasses_filter(self):
        """Papers without DOI should not be filtered regardless of citations."""
        df = self._make_df([{"DOI": "NA", "nb_citation": "0", "date": "2018-01-01"}])
        result = _apply_time_aware_citation_filter(df)
        assert len(result) == 1

    def test_citation_threshold_column_added(self):
        """The citation_threshold column must be present in output."""
        df = self._make_df(
            [{"DOI": "10.1/a", "nb_citation": "100", "date": "2024-01-01"}]
        )
        result = _apply_time_aware_citation_filter(df)
        assert "citation_threshold" in result.columns

    def test_citation_threshold_value_for_established_paper(self):
        """Papers >36 months old must have threshold >= ESTABLISHED_BASE_CITATIONS."""
        df = self._make_df(
            [{"DOI": "10.1/a", "nb_citation": "100", "date": "2020-01-01"}]
        )
        result = _apply_time_aware_citation_filter(df)
        assert (
            result["citation_threshold"].iloc[0]
            >= CitationFilterConfig.ESTABLISHED_BASE_CITATIONS
        )
