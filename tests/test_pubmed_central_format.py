"""Tests for PubMedCentraltoZoteroFormat in scilex/crawlers/aggregate.py"""

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import PubMedCentraltoZoteroFormat


def _minimal_row():
    return {}


def _full_row():
    return {
        "title": "Test PMC Article",
        "authors": ["Smith J", "Doe A"],
        "abstract": "This is a test abstract for PMC.",
        "doi": "10.1234/pmc.test",
        "pmc_id": "PMC12345",
        "pmid": "987654",
        "date": "2023-06-15",
        "journal": "Test Journal",
        "volume": "10",
        "issue": "3",
        "pages": "100-110",
        "publisher": "Test Publisher",
        "language": "eng",
    }


class TestPubMedCentraltoZoteroFormat:
    def test_returns_dict(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert isinstance(result, dict)

    def test_archive_always_pubmedcentral(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert result["archive"] == "PubMedCentral"

    def test_rights_always_open_access(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert result["rights"] == "open-access"

    def test_itemtype_always_journal_article(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert result["itemType"] == "journalArticle"

    def test_title_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["title"] == "Test PMC Article"

    def test_authors_list_joined_with_semicolon(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["authors"] == "Smith J;Doe A"

    def test_authors_string_preserved(self):
        row = _full_row()
        row["authors"] = "Smith J;Doe A"
        result = PubMedCentraltoZoteroFormat(row)
        assert result["authors"] == "Smith J;Doe A"

    def test_abstract_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["abstract"] == "This is a test abstract for PMC."

    def test_doi_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["DOI"] == "10.1234/pmc.test"

    def test_pmc_id_generates_url(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert "PMC12345" in result["url"]
        assert "ncbi.nlm.nih.gov" in result["url"]

    def test_pmc_id_generates_pdf_url(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert "PMC12345" in result["pdf_url"]
        assert "pdf" in result["pdf_url"]

    def test_archive_id_from_pmc_id(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["archiveID"] == "PMC12345"

    def test_pmid_fallback_when_no_pmc_id(self):
        row = _full_row()
        del row["pmc_id"]
        result = PubMedCentraltoZoteroFormat(row)
        assert result["archiveID"] == "987654"
        assert "pubmed.ncbi.nlm.nih.gov" in result["url"]

    def test_date_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["date"] == "2023-06-15"

    def test_journal_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["journalAbbreviation"] == "Test Journal"

    def test_volume_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["volume"] == "10"

    def test_issue_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["issue"] == "3"

    def test_pages_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["pages"] == "100-110"

    def test_publisher_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["publisher"] == "Test Publisher"

    def test_language_extracted(self):
        result = PubMedCentraltoZoteroFormat(_full_row())
        assert result["language"] == "eng"

    def test_missing_title_stays_missing(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert result["title"] == MISSING_VALUE

    def test_missing_doi_stays_missing(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        assert result["DOI"] == MISSING_VALUE

    def test_non_pmc_pmc_id_no_pdf_url(self):
        row = _full_row()
        row["pmc_id"] = "12345"  # doesn't start with PMC
        result = PubMedCentraltoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE

    def test_all_required_keys_present(self):
        result = PubMedCentraltoZoteroFormat(_minimal_row())
        required = [
            "title",
            "publisher",
            "itemType",
            "authors",
            "language",
            "abstract",
            "archiveID",
            "archive",
            "date",
            "DOI",
            "url",
            "pdf_url",
            "rights",
            "pages",
            "journalAbbreviation",
            "volume",
            "serie",
            "issue",
            "tags",
        ]
        for key in required:
            assert key in result
