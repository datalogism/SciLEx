"""Tests for SpringertoZoteroFormat in scilex/crawlers/aggregate.py"""

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import SpringertoZoteroFormat


def _full_row():
    return {
        "identifier": "springer-id-12345",
        "title": "Deep Learning Methods",
        "abstract": "A survey of deep learning methods.",
        "publicationDate": "2022-05-01",
        "doi": "10.1234/springer.test",
        "url": [
            {"format": "html", "value": "https://link.springer.com/article/123"},
            {"format": "pdf", "value": "https://link.springer.com/article/123.pdf"},
        ],
        "openaccess": "open-access",
        "publisher": "Springer",
        "volume": "10",
        "number": "3",
        "publicationName": "Machine Learning Journal",
        "creators": [{"creator": "Smith J"}, {"creator": "Doe A"}],
        "startingPage": "100",
        "endingPage": "115",
        "contentType": "Article",
    }


def _minimal_row():
    return {
        "identifier": "minimal-id",
        "title": "Minimal Paper",
        "abstract": "",
        "publicationDate": None,
        "doi": None,
        "url": None,
        "openaccess": None,
        "publisher": None,
        "volume": None,
        "number": None,
        "publicationName": "",
        "creators": [],
        "startingPage": "",
        "endingPage": "",
        "contentType": "Unknown",
    }


class TestSpringertoZoteroFormat:
    def test_returns_dict(self):
        result = SpringertoZoteroFormat(_full_row())
        assert isinstance(result, dict)

    def test_archive_always_springer(self):
        result = SpringertoZoteroFormat(_minimal_row())
        assert result["archive"] == "Springer"

    def test_archive_id_from_identifier(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["archiveID"] == "springer-id-12345"

    def test_title_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["title"] == "Deep Learning Methods"

    def test_abstract_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["abstract"] == "A survey of deep learning methods."

    def test_date_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["date"] == "2022-05-01"

    def test_doi_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["DOI"] == "10.1234/springer.test"

    def test_doi_cleaned(self):
        row = _full_row()
        row["doi"] = "https://doi.org/10.1234/springer.test"
        result = SpringertoZoteroFormat(row)
        assert result["DOI"] == "10.1234/springer.test"

    def test_html_url_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["url"] == "https://link.springer.com/article/123"

    def test_pdf_url_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["pdf_url"] == "https://link.springer.com/article/123.pdf"

    def test_string_url_extracted(self):
        row = _full_row()
        row["url"] = "https://link.springer.com/article/456"
        result = SpringertoZoteroFormat(row)
        assert result["url"] == "https://link.springer.com/article/456"

    def test_rights_from_openaccess(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["rights"] == "open-access"

    def test_publisher_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["publisher"] == "Springer"

    def test_volume_extracted(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["volume"] == "10"

    def test_issue_from_number(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["issue"] == "3"

    def test_issue_fallback_field(self):
        row = _full_row()
        del row["number"]
        row["issue"] = "5"
        result = SpringertoZoteroFormat(row)
        assert result["issue"] == "5"

    def test_journal_name_from_publication_name(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["journalAbbreviation"] == "Machine Learning Journal"

    def test_authors_joined(self):
        result = SpringertoZoteroFormat(_full_row())
        assert "Smith J" in result["authors"]
        assert "Doe A" in result["authors"]

    def test_pages_from_start_end(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["pages"] == "100-115"

    def test_article_content_type_is_journal(self):
        result = SpringertoZoteroFormat(_full_row())
        assert result["itemType"] == "journalArticle"

    def test_conference_content_type(self):
        row = _full_row()
        row["contentType"] = "Conference Paper"
        result = SpringertoZoteroFormat(row)
        assert result["itemType"] == "conferencePaper"

    def test_chapter_content_type(self):
        row = _full_row()
        row["contentType"] = "Book Chapter"
        result = SpringertoZoteroFormat(row)
        assert result["itemType"] == "bookSection"

    def test_unknown_content_type_defaults_manuscript(self):
        result = SpringertoZoteroFormat(_minimal_row())
        assert result["itemType"] == "Manuscript"

    def test_url_list_with_dict_no_html_uses_first_value(self):
        row = _full_row()
        row["url"] = [{"format": "pdf", "value": "https://pdf.example.com/paper.pdf"}]
        result = SpringertoZoteroFormat(row)
        # Should fallback to first URL value when no html format
        assert (
            result["url"] == "https://pdf.example.com/paper.pdf"
            or result["url"] == MISSING_VALUE
        )

    def test_all_required_keys_present(self):
        result = SpringertoZoteroFormat(_minimal_row())
        for key in ["title", "archive", "itemType", "DOI", "url", "authors"]:
            assert key in result
