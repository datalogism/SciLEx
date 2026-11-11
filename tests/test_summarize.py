"""Tests for the scilex.summarize module."""

import pandas as pd

from scilex.summarize.report import generate_report
from scilex.summarize.stats import compute_cluster_stats

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------


def _make_cluster_df():
    """Create a DataFrame with cluster assignments."""
    return pd.DataFrame(
        {
            "DOI": ["10.1/a", "10.1/b", "10.1/c", "10.1/d", "10.1/e"],
            "title": [
                "Knowledge Graph Embeddings",
                "Graph Neural Networks",
                "Metabolomics Analysis",
                "Drug Discovery Pipeline",
                "RDF Link Prediction",
            ],
            "authors": [
                "Smith, John;Doe, Jane",
                "Smith, John;Brown, Bob",
                "Green, Alice;White, Eve",
                "Green, Alice;Black, Tom",
                "Smith, John;Doe, Jane",
            ],
            "date": ["2023-01", "2024-03", "2022-06", "2023-11", "2024-01"],
            "tags": [
                "knowledge graph;embedding",
                "graph;neural network",
                "metabolomics;mass spectrometry",
                "drug discovery;metabolomics",
                "RDF;knowledge graph;link prediction",
            ],
            "cluster_id": [0, 0, 1, 1, 0],
            "pagerank": [0.3, 0.15, 0.25, 0.2, 0.1],
        }
    )


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------


class TestComputeClusterStats:
    def test_returns_stats_per_cluster(self):
        """One ClusterStats per cluster_id."""
        stats = compute_cluster_stats(_make_cluster_df())
        assert len(stats) == 2
        assert stats[0].cluster_id == 0
        assert stats[1].cluster_id == 1

    def test_cluster_sizes(self):
        """Cluster sizes match expected values."""
        stats = compute_cluster_stats(_make_cluster_df())
        assert stats[0].size == 3  # cluster 0: a, b, e
        assert stats[1].size == 2  # cluster 1: c, d

    def test_top_keywords(self):
        """Top keywords extracted from tags column."""
        stats = compute_cluster_stats(_make_cluster_df())
        kw_0 = {kw for kw, _ in stats[0].top_keywords}
        assert "knowledge graph" in kw_0

    def test_top_authors(self):
        """Most frequent authors identified."""
        stats = compute_cluster_stats(_make_cluster_df())
        authors_0 = {a for a, _ in stats[0].top_authors}
        assert "Smith, John" in authors_0

    def test_year_range(self):
        """Year range correctly extracted from date column."""
        stats = compute_cluster_stats(_make_cluster_df())
        yr_min, yr_max = stats[0].year_range
        assert yr_min == 2023
        assert yr_max == 2024

    def test_hub_paper(self):
        """Hub paper is the one with highest PageRank."""
        stats = compute_cluster_stats(_make_cluster_df())
        # In cluster 0, paper "a" has pagerank 0.3 (highest)
        assert stats[0].hub_paper == "Knowledge Graph Embeddings"

    def test_skips_unclustered(self):
        """Papers with cluster_id=-1 are skipped."""
        df = _make_cluster_df()
        df.loc[0, "cluster_id"] = -1
        stats = compute_cluster_stats(df)
        cluster_ids = {s.cluster_id for s in stats}
        assert -1 not in cluster_ids

    def test_empty_dataframe(self):
        """Empty DataFrame returns empty list."""
        stats = compute_cluster_stats(pd.DataFrame())
        assert stats == []


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_report_contains_header(self, tmp_path):
        """Report has a title with collection name."""
        stats = compute_cluster_stats(_make_cluster_df())
        path = str(tmp_path / "report.md")
        report = generate_report(stats, path, collect_name="test_review")
        assert "# Cluster Summary: test_review" in report

    def test_report_contains_mermaid(self, tmp_path):
        """Report includes Mermaid mindmap."""
        stats = compute_cluster_stats(_make_cluster_df())
        path = str(tmp_path / "report.md")
        report = generate_report(stats, path)
        assert "```mermaid" in report
        assert "mindmap" in report

    def test_report_contains_cluster_details(self, tmp_path):
        """Report includes details for each cluster."""
        stats = compute_cluster_stats(_make_cluster_df())
        path = str(tmp_path / "report.md")
        report = generate_report(stats, path)
        assert "### Cluster 0" in report
        assert "### Cluster 1" in report

    def test_report_written_to_file(self, tmp_path):
        """Report is written to the output path."""
        stats = compute_cluster_stats(_make_cluster_df())
        path = str(tmp_path / "report.md")
        generate_report(stats, path)
        with open(path) as f:
            content = f.read()
        assert "Cluster Summary" in content

    def test_empty_stats(self, tmp_path):
        """Empty stats list produces minimal report."""
        path = str(tmp_path / "report.md")
        report = generate_report([], path)
        assert "0 communities" in report


class TestSummaryOnAggregatedColumns:
    """The aggregated CSV has no tags column and many one-paper clusters."""

    def _df(self):
        return pd.DataFrame(
            {
                "title": [
                    "Knowledge Graph Memory for Agents",
                    "Knowledge Graph Reasoning with LLMs",
                    "Unrelated Paper",
                ],
                "collect_keywords": ["Collect_KW1:Graph"] * 3,
                "cluster_id": [0, 0, 1],
                "pagerank": [0.5, 0.3, 0.0],
            }
        )

    def test_keywords_fall_back_to_title_bigrams(self):
        stats = compute_cluster_stats(self._df())
        assert stats[0].top_keywords[0] == ("knowledge graph", 2)

    def test_one_paper_communities_are_left_out(self, tmp_path):
        stats = compute_cluster_stats(self._df())
        report = generate_report(stats, str(tmp_path / "report.md"))
        assert "**1 communities**" in report
        assert "1 papers without links" in report
        assert "### Cluster 1" not in report
        assert "Cluster 0: knowledge graph" in report
