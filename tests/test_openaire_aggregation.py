"""Unit tests for OpenAIREtoZoteroFormat converter.

Tests cover:
- Full record with all fields populated
- Missing DOI fallback
- Single author (creator dict → list normalisation)
- Multiple authors (creator list joined with ";")
- Open access rights detection
- ItemType mapping from resourcetype vocabulary
"""

import json
from pathlib import Path

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import OpenAIREtoZoteroFormat


def _make_result(entity_overrides=None):
    """Build a minimal valid OpenAIRE result dict."""
    entity = {
        "title": {"$": "Test Paper Title"},
        "creator": [
            {"$": "John Smith"},
            {"$": "Jane Doe"},
        ],
        "dateofacceptance": {"$": "2023-05-15"},
        "description": {"$": "This is the abstract."},
        "pid": [
            {"@classid": "doi", "$": "10.1234/test-doi"},
        ],
        "journal": {"$": "Test Journal"},
        "language": {"@classid": "eng"},
        "bestaccessright": {"@classname": "Open Access"},
        "resourcetype": {"@classname": "Article"},
        "originalId": "oai:test::001",
        "children": {
            "instance": [{"webresource": {"url": {"$": "https://example.com/paper"}}}]
        },
    }
    if entity_overrides:
        entity.update(entity_overrides)

    return {"metadata": {"oaf:entity": {"oaf:result": entity}}}


