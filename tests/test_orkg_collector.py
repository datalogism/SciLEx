"""Unit tests for the ORKG collector.

Tests cover:
- URL construction
- 0-based page offset
- Page result parsing (full fixture, empty results)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from scilex.crawlers.collectors import ORKG_collector


def _make_data_query(keywords, year=2023):
    return {
        "keyword": keywords,
        "year": year,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


class TestORKGCollector:
    """Test ORKG collector functionality."""

    def setup_method(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures" / "orkg"
        self.single_keywords = [["knowledge graph"]]
        self.dual_keywords = [["semantic web"], ["ontology"]]

    def test_url_construction_single_keyword(self):
        """URL includes encoded keyword query and page placeholder."""
        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        url_template = collector.get_configurated_url()

        assert "title=knowledge%20graph" in url_template
        assert "?q=" not in url_template  # ORKG ignores q and returns everything
        assert "size=" in url_template
        assert "{}" in url_template

    def test_url_construction_dual_keywords(self):
        """URL joins keywords from both groups."""
        data_query = _make_data_query(self.dual_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        url_template = collector.get_configurated_url()

        assert "semantic" in url_template
        assert "web" in url_template
        assert "ontology" in url_template

    def test_page_offset_zero_indexed(self):
        """get_offset() returns 0-based index (page - 1)."""
        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)

        assert collector.get_offset(1) == 0
        assert collector.get_offset(2) == 1
        assert collector.get_offset(5) == 4

    def test_parse_page_results(self):
        """Parsing the full fixture returns correct total and three results."""
        fixture_path = self.fixtures_dir / "search_results.json"
        with open(fixture_path) as f:
            fixture_data = json.load(f)

        mock_response = MagicMock()
        mock_response.json.return_value = fixture_data

        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        page_data = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 3
        assert len(page_data["results"]) == 3
        assert page_data["page"] == 1
        assert page_data["id_collect"] == 0

    def test_parse_empty_results(self):
        """Empty content list returns total from page metadata and empty results."""
        empty_response = {
            "page": {"total_elements": 0, "total_pages": 0, "number": 0, "size": 25},
            "content": [],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = empty_response

        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        page_data = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 0
        assert page_data["results"] == []

    def test_api_name(self):
        """Collector uses 'ORKG' as api_name for filesystem directories."""
        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        assert collector.api_name == "ORKG"

    def test_max_by_page(self):
        """Default page size is 25 (ORKG recommended)."""
        data_query = _make_data_query(self.single_keywords)
        collector = ORKG_collector(data_query, "/tmp", None)
        assert collector.max_by_page == 25
