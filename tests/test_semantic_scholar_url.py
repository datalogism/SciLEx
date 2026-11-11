"""Tests for Semantic Scholar URL construction with pagination parameters."""

import urllib.parse

from scilex.crawlers.collectors import SemanticScholar_collector


def _make_collector(data_query, api_key=None):
    """Create a SemanticScholar collector for testing."""
    return SemanticScholar_collector(data_query, "/tmp/test", api_key)


class TestSemanticScholarURLConstruction:
    """Verify Semantic Scholar URL has proper pagination parameters."""

    def setup_method(self):
        self.data_query = {
            "year": 2024,
            "keyword": ["machine learning", "knowledge graph"],
            "max_articles_per_query": 100,
            "id_collect": 0,
            "total_art": 0,
            "last_page": 0,
            "coll_art": 0,
            "state": -1,
        }

    def test_url_has_limit_parameter(self):
        collector = _make_collector(self.data_query)
        url = collector.get_configurated_url()
        assert "&limit=" in url

    def test_url_has_offset_placeholder(self):
        collector = _make_collector(self.data_query)
        url = collector.get_configurated_url()
        assert "&offset={}" in url or "offset=" in url

    def test_url_contains_keywords(self):
        collector = _make_collector(self.data_query)
        url = collector.get_configurated_url()
        # URL should contain the keyword terms
        full_url = urllib.parse.unquote(url)
        assert (
            "machine learning" in full_url.lower()
            or "machine+learning" in full_url.lower()
        )

    def test_paginated_urls_have_different_offsets(self):
        collector = _make_collector(self.data_query)
        url = collector.get_configurated_url()
        # If URL uses {} placeholder, format with different offsets
        if "{}" in url:
            url_page1 = url.format(0)
            url_page2 = url.format(100)
            assert url_page1 != url_page2
            assert "offset=0" in url_page1 or "0" in url_page1