class TestOpenAIREAggregation:
    """Test OpenAIREtoZoteroFormat converter."""

    def test_full_record(self):
        """All standard fields are extracted correctly from a full record."""
        row = _make_result()
        result = OpenAIREtoZoteroFormat(row)

        assert result["title"] == "Test Paper Title"
        assert result["DOI"] == "10.1234/test-doi"
        assert result["authors"] == "John Smith;Jane Doe"
        assert result["date"] == "2023-05-15"
        assert result["abstract"] == "This is the abstract."
        assert result["journalAbbreviation"] == "Test Journal"
        assert result["language"] == "eng"
        assert result["rights"] == "open_access"
        assert result["archive"] == "OpenAIRE"
        assert result["archiveID"] == "oai:test::001"
        assert result["url"] == "https://example.com/paper"
        assert result["itemType"] == "journalArticle"

    def test_missing_doi(self):
        """When no DOI is present, DOI field defaults to MISSING_VALUE."""
        row = _make_result({"pid": []})
        result = OpenAIREtoZoteroFormat(row)
        assert result["DOI"] == MISSING_VALUE

    def test_doi_as_url_cleaned(self):
        """DOI in URL format (https://doi.org/...) is cleaned to plain DOI."""
        row = _make_result(
            {"pid": [{"@classid": "doi", "$": "https://doi.org/10.5678/url-doi"}]}
        )
        result = OpenAIREtoZoteroFormat(row)
        assert result["DOI"] == "10.5678/url-doi"

    def test_single_author_dict_normalised(self):
        """Single creator as dict is normalised to a list of one author."""
        row = _make_result({"creator": {"$": "Alice Brown"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["authors"] == "Alice Brown"

    def test_multiple_authors_joined(self):
        """Multiple creators are joined with semicolons."""
        row = _make_result(
            {
                "creator": [
                    {"$": "First Author"},
                    {"$": "Second Author"},
                    {"$": "Third Author"},
                ]
            }
        )
        result = OpenAIREtoZoteroFormat(row)
        assert result["authors"] == "First Author;Second Author;Third Author"

    def test_open_access_rights(self):
        """bestaccessright 'Open Access' maps to rights='open_access'."""
        row = _make_result({"bestaccessright": {"@classname": "Open Access"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["rights"] == "open_access"

    def test_restricted_rights(self):
        """bestaccessright other than 'Open' maps to rights='restricted'."""
        row = _make_result({"bestaccessright": {"@classname": "Restricted"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["rights"] == "restricted"

    def test_itemtype_article(self):
        """resourcetype 'Article' maps to journalArticle."""
        row = _make_result({"resourcetype": {"@classname": "Article"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

    def test_itemtype_conference(self):
        """resourcetype 'Conference object' maps to conferencePaper."""
        row = _make_result({"resourcetype": {"@classname": "Conference object"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "conferencePaper"

    def test_itemtype_book(self):
        """resourcetype 'Book' maps to book."""
        row = _make_result({"resourcetype": {"@classname": "Book"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "book"

    def test_itemtype_book_part(self):
        """resourcetype 'Book part' maps to bookSection."""
        row = _make_result({"resourcetype": {"@classname": "Book part"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "bookSection"

    def test_itemtype_preprint(self):
        """resourcetype 'Preprint' maps to preprint (matches allowed_item_types)."""
        row = _make_result({"resourcetype": {"@classname": "Preprint"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "preprint"

    def test_itemtype_unknown_defaults_to_journalarticle(self):
        """Unknown resourcetype defaults to journalArticle (not Manuscript which is never allowed)."""
        row = _make_result({"resourcetype": {"@classname": "Dataset"}})
        result = OpenAIREtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

    def test_original_id_list_takes_first(self):
        """originalId list uses the first element as archiveID."""
        row = _make_result({"originalId": ["oai:first::001", "oai:second::002"]})
        result = OpenAIREtoZoteroFormat(row)
        assert result["archiveID"] == "oai:first::001"

    def test_pid_list_filters_by_doi_classid(self):
        """Only the pid entry with @classid='doi' is used as DOI."""
        row = _make_result(
            {
                "pid": [
                    {"@classid": "pmid", "$": "12345678"},
                    {"@classid": "doi", "$": "10.9999/correct-doi"},
                    {"@classid": "handle", "$": "hdl:1234/5678"},
                ]
            }
        )
        result = OpenAIREtoZoteroFormat(row)
        assert result["DOI"] == "10.9999/correct-doi"

    def test_url_from_children_instance_list(self):
        """URL is extracted from children.instance list (first valid URL)."""
        row = _make_result(
            {
                "children": {
                    "instance": [
                        {
                            "webresource": {
                                "url": {"$": "https://openaire.eu/paper/001"}
                            }
                        },
                        {"webresource": {"url": {"$": "https://mirror.org/paper/001"}}},
                    ]
                }
            }
        )
        result = OpenAIREtoZoteroFormat(row)
        assert result["url"] == "https://openaire.eu/paper/001"

    def test_url_from_children_instance_dict(self):
        """URL is extracted when children.instance is a single dict (not list)."""
        row = _make_result(
            {
                "children": {
                    "instance": {
                        "webresource": {"url": {"$": "https://openaire.eu/single/001"}}
                    }
                }
            }
        )
        result = OpenAIREtoZoteroFormat(row)
        assert result["url"] == "https://openaire.eu/single/001"

    def test_missing_metadata_returns_defaults(self):
        """Row with no metadata key returns dict with all MISSING_VALUE fields."""
        result = OpenAIREtoZoteroFormat({})
        assert result["archive"] == "OpenAIRE"
        assert result["title"] == MISSING_VALUE
        assert result["DOI"] == MISSING_VALUE
        assert result["authors"] == MISSING_VALUE

    def test_full_fixture_first_result(self):
        """Parse the first result from the full fixture file."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "openaire" / "search_results.json"
        )
        with open(fixture_path) as f:
            data = json.load(f)

        first_result = data["response"]["results"]["result"][0]
        result = OpenAIREtoZoteroFormat(first_result)

        assert result["title"] == "Machine Learning for Knowledge Graph Completion"
        assert result["DOI"] == "10.1234/ml-kg-2023"
        assert "John Smith" in result["authors"]
        assert "Jane Doe" in result["authors"]
        assert result["date"] == "2023-05-15"
        assert (
            result["journalAbbreviation"]
            == "Journal of Artificial Intelligence Research"
        )
        assert result["rights"] == "open_access"
        assert result["itemType"] == "journalArticle"
        assert result["archive"] == "OpenAIRE"
