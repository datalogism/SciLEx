"""Tests for the scilex.keyword_suggestions module."""

import os

import pandas as pd
import yaml

from scilex.keyword_suggestions.extractor import extract_suggestions
from scilex.keyword_suggestions.report import generate_keyword_report

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------


def _make_cluster_df():
    return pd.DataFrame(
        {
            "DOI": ["10.1/a", "10.1/b", "10.1/c", "10.1/d"],
            "title": [
                "Knowledge Graph Embeddings for Drug Discovery",
                "Graph Neural Networks for Molecular Property",
                "Metabolomics Data Analysis Pipeline",
                "Knowledge Graph Completion Methods",
            ],
            "tags": [
                "knowledge graph;embedding;link prediction",
                "graph neural network;molecular",
                "metabolomics;mass spectrometry",
                "knowledge graph;completion;embedding",
            ],
            "cluster_id": [0, 0, 1, 0],
        }
    )


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------


class TestExtractSuggestions:
    def test_excludes_existing_keywords(self):
        """Terms already in config should not be suggested."""
        existing = ["knowledge graph", "embedding"]
        suggestions = extract_suggestions(_make_cluster_df(), existing, min_freq=1)
        terms = {s["term"] for s in suggestions}
        assert "knowledge graph" not in terms
        assert "embedding" not in terms

    def test_returns_new_terms(self):
        """Terms not in config should be suggested."""
        suggestions = extract_suggestions(
            _make_cluster_df(), existing_keywords=[], min_freq=1
        )
        terms = {s["term"] for s in suggestions}
        assert "knowledge graph" in terms

    def test_frequency_sorting(self):
        """Suggestions sorted by frequency descending."""
        suggestions = extract_suggestions(_make_cluster_df(), [], min_freq=1)
        freqs = [s["frequency"] for s in suggestions]
        assert freqs == sorted(freqs, reverse=True)

    def test_min_freq_filter(self):
        """Only terms with freq >= min_freq are returned."""
        suggestions = extract_suggestions(_make_cluster_df(), [], min_freq=2)
        for s in suggestions:
            assert s["frequency"] >= 2

    def test_top_k_limit(self):
        """No more than top_k suggestions returned."""
        suggestions = extract_suggestions(_make_cluster_df(), [], top_k=3, min_freq=1)
        assert len(suggestions) <= 3

    def test_cluster_ids_tracked(self):
        """Each suggestion should have cluster_ids."""
        suggestions = extract_suggestions(_make_cluster_df(), [], min_freq=1)
        for s in suggestions:
            assert isinstance(s["cluster_ids"], list)
            assert all(isinstance(c, int) for c in s["cluster_ids"])

    def test_title_bigrams_included(self):
        """Bigrams from titles should appear as suggestions."""
        suggestions = extract_suggestions(_make_cluster_df(), [], min_freq=1)
        terms = {s["term"] for s in suggestions}
        # "knowledge graph" appears in both tags and title bigrams
        assert "knowledge graph" in terms

    def test_empty_dataframe(self):
        """Empty DataFrame returns no suggestions."""
        suggestions = extract_suggestions(pd.DataFrame(), [])
        assert suggestions == []

    def test_case_insensitive_exclusion(self):
        """Existing keywords should be excluded case-insensitively."""
        existing = ["Knowledge Graph"]
        suggestions = extract_suggestions(_make_cluster_df(), existing, min_freq=1)
        terms = {s["term"].lower() for s in suggestions}
        assert "knowledge graph" not in terms


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------


class TestGenerateKeywordReport:
    def _make_suggestions(self):
        return [
            {"term": "graph neural network", "frequency": 5, "cluster_ids": [0, 1]},
            {"term": "link prediction", "frequency": 3, "cluster_ids": [0]},
        ]

    def test_markdown_report(self, tmp_path):
        """Markdown report contains suggestions table."""
        md_path, _ = generate_keyword_report(
            self._make_suggestions(), str(tmp_path), "test"
        )
        with open(md_path) as f:
            content = f.read()
        assert "graph neural network" in content
        assert "| Term |" in content

    def test_yaml_report(self, tmp_path):
        """YAML report is parsable and contains terms."""
        _, yml_path = generate_keyword_report(
            self._make_suggestions(), str(tmp_path), "test"
        )
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert "graph neural network" in data["search"]["bonus_keywords"]

    def test_empty_suggestions(self, tmp_path):
        """Empty suggestions produce minimal reports."""
        md_path, yml_path = generate_keyword_report([], str(tmp_path))
        assert os.path.exists(md_path)
        assert os.path.exists(yml_path)
        with open(md_path) as f:
            assert "0 new terms" in f.read()


def test_configured_keywords_flattens_groups_and_bonus():
    from scilex.keyword_suggestions import configured_keywords

    config = {
        "keywords": [["knowledge graph", "KG"], ["metabolomics"]],
        "bonus_keywords": ["LC-MS"],
    }
    assert configured_keywords(config) == [
        "knowledge graph",
        "KG",
        "metabolomics",
        "LC-MS",
    ]
    assert configured_keywords({"keywords": "a, b"}) == ["a", "b"]
    assert configured_keywords({}) == []


class TestSuggestionNoise:
    def _df(self, titles):
        return pd.DataFrame({"title": titles, "cluster_id": [0] * len(titles)})

    def test_stopword_breaks_bigram(self):
        from scilex.keyword_suggestions.extractor import title_bigrams

        bigrams = title_bigrams("Unifying Language Models and Knowledge Graphs")
        assert "models knowledge" not in bigrams
        assert "knowledge graphs" in bigrams

    def test_hyphenated_word_stays_whole(self):
        from scilex.keyword_suggestions.extractor import title_bigrams

        assert title_bigrams("Long-Term Memory for Agents") == ["long-term memory"]

    def test_punctuation_breaks_bigram(self):
        from scilex.keyword_suggestions.extractor import title_bigrams

        assert "graphs survey" not in title_bigrams("Knowledge Graphs: Survey Paper")

    def test_plural_of_existing_keyword_is_excluded(self):
        df = self._df(["Knowledge Graphs Today", "Knowledge Graphs Tomorrow"])
        terms = [s["term"] for s in extract_suggestions(df, ["knowledge graph"])]
        assert "knowledge graphs" not in terms

    def test_singular_and_plural_are_merged(self):
        df = self._df(["Neural Networks Now", "Neural Network Later"])
        suggestions = extract_suggestions(df, [], min_freq=2)
        assert [
            (s["term"], s["frequency"]) for s in suggestions if "neural" in s["term"]
        ] == [("neural networks", 2)]
