"""Unit tests for the OpenAIRE collector.

Tests cover:
- URL construction (single/dual keyword groups)
- Year filter parameters
- Page result parsing (full fixture, single result dict→list, empty results)
- Page offset (1-based page numbers)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from scilex.crawlers.collectors import OpenAIRE_collector


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


class TestOpenAIRECollector:
    """Test OpenAIRE collector functionality."""

    def setup_method(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures" / "openaire"
        self.single_keywords = [["machine learning"]]
        self.dual_keywords = [["knowledge graph"], ["biomedical"]]

    def test_url_construction_single_keyword(self):
        """URL includes encoded keyword and year filter parameters."""
        data_query = _make_data_query(self.single_keywords, year=2023)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        url_template = collector.get_configurated_url()

        assert "machine%20learning" in url_template
        assert "fromDateAccepted=2023-01-01" in url_template
        assert "toDateAccepted=2023-12-31" in url_template
        assert "format=json" in url_template
        assert "{}" in url_template  # page placeholder

    def test_url_construction_dual_keywords(self):
        """URL joins keywords from both groups with a space."""
        data_query = _make_data_query(self.dual_keywords, year=2022)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        url_template = collector.get_configurated_url()

        # Both keyword group values should appear in the encoded query
        assert "knowledge" in url_template
        assert "graph" in url_template
        assert "biomedical" in url_template

    def test_url_year_filter(self):
        """FromDateAccepted and toDateAccepted use the configured year."""
        data_query = _make_data_query([["nlp"]], year=2024)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        url_template = collector.get_configurated_url()

        assert "fromDateAccepted=2024-01-01" in url_template
        assert "toDateAccepted=2024-12-31" in url_template

    def test_page_offset_returns_page(self):
        """get_offset() returns the page number unchanged (1-based)."""
        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)

        assert collector.get_offset(1) == 1
        assert collector.get_offset(2) == 2
        assert collector.get_offset(5) == 5

    def test_parse_page_results_full(self):
        """Parsing the full fixture returns correct total and two results."""
        fixture_path = self.fixtures_dir / "search_results.json"
        with open(fixture_path) as f:
            fixture_data = json.load(f)

        mock_response = MagicMock()
        mock_response.json.return_value = fixture_data

        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        page_data = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 2
        assert len(page_data["results"]) == 2
        assert page_data["page"] == 1
        assert page_data["id_collect"] == 0

    def test_parse_page_results_single_result_normalised_to_list(self):
        """When 'result' is a dict (single item), it is normalised to a list."""
        # Build a response where result is a single dict, not a list
        single_result = {
            "response": {
                "header": {"total": {"$": "1"}},
                "results": {
                    "result": {
                        "header": {"dri:objIdentifier": {"$": "test::001"}},
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {"title": {"$": "Single Paper"}}
                            }
                        },
                    }
                },
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = single_result

        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        page_data = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 1
        assert isinstance(page_data["results"], list)
        assert len(page_data["results"]) == 1

    def test_parse_page_results_empty(self):
        """Empty response returns total=0 and empty results list."""
        empty_response = {"response": {"header": {"total": {"$": "0"}}, "results": {}}}

        mock_response = MagicMock()
        mock_response.json.return_value = empty_response

        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        page_data = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 0
        assert page_data["results"] == []

    def test_api_name(self):
        """Collector uses 'OpenAIRE' as api_name for filesystem directories."""
        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        assert collector.api_name == "OpenAIRE"

    def test_max_by_page(self):
        """Default page size is 100."""
        data_query = _make_data_query(self.single_keywords)
        collector = OpenAIRE_collector(data_query, "/tmp", None)
        assert collector.max_by_page == 100
