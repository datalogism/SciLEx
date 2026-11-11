"""Unit tests for PubMed aggregation (format conversion).

Tests cover:
- PubMedtoZoteroFormat() field mapping
- PMCID handling (present vs absent)
- PDF URL propagation
- MeSH terms as tags
- ItemType conversion
"""

from scilex.constants import MISSING_VALUE, is_valid
from scilex.crawlers.aggregate import PubMedtoZoteroFormat


class TestPubMedAggregation:
    """Test PubMed to Zotero format conversion."""

    def test_article_with_pmcid(self):
        """Test conversion of article with PMCID (open access with PDF)."""
        pubmed_row = {
            "pmid": "12345678",
            "pmcid": "PMC9876543",
            "doi": "10.1093/database/baad001",
            "title": "Machine learning approaches for biomedical knowledge graphs",
            "abstract": "BACKGROUND: Machine learning has revolutionized biomedical research. METHODS: We applied deep learning.",
            "authors": ["Smith John", "Doe Jane"],
            "journal": "Database (Oxford)",
            "date": "2024-01-15",
            "volume": "21",
            "issue": "3",
            "pages": "123-145",
            "publication_type": "Journal Article",
            "mesh_terms": ["Machine Learning", "Knowledge Bases"],
            "pdf_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/pdf/",
            "language": "eng",
        }

        result = PubMedtoZoteroFormat(pubmed_row)

        # Check archive
        assert result["archive"] == "PubMed"

        # Check identifiers
        assert result["archiveID"] == "12345678"
        assert result["DOI"] == "10.1093/database/baad001"
        assert result["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

        # Check PDF URL is preserved
        assert (
            result["pdf_url"]
            == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/pdf/"
        )

        # Check open access rights
        assert result["rights"] == "open-access"

        # Check basic metadata
        assert (
            result["title"]
            == "Machine learning approaches for biomedical knowledge graphs"
        )
        assert result["abstract"] == pubmed_row["abstract"]
        assert result["authors"] == "Smith John;Doe Jane"

        # Check journal fields
        assert result["journalAbbreviation"] == "Database (Oxford)"
        assert result["date"] == "2024-01-15"
        assert result["volume"] == "21"
        assert result["issue"] == "3"
        assert result["pages"] == "123-145"

        # Check itemType mapping
        assert result["itemType"] == "journalArticle"

        # Check language
        assert result["language"] == "eng"

        # Check MeSH terms as tags
        assert result["tags"] == "Machine Learning;Knowledge Bases"

    def test_article_without_pmcid(self):
        """Test conversion of article without PMCID (paywalled, no PDF)."""
        pubmed_row = {
            "pmid": "23456789",
            "pmcid": "",
            "doi": "10.1038/s41586-024-07146-0",
            "title": "Deep learning for drug discovery: a comprehensive review",
            "abstract": "Deep learning has transformed drug discovery pipelines.",
            "authors": ["Johnson Alice"],
            "journal": "Nature",
            "date": "2024-02-01",
            "volume": "625",
            "issue": "7994",
            "pages": "234-256",
            "publication_type": "Review",
            "mesh_terms": ["Machine Learning", "Drug Discovery"],
            "pdf_url": "",
            "language": "eng",
        }

        result = PubMedtoZoteroFormat(pubmed_row)

        # Check archive
        assert result["archive"] == "PubMed"

        # Check identifiers
        assert result["archiveID"] == "23456789"
        assert result["DOI"] == "10.1038/s41586-024-07146-0"
        assert result["url"] == "https://pubmed.ncbi.nlm.nih.gov/23456789/"

        # Check NO PDF URL (paywalled)
        assert result["pdf_url"] == MISSING_VALUE

        # Check NO open access rights
        assert result["rights"] == MISSING_VALUE

        # Check itemType mapping (Review → journalArticle)
        assert result["itemType"] == "journalArticle"

        # Check MeSH terms
        assert result["tags"] == "Machine Learning;Drug Discovery"

    def test_itemtype_mapping(self):
        """Test publication_type to itemType mapping."""
        # Journal Article
        row = {"pmid": "123", "publication_type": "Journal Article"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

        # Review
        row = {"pmid": "124", "publication_type": "Review"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

        # Book
        row = {"pmid": "125", "publication_type": "Book"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "book"

        # Book Chapter
        row = {"pmid": "126", "publication_type": "Book Chapter"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "bookSection"

        # Unknown type (default to journalArticle)
        row = {"pmid": "127", "publication_type": "Unknown Type"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

        # Missing publication_type
        row = {"pmid": "128"}
        result = PubMedtoZoteroFormat(row)
        assert result["itemType"] == "journalArticle"

    def test_mesh_terms_handling(self):
        """Test MeSH terms conversion to semicolon-separated tags."""
        # Multiple MeSH terms
        row = {
            "pmid": "123",
            "mesh_terms": ["Machine Learning", "Knowledge Bases", "Drug Discovery"],
        }
        result = PubMedtoZoteroFormat(row)
        assert result["tags"] == "Machine Learning;Knowledge Bases;Drug Discovery"

        # Single MeSH term
        row = {"pmid": "124", "mesh_terms": ["Machine Learning"]}
        result = PubMedtoZoteroFormat(row)
        assert result["tags"] == "Machine Learning"

        # No MeSH terms
        row = {"pmid": "125", "mesh_terms": []}
        result = PubMedtoZoteroFormat(row)
        assert result["tags"] == MISSING_VALUE

        # Missing mesh_terms field
        row = {"pmid": "126"}
        result = PubMedtoZoteroFormat(row)
        assert result["tags"] == MISSING_VALUE

    def test_authors_handling(self):
        """Test author list conversion."""
        # List of authors
        row = {"pmid": "123", "authors": ["Smith John", "Doe Jane", "Johnson Alice"]}
        result = PubMedtoZoteroFormat(row)
        assert result["authors"] == "Smith John;Doe Jane;Johnson Alice"

        # Single author
        row = {"pmid": "124", "authors": ["Smith John"]}
        result = PubMedtoZoteroFormat(row)
        assert result["authors"] == "Smith John"

        # Empty list
        row = {"pmid": "125", "authors": []}
        result = PubMedtoZoteroFormat(row)
        assert result["authors"] == MISSING_VALUE

        # String instead of list (edge case)
        row = {"pmid": "126", "authors": "Smith John"}
        result = PubMedtoZoteroFormat(row)
        assert result["authors"] == "Smith John"

        # Missing authors field
        row = {"pmid": "127"}
        result = PubMedtoZoteroFormat(row)
        assert result["authors"] == MISSING_VALUE

    def test_missing_values_handling(self):
        """Test handling of missing/empty fields."""
        # Minimal article (only PMID)
        row = {"pmid": "12345678"}
        result = PubMedtoZoteroFormat(row)

        # Should have PMID and URL
        assert result["archiveID"] == "12345678"
        assert result["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

        # Should have archive
        assert result["archive"] == "PubMed"

        # Everything else should be MISSING_VALUE
        assert result["title"] == MISSING_VALUE
        assert result["abstract"] == MISSING_VALUE
        assert result["DOI"] == MISSING_VALUE
        assert result["pdf_url"] == MISSING_VALUE
        assert result["rights"] == MISSING_VALUE
        assert result["authors"] == MISSING_VALUE
        assert result["journalAbbreviation"] == MISSING_VALUE
        assert result["volume"] == MISSING_VALUE
        assert result["issue"] == MISSING_VALUE
        assert result["pages"] == MISSING_VALUE
        assert result["tags"] == MISSING_VALUE

        # Default itemType
        assert result["itemType"] == "journalArticle"

    def test_pdf_url_validation(self):
        """Test PDF URL is only set when valid."""
        # Valid PDF URL
        row = {
            "pmid": "123",
            "pmcid": "PMC9876543",
            "pdf_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/pdf/",
        }
        result = PubMedtoZoteroFormat(row)
        assert is_valid(result["pdf_url"])
        assert result["rights"] == "open-access"

        # Empty PDF URL
        row = {"pmid": "124", "pmcid": "", "pdf_url": ""}
        result = PubMedtoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE
        assert result["rights"] == MISSING_VALUE

        # Missing PDF URL field
        row = {"pmid": "125"}
        result = PubMedtoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE

    def test_rights_field_logic(self):
        """Test rights field is set to open-access only when PMCID present."""
        # With PMCID (open access)
        row = {"pmid": "123", "pmcid": "PMC9876543"}
        result = PubMedtoZoteroFormat(row)
        assert result["rights"] == "open-access"

        # Without PMCID (paywalled)
        row = {"pmid": "124", "pmcid": ""}
        result = PubMedtoZoteroFormat(row)
        assert result["rights"] == MISSING_VALUE

        # Missing PMCID field
        row = {"pmid": "125"}
        result = PubMedtoZoteroFormat(row)
        assert result["rights"] == MISSING_VALUE
