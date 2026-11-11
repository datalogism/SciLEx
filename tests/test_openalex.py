"""Unit tests for OpenAlex collector and aggregation format."""

import urllib.parse
from unittest.mock import MagicMock

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import OpenAlextoZoteroFormat
from scilex.crawlers.collectors import OpenAlex_collector


class TestOpenAlexCollectorURL:
    """Test URL construction for OpenAlex collector."""

    def setup_method(self):
        self.data_query = {
            "keyword": ["knowledge graph", "LLM"],
            "year": 2024,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

    def test_url_uses_title_and_abstract_search(self):
        """URL must use title_and_abstract.search, not display_name.search."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        assert "title_and_abstract.search:" in url
        assert "display_name.search:" not in url

    def test_url_has_no_page_parameter(self):
        """URL should not contain &page= (cursor pagination instead)."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)

        assert "page" not in query_params, (
            "URL should not have page param (cursor pagination used instead)"
        )

    def test_url_has_per_page(self):
        """URL should include per-page parameter."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        assert "per-page=200" in url

    def test_api_key_appended_as_api_key(self):
        """A real key is sent as api_key= (otherwise OpenAlex answers 401)."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", "abc123KEY")
        url = collector.get_configurated_url()

        assert "api_key=abc123KEY" in url
        assert "mailto=" not in url

    def test_email_value_appended_as_mailto(self):
        """An email address (old configs) is still sent as mailto=."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", "user@example.org")
        url = collector.get_configurated_url()

        assert "mailto=user%40example.org" in url or "mailto=user@example.org" in url
        assert "api_key=" not in url

    def test_no_mailto_when_no_key(self):
        """URL should not include mailto when api_key is not configured."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = collector.get_configurated_url()

        assert "mailto=" not in url
        assert "api_key=" not in url


class TestOpenAlexParsePageResults:
    """Test parsePageResults returns cursor."""

    def setup_method(self):
        self.data_query = {
            "keyword": ["test"],
            "year": 2024,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

    def test_returns_next_cursor(self):
        """ParsePageResults should return (page_data, next_cursor) tuple."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "meta": {"count": 100, "next_cursor": "abc123"},
            "results": [{"id": "W1"}, {"id": "W2"}],
        }

        page_data, next_cursor = collector.parsePageResults(mock_response, 1)

        assert page_data["total"] == 100
        assert len(page_data["results"]) == 2
        assert next_cursor == "abc123"

    def test_returns_none_cursor_on_last_page(self):
        """ParsePageResults should return None cursor when no more pages."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "meta": {"count": 2, "next_cursor": None},
            "results": [{"id": "W1"}],
        }

        page_data, next_cursor = collector.parsePageResults(mock_response, 1)

        assert next_cursor is None


