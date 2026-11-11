"""Tests for scilex.duplicate_tracking module."""

import pandas as pd

from scilex.duplicate_tracking import DuplicateSourceAnalyzer


# -------------------------------------------------------------------------
# DuplicateSourceAnalyzer
# -------------------------------------------------------------------------
class TestDuplicateSourceAnalyzer:
    def test_add_paper(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        assert "doi1" in analyzer.papers_by_api["API1"]
        assert "API1" in analyzer.apis_encountered

    def test_add_paper_multiple_apis(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi1", "API2")
        assert len(analyzer.duplicate_papers["doi1"]) == 2

    def test_get_api_overlap(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi1", "API2")
        analyzer.add_paper("doi2", "API1")
        analyzer.add_paper("doi3", "API2")

        count, pct = analyzer.get_api_overlap("API1", "API2")
        assert count == 1  # doi1 shared
        assert pct == 50.0  # 1 out of min(2,2)

    def test_get_api_overlap_no_shared(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi2", "API2")
        count, pct = analyzer.get_api_overlap("API1", "API2")
        assert count == 0
        assert pct == 0.0

    def test_get_api_overlap_unknown_api(self):
        analyzer = DuplicateSourceAnalyzer()
        count, pct = analyzer.get_api_overlap("API1", "API2")
        assert count == 0
        assert pct == 0.0

    def test_get_api_statistics(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi2", "API1")
        analyzer.add_paper("doi1", "API2")
        analyzer.add_paper("doi3", "API2")

        # Need to calculate unique papers first
        analyzer._calculate_unique_papers()
        all_papers = set()
        for papers in analyzer.papers_by_api.values():
            all_papers.update(papers)
        analyzer.total_unique_papers = len(all_papers)

        stats = analyzer.get_api_statistics()
        assert stats["API1"]["total_papers"] == 2
        assert stats["API1"]["unique_papers"] == 1  # doi2 is unique
        assert stats["API2"]["total_papers"] == 2
        assert stats["API2"]["unique_papers"] == 1  # doi3 is unique

    def test_analyze_from_dataframe(self):
        df = pd.DataFrame(
            [
                {"DOI": "10.1234/a", "title": "Paper A", "archive": "API1;API2*"},
                {"DOI": "10.1234/b", "title": "Paper B", "archive": "API1*"},
                {"DOI": "NA", "title": "Paper C", "archive": "API2*"},
            ]
        )
        analyzer = DuplicateSourceAnalyzer()
        analyzer.analyze_from_dataframe(df)

        assert analyzer.total_papers == 3
        assert "API1" in analyzer.apis_encountered
        assert "API2" in analyzer.apis_encountered

    def test_analyze_from_dataframe_missing_archive(self):
        df = pd.DataFrame(
            [
                {"DOI": "10.1234/a", "title": "Paper A", "archive": "NA"},
                {"DOI": "10.1234/b", "title": "Paper B", "archive": "API1*"},
            ]
        )
        analyzer = DuplicateSourceAnalyzer()
        analyzer.analyze_from_dataframe(df)
        # First row skipped due to NA archive
        assert len(analyzer.apis_encountered) == 1

    def test_generate_report_empty(self):
        analyzer = DuplicateSourceAnalyzer()
        report = analyzer.generate_report()
        assert "No API source information available" in report

    def test_generate_report_with_data(self):
        analyzer = DuplicateSourceAnalyzer()
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi2", "API2")
        analyzer._calculate_unique_papers()
        analyzer.total_unique_papers = 2
        analyzer.total_papers = 2

        report = analyzer.generate_report()
        assert "DUPLICATE SOURCE TRACKING REPORT" in report
        assert "API1" in report
        assert "API2" in report

    def test_get_all_overlaps_sorted(self):
        analyzer = DuplicateSourceAnalyzer()
        # API1 and API2 share 2 papers
        analyzer.add_paper("doi1", "API1")
        analyzer.add_paper("doi1", "API2")
        analyzer.add_paper("doi2", "API1")
        analyzer.add_paper("doi2", "API2")
        # API1 and API3 share 1 paper
        analyzer.add_paper("doi3", "API1")
        analyzer.add_paper("doi3", "API3")

        overlaps = analyzer.get_all_overlaps()
        assert len(overlaps) >= 2
        # First overlap should be the largest
        assert overlaps[0][2] >= overlaps[-1][2]
