"""Unit tests for dual keyword logic in collectors.

These tests verify that each collector properly implements AND logic
between dual keyword groups, ensuring papers match keywords from BOTH groups.
"""

import urllib.parse

from scilex.crawlers.collectors import (
    Arxiv_collector,
    DBLP_collector,
    Elsevier_collector,
    Filter_param,
    HAL_collector,
    IEEE_collector,
    Istex_collector,
    OpenAlex_collector,
    SemanticScholar_collector,
    Springer_collector,
)


class TestDualKeywordLogic:
    """Test that collectors enforce AND logic between dual keyword groups."""

    def setup_method(self):
        """Setup test fixtures."""
        # Dual keyword groups: ["knowledge graph", "LLM"]
        # This represents (Group1: knowledge graph) AND (Group2: LLM)
        self.dual_keywords = ["knowledge graph", "LLM"]
        self.year = 2024
        self.data_query = {
            "keyword": self.dual_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }
        self.filter_param = Filter_param(self.year, self.dual_keywords)

    def test_semantic_scholar_uses_and_logic(self):
        """Test SemanticScholar uses + (AND) operator, not | (OR)."""
        collector = SemanticScholar_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("query", [""])[0]

        # Should use + for AND, not | for OR
        assert "+" in query_string, "SemanticScholar should use + for AND logic"
        assert "|" not in query_string, "SemanticScholar should not use | (OR logic)"

        # Should have both keywords
        assert "knowledge graph" in query_string or "knowledge-graph" in query_string
        assert "LLM" in query_string

    def test_openalex_uses_and_logic(self):
        """Test OpenAlex uses comma (AND) between keywords."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Check filter parameter
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        filter_string = query_params.get("filter", [""])[0]

        # Should have separate quoted title_and_abstract.search for each keyword
        assert 'title_and_abstract.search:"knowledge graph"' in filter_string, (
            "OpenAlex should search for 'knowledge graph' as an exact phrase"
        )
        assert 'title_and_abstract.search:"LLM"' in filter_string, (
            "OpenAlex should search for 'LLM' as an exact phrase"
        )

        # Should use comma to separate (AND logic)
        keyword_filters = [
            f for f in filter_string.split(",") if "title_and_abstract" in f
        ]
        assert len(keyword_filters) >= 2, (
            "OpenAlex should have separate filters for each keyword"
        )

    def test_dblp_preserves_phrases(self):
        """Test DBLP uses hyphens to preserve multi-word phrases."""
        collector = DBLP_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Check query parameter
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("q", [""])[0]

        # Should use hyphens for multi-word phrases
        assert "knowledge-graph" in query_string, (
            "DBLP should use hyphen for 'knowledge graph' phrase"
        )

        # Should have both keywords (may start with space or +)
        assert "knowledge-graph" in query_string
        assert "LLM" in query_string

    def test_ieee_uses_and_logic(self):
        """Test IEEE uses AND operator between keywords."""
        collector = IEEE_collector(self.data_query, "/tmp/test", "fake_api_key")
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("querytext", [""])[0]

        # Should use AND
        assert " AND " in query_string, "IEEE should use AND logic"

        # Should have both keywords
        assert "knowledge graph" in query_string
        assert "LLM" in query_string

    def test_elsevier_view_depends_on_inst_token(self):
        """COMPLETE view needs an institutional token; a plain key gets STANDARD."""
        plain = Elsevier_collector(self.data_query, "/tmp/test", "fake_api_key")
        assert "view=STANDARD" in plain.get_configurated_url()
        with_token = Elsevier_collector(
            self.data_query, "/tmp/test", "fake_api_key", "fake_inst_token"
        )
        assert "view=COMPLETE" in with_token.get_configurated_url()

    def test_elsevier_uses_and_logic(self):
        """Test Elsevier uses AND operator between keywords."""
        collector = Elsevier_collector(self.data_query, "/tmp/test", "fake_api_key")
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("query", [""])[0]

        # Should use AND in TITLE-ABS query
        assert " AND " in query_string, "Elsevier should use AND logic"
        assert "TITLE-ABS" in query_string

        # Should have both keywords
        assert "knowledge graph" in query_string
        assert "LLM" in query_string

    def test_springer_uses_and_logic(self):
        """Test Springer uses AND operator between keywords."""
        collector = Springer_collector(self.data_query, "/tmp/test", "fake_api_key")
        urls = collector._get_api_endpoints()  # meta + openaccess URL templates

        # Check first URL (meta)
        parsed = urllib.parse.urlparse(urls[0])
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("q", [""])[0]

        # Should use AND
        assert " AND " in query_string, "Springer should use AND logic"

        # Should have both keywords with quotes
        assert '"knowledge graph"' in query_string
        assert '"LLM"' in query_string

    def test_hal_uses_and_logic(self):
        """Test HAL uses AND operator between keywords."""
        collector = HAL_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("q", [""])[0]

        # Should use %20AND%20 (URL-encoded AND)
        assert "%20AND%20" in query_string or " AND " in query_string, (
            "HAL should use AND logic"
        )

        # Should have both keywords
        assert "knowledge" in query_string.lower()
        assert "llm" in query_string.lower()

    def test_arxiv_uses_and_logic(self):
        """Test Arxiv uses AND operator between keyword groups."""
        collector = Arxiv_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("search_query", [""])[0]

        # Should use AND between keyword groups (may be +AND+ or ' AND ')
        decoded_query = urllib.parse.unquote(query_string)
        assert " AND " in decoded_query or "+AND+" in query_string, (
            "Arxiv should use AND logic between keywords"
        )

        # Should have both keywords
        assert "knowledge" in decoded_query.lower()
        assert "llm" in decoded_query.lower()

    def test_istex_uses_and_logic(self):
        """Test Istex uses AND operator between keywords."""
        collector = Istex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        # Decode URL to check query
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_string = query_params.get("q", [""])[0]

        # Should use %20AND%20 (URL-encoded AND)
        assert "%20AND%20" in query_string or " AND " in query_string, (
            "Istex should use AND logic"
        )

        # Should have both keywords
        assert "knowledge" in query_string.lower()
        assert "llm" in query_string.lower()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