class TestOpenAlexToZoteroFormat:
    """Test OpenAlex aggregation format with primary_location.source."""

    def _make_row(self, **overrides):
        """Create a minimal OpenAlex result row with defaults."""
        row = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1234/test",
            "title": "Test Paper",
            "publication_date": "2024-01-15",
            "language": "en",
            "type": "journal-article",
            "open_access": {"is_oa": True},
            "authorships": [
                {"author": {"display_name": "John Doe"}},
            ],
            "biblio": {
                "volume": "10",
                "issue": "2",
                "first_page": "100",
                "last_page": "110",
            },
            "primary_location": None,
            "best_oa_location": None,
            "abstract_inverted_index": None,
            "cited_by_count": None,
        }
        row.update(overrides)
        return row

    def test_reads_publisher_from_primary_location_source(self):
        """Should extract publisher from primary_location.source.host_organization_name."""
        row = self._make_row(
            primary_location={
                "source": {
                    "display_name": "Nature",
                    "type": "journal",
                    "host_organization_name": "Springer Nature",
                    "issn_l": "0028-0836",
                }
            }
        )
        result = OpenAlextoZoteroFormat(row)

        assert result["publisher"] == "Springer Nature"
        assert result["journalAbbreviation"] == "Nature"
        assert result["serie"] == "0028-0836"
        assert result["itemType"] == "journalArticle"

    def test_reads_conference_from_primary_location_source(self):
        """Should extract conference name from source with type=conference."""
        row = self._make_row(
            type="proceedings-article",
            primary_location={
                "source": {
                    "display_name": "ACL 2024",
                    "type": "conference",
                    "host_organization_name": "ACL",
                    "issn_l": None,
                }
            },
        )
        result = OpenAlextoZoteroFormat(row)

        assert result["conferenceName"] == "ACL 2024"
        assert result["itemType"] == "conferencePaper"
        assert result["publisher"] == "ACL"

    def test_reads_repository_source_as_journal_abbreviation(self):
        """Should set journalAbbreviation from repository source (preprint servers)."""
        row = self._make_row(
            type="article",
            primary_location={
                "source": {
                    "display_name": "bioRxiv",
                    "type": "repository",
                    "host_organization_name": "Cold Spring Harbor Laboratory",
                    "issn_l": None,
                }
            },
        )
        result = OpenAlextoZoteroFormat(row)

        assert result["journalAbbreviation"] == "bioRxiv"
        assert result["publisher"] == "Cold Spring Harbor Laboratory"

    def test_extracts_cited_by_count(self):
        """Should extract cited_by_count as oa_citation_count."""
        row = self._make_row(cited_by_count=42)
        result = OpenAlextoZoteroFormat(row)

        assert result["oa_citation_count"] == 42

    def test_no_cited_by_count_when_none(self):
        """Should not add oa_citation_count when cited_by_count is None."""
        row = self._make_row(cited_by_count=None)
        result = OpenAlextoZoteroFormat(row)

        assert "oa_citation_count" not in result

    def test_handles_missing_primary_location(self):
        """Should handle missing primary_location gracefully (no crash)."""
        row = self._make_row(primary_location=None)
        result = OpenAlextoZoteroFormat(row)

        assert result["publisher"] == MISSING_VALUE
        assert result["journalAbbreviation"] == MISSING_VALUE

    def test_handles_null_source_in_primary_location(self):
        """Should handle primary_location with null source gracefully."""
        row = self._make_row(primary_location={"source": None})
        result = OpenAlextoZoteroFormat(row)

        assert result["publisher"] == MISSING_VALUE

    def test_repository_does_not_overwrite_existing_journal(self):
        """Repository source should not overwrite journalAbbreviation if already set."""
        # This row has type=journal-article which does NOT set journalAbbreviation
        # by default. But if the source has a journal type AND a repository fallback,
        # only the journal name should be set.
        row = self._make_row(
            type="journal-article",
            primary_location={
                "source": {
                    "display_name": "arXiv",
                    "type": "repository",
                    "host_organization_name": "Cornell University",
                    "issn_l": None,
                }
            },
        )
        result = OpenAlextoZoteroFormat(row)
        # Repository should fill journalAbbreviation since it was MISSING_VALUE
        assert result["journalAbbreviation"] == "arXiv"

    def test_zero_cited_by_count(self):
        """Should extract cited_by_count=0 (not treat as falsy)."""
        row = self._make_row(cited_by_count=0)
        result = OpenAlextoZoteroFormat(row)

        assert result["oa_citation_count"] == 0


class TestApiKeySanitization:
    """Test that API keys are redacted from log output."""

    def setup_method(self):
        self.data_query = {
            "keyword": ["test"],
            "year": 2024,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

    def test_sanitize_url_redacts_api_key_with_underscore(self):
        """_sanitize_url must redact api_key= (OpenAlex format)."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = "https://api.openalex.org/works?filter=x&api_key=SECRET123"
        sanitized = collector._sanitize_url(url)

        assert "SECRET123" not in sanitized
        assert "api_key=***REDACTED***" in sanitized

    def test_sanitize_url_redacts_apiKey_camelcase(self):
        """_sanitize_url must also redact apiKey= (camelCase format)."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = "https://example.com/api?apiKey=MY_SECRET"
        sanitized = collector._sanitize_url(url)

        assert "MY_SECRET" not in sanitized
        assert "apiKey=***REDACTED***" in sanitized

    def test_sanitize_url_preserves_non_sensitive_params(self):
        """_sanitize_url should not touch non-sensitive parameters."""
        collector = OpenAlex_collector(self.data_query, "/tmp/test", None)
        url = "https://api.openalex.org/works?filter=test&per-page=200&api_key=SECRET"
        sanitized = collector._sanitize_url(url)

        assert "filter=test" in sanitized
        assert "per-page=200" in sanitized
        assert "SECRET" not in sanitized


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
