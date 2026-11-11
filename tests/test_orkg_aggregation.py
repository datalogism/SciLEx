"""Unit tests for ORKGtoZoteroFormat converter.

Tests cover:
- Full record with all fields populated
- Missing DOI fallback
- URL fallback to ORKG paper page when url field is empty
- Authors joined with ";"
- Missing year handling
- Published_in as string (not dict)
"""

import json
from pathlib import Path

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import ORKGtoZoteroFormat


def _make_row(overrides=None):
    """Build a minimal valid ORKG content entry."""
    row = {
        "id": "R12345",
        "title": "Test Knowledge Graph Paper",
        "identifiers": {"doi": ["10.1234/orkg-test-2023"]},
        "publication_info": {
            "published_year": 2023,
            "published_in": {"id": "V100", "label": "Journal of Web Semantics"},
            "url": "https://www.example.com/paper/123",
        },
        "authors": [
            {"id": "A1", "name": "Emma Wilson"},
            {"id": "A2", "name": "David Chen"},
        ],
    }
    if overrides:
        row.update(overrides)
    return row


class TestORKGAggregation:
    """Test ORKGtoZoteroFormat converter."""

    def test_full_record(self):
        """All standard fields are extracted correctly from a full record."""
        row = _make_row()
        result = ORKGtoZoteroFormat(row)

        assert result["title"] == "Test Knowledge Graph Paper"
        assert result["DOI"] == "10.1234/orkg-test-2023"
        assert result["date"] == "2023"
        assert result["journalAbbreviation"] == "Journal of Web Semantics"
        assert result["url"] == "https://www.example.com/paper/123"
        assert result["authors"] == "Emma Wilson;David Chen"
        assert result["archiveID"] == "R12345"
        assert result["archive"] == "ORKG"
        assert result["itemType"] == "journalArticle"
        # ORKG does not provide abstracts
        assert result["abstract"] == MISSING_VALUE

    def test_missing_doi(self):
        """When no DOI is in identifiers, DOI defaults to MISSING_VALUE."""
        row = _make_row({"identifiers": {}})
        result = ORKGtoZoteroFormat(row)
        assert result["DOI"] == MISSING_VALUE

    def test_doi_empty_list(self):
        """Empty DOI list defaults to MISSING_VALUE."""
        row = _make_row({"identifiers": {"doi": []}})
        result = ORKGtoZoteroFormat(row)
        assert result["DOI"] == MISSING_VALUE

    def test_url_fallback_to_orkg_id(self):
        """When url field is empty, URL is constructed from ORKG paper ID."""
        pub_info = {
            "published_year": 2023,
            "published_in": {"label": "Some Journal"},
            "url": "",
        }
        row = _make_row({"publication_info": pub_info})
        result = ORKGtoZoteroFormat(row)
        assert result["url"] == "https://orkg.org/paper/R12345"

    def test_url_fallback_no_pub_info_url(self):
        """When url key absent from pub_info, URL is constructed from ORKG ID."""
        pub_info = {
            "published_year": 2022,
            "published_in": {"label": "Some Journal"},
        }
        row = _make_row({"publication_info": pub_info})
        result = ORKGtoZoteroFormat(row)
        assert result["url"] == "https://orkg.org/paper/R12345"

    def test_authors_joined(self):
        """Multiple authors are joined with semicolons."""
        row = _make_row(
            {
                "authors": [
                    {"id": "A1", "name": "First Author"},
                    {"id": "A2", "name": "Second Author"},
                    {"id": "A3", "name": "Third Author"},
                ]
            }
        )
        result = ORKGtoZoteroFormat(row)
        assert result["authors"] == "First Author;Second Author;Third Author"

    def test_single_author(self):
        """Single author is set without trailing semicolons."""
        row = _make_row({"authors": [{"id": "A1", "name": "Solo Author"}]})
        result = ORKGtoZoteroFormat(row)
        assert result["authors"] == "Solo Author"

    def test_missing_authors(self):
        """Empty authors list defaults to MISSING_VALUE."""
        row = _make_row({"authors": []})
        result = ORKGtoZoteroFormat(row)
        assert result["authors"] == MISSING_VALUE

    def test_missing_year(self):
        """Missing published_year defaults date to MISSING_VALUE."""
        pub_info = {
            "published_in": {"label": "Test Journal"},
            "url": "https://example.com",
        }
        row = _make_row({"publication_info": pub_info})
        result = ORKGtoZoteroFormat(row)
        assert result["date"] == MISSING_VALUE

    def test_published_in_as_string(self):
        """published_in as plain string (not dict) is used as journal name."""
        pub_info = {
            "published_year": 2021,
            "published_in": "Artificial Intelligence",
            "url": "https://example.com",
        }
        row = _make_row({"publication_info": pub_info})
        result = ORKGtoZoteroFormat(row)
        assert result["journalAbbreviation"] == "Artificial Intelligence"

    def test_itemtype_always_journal_article(self):
        """ORKG has no type field — always returns journalArticle."""
        result = ORKGtoZoteroFormat(_make_row())
        assert result["itemType"] == "journalArticle"

    def test_no_abstract_always_missing(self):
        """Abstract is always MISSING_VALUE (ORKG API does not return abstracts)."""
        result = ORKGtoZoteroFormat(_make_row())
        assert result["abstract"] == MISSING_VALUE

    def test_full_fixture_first_result(self):
        """Parse the first result from the full fixture file."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "orkg" / "search_results.json"
        )
        with open(fixture_path) as f:
            data = json.load(f)

        first_result = data["content"][0]
        result = ORKGtoZoteroFormat(first_result)

        assert result["title"] == "Knowledge Graph Embedding for Link Prediction"
        assert result["DOI"] == "10.1234/orkg-kg-2023"
        assert result["date"] == "2023"
        assert result["journalAbbreviation"] == "Journal of Web Semantics"
        assert "Emma Wilson" in result["authors"]
        assert "David Chen" in result["authors"]
        assert result["archiveID"] == "R12345"
        assert result["archive"] == "ORKG"

    def test_full_fixture_second_result_no_doi_url_fallback(self):
        """Second fixture result: no DOI and empty URL → fallback URL from ORKG ID."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "orkg" / "search_results.json"
        )
        with open(fixture_path) as f:
            data = json.load(f)

        second_result = data["content"][1]
        result = ORKGtoZoteroFormat(second_result)

        assert result["DOI"] == MISSING_VALUE
        assert result["url"] == "https://orkg.org/paper/R67890"
        assert result["archiveID"] == "R67890"
