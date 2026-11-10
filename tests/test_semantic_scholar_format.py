"""Tests for SemanticScholartoZoteroFormat in scilex/crawlers/aggregate.py"""

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import SemanticScholartoZoteroFormat


def _full_row():
    return {
        "title": "Deep Learning for NLP",
        "authors": [{"name": "Smith J"}, {"name": "Doe A"}],
        "abstract": "This paper presents a deep learning approach.",
        "publication_date": "2022-04-15",
        "DOI": "10.1234/ss.test",
        "url": "https://semanticscholar.org/paper/abc123",
        "paper_id": "abc123",
        "publicationTypes": ["JournalArticle"],
        "open_access_pdf": "https://example.com/paper.pdf",
        "citationCount": 42,
        "referenceCount": 25,
        "journal": None,
        "publicationVenue": None,
        "venue": None,
    }


def _minimal_row():
    return {
        "title": "Test Paper",
        "authors": [],
        "abstract": None,
        "publication_date": None,
        "DOI": None,
        "url": None,
        "paper_id": None,
        "publicationTypes": None,
        "open_access_pdf": None,
        "citationCount": None,
        "referenceCount": None,
        "journal": None,
        "publicationVenue": None,
        "venue": None,
    }


class TestSemanticScholartoZoteroFormat:
    def test_returns_dict(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert isinstance(result, dict)

    def test_archive_always_semantic_scholar(self):
        result = SemanticScholartoZoteroFormat(_minimal_row())
        assert result["archive"] == "SemanticScholar"

    def test_title_extracted(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["title"] == "Deep Learning for NLP"

    def test_authors_joined_semicolon(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert "Smith J" in result["authors"]
        assert "Doe A" in result["authors"]
        assert ";" in result["authors"]

    def test_abstract_extracted(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["abstract"] == "This paper presents a deep learning approach."

    def test_date_extracted(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["date"] == "2022-04-15"

    def test_doi_extracted(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["DOI"] == "10.1234/ss.test"

    def test_doi_cleaned(self):
        row = _full_row()
        row["DOI"] = "https://doi.org/10.1234/ss.test"
        result = SemanticScholartoZoteroFormat(row)
        assert result["DOI"] == "10.1234/ss.test"

    def test_url_extracted(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["url"] == "https://semanticscholar.org/paper/abc123"

    def test_archive_id_from_paper_id(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["archiveID"] == "abc123"

    def test_open_access_pdf_sets_pdf_url_and_rights(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["pdf_url"] == "https://example.com/paper.pdf"
        assert result["rights"] == "open_access"

    def test_citation_count_preserved(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["ss_citation_count"] == 42

    def test_reference_count_preserved(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["ss_reference_count"] == 25

    def test_zero_citation_count_preserved(self):
        row = _full_row()
        row["citationCount"] = 0
        result = SemanticScholartoZoteroFormat(row)
        assert result["ss_citation_count"] == 0

    def test_journal_article_type(self):
        result = SemanticScholartoZoteroFormat(_full_row())
        assert result["itemType"] == "journalArticle"

    def test_conference_type(self):
        row = _full_row()
        row["publicationTypes"] = ["Conference"]
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "conferencePaper"

    def test_book_type(self):
        row = _full_row()
        row["publicationTypes"] = ["Book"]
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "book"

    def test_multiple_types_book_wins(self):
        row = _full_row()
        row["publicationTypes"] = ["Book", "JournalArticle"]
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "book"

    def test_multiple_types_conference_wins_over_journal(self):
        row = _full_row()
        row["publicationTypes"] = ["Conference", "JournalArticle"]
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "conferencePaper"

    def test_no_pub_type_defaults_manuscript(self):
        result = SemanticScholartoZoteroFormat(_minimal_row())
        assert result["itemType"] == "Manuscript"

    def test_empty_pub_types_defaults_manuscript(self):
        row = _minimal_row()
        row["publicationTypes"] = []
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "Manuscript"

    def test_publication_venue_journal(self):
        row = _minimal_row()
        row["publicationVenue"] = {
            "type": "journal",
            "name": "Nature",
            "publisher": "NPG",
            "issn": "1234-5678",
        }
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"
        assert result["journalAbbreviation"] == "Nature"
        assert result["publisher"] == "NPG"

    def test_publication_venue_conference(self):
        row = _minimal_row()
        row["publicationVenue"] = {"type": "conference", "name": "NeurIPS"}
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "conferencePaper"

    def test_venue_fallback_journal(self):
        row = _minimal_row()
        row["venue"] = {"type": "journal", "name": "JMLR"}
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"
        assert result["journalAbbreviation"] == "JMLR"

    def test_journal_field_sets_pages_and_volume(self):
        row = _minimal_row()
        row["journal"] = {"pages": "100-110", "name": "AI Journal", "volume": "5"}
        result = SemanticScholartoZoteroFormat(row)
        assert result["pages"] == "100-110"
        assert result["journalAbbreviation"] == "AI Journal"
        assert result["volume"] == "5"

    def test_journal_with_pages_changes_book_to_book_section(self):
        row = _full_row()
        row["publicationTypes"] = ["Book"]
        row["journal"] = {"pages": "50-60", "name": "Book Journal", "volume": None}
        result = SemanticScholartoZoteroFormat(row)
        assert result["itemType"] == "bookSection"

    def test_no_authors_stays_missing(self):
        result = SemanticScholartoZoteroFormat(_minimal_row())
        assert result["authors"] == MISSING_VALUE

    def test_all_required_keys_present(self):
        result = SemanticScholartoZoteroFormat(_minimal_row())
        for key in ["title", "archive", "itemType", "authors", "date", "DOI"]:
            assert key in result
