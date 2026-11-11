"""Unit tests for BioRxiv aggregation (format conversion).

Tests cover:
- BioRxivtoZoteroFormat() field mapping
- DOI cleaning and URL construction
- PDF URL construction (100% coverage from DOI)
- Category mapping to journalAbbreviation
- Preprint vs published paper itemType handling
- Missing value handling
"""

from scilex.constants import MISSING_VALUE, is_valid
from scilex.crawlers.aggregate import BioRxivtoZoteroFormat


class TestBioRxivAggregation:
    """Test BioRxiv to Zotero format conversion."""

    def test_full_preprint(self):
        """Test conversion of a typical bioRxiv preprint."""
        row = {
            "doi": "10.1101/2024.01.15.575123",
            "title": "CRISPR-Cas9 editing in zebrafish neural circuits",
            "authors": "Smith, J.; Doe, A.; Johnson, B.",
            "abstract": "We describe a novel CRISPR approach for zebrafish.",
            "date": "2024-01-15",
            "version": "2",
            "type": "new results",
            "license": "cc_by",
            "category": "neuroscience",
            "published": "NA",
            "server": "biorxiv",
        }

        result = BioRxivtoZoteroFormat(row)

        # Fixed fields
        assert result["archive"] == "BioRxiv"
        assert result["rights"] == "open_access"
        assert result["language"] == "en"
        assert result["publisher"] == "bioRxiv"

        # Title
        assert result["title"] == row["title"]

        # Authors (already semicolon-separated from API)
        assert result["authors"] == "Smith, J.; Doe, A.; Johnson, B."

        # Abstract
        assert result["abstract"] == row["abstract"]

        # DOI (cleaned)
        assert result["DOI"] == "10.1101/2024.01.15.575123"
        assert result["archiveID"] == "10.1101/2024.01.15.575123"

        # URLs
        assert (
            result["url"] == "https://www.biorxiv.org/content/10.1101/2024.01.15.575123"
        )
        assert (
            result["pdf_url"]
            == "https://www.biorxiv.org/content/10.1101/2024.01.15.575123v2.full.pdf"
        )

        # Date
        assert result["date"] == "2024-01-15"

        # Category
        assert result["journalAbbreviation"] == "neuroscience"

        # ItemType (not published)
        assert result["itemType"] == "preprint"

    def test_published_paper(self):
        """Test conversion of a bioRxiv paper that has been published."""
        row = {
            "doi": "10.1101/2023.06.01.543210",
            "title": "Protein structure prediction with deep learning",
            "authors": "Lee, C.; Park, D.",
            "abstract": "Deep learning for protein folding.",
            "date": "2023-06-01",
            "version": "1",
            "category": "bioinformatics",
            "published": "10.1038/s41586-024-07146-0",
            "server": "biorxiv",
        }

        result = BioRxivtoZoteroFormat(row)

        # Should be journalArticle since it's published
        assert result["itemType"] == "journalArticle"

    def test_pdf_url_version_1(self):
        """Test PDF URL uses version number."""
        row = {
            "doi": "10.1101/2024.03.01.111111",
            "version": "1",
        }
        result = BioRxivtoZoteroFormat(row)
        assert result["pdf_url"].endswith("v1.full.pdf")

    def test_pdf_url_default_version(self):
        """Test PDF URL defaults to v1 when version missing."""
        row = {
            "doi": "10.1101/2024.03.01.111111",
        }
        result = BioRxivtoZoteroFormat(row)
        assert result["pdf_url"].endswith("v1.full.pdf")

    def test_doi_cleaning(self):
        """Test DOI URL prefix is stripped."""
        row = {
            "doi": "https://doi.org/10.1101/2024.01.01.000001",
        }
        result = BioRxivtoZoteroFormat(row)
        assert result["DOI"] == "10.1101/2024.01.01.000001"

    def test_missing_values(self):
        """Test handling of completely empty row."""
        row = {}
        result = BioRxivtoZoteroFormat(row)

        # Fixed fields should be set
        assert result["archive"] == "BioRxiv"
        assert result["rights"] == "open_access"
        assert result["language"] == "en"
        assert result["publisher"] == "bioRxiv"
        assert result["itemType"] == "preprint"

        # Everything else should be MISSING_VALUE
        assert result["title"] == MISSING_VALUE
        assert result["authors"] == MISSING_VALUE
        assert result["abstract"] == MISSING_VALUE
        assert result["DOI"] == MISSING_VALUE
        assert result["url"] == MISSING_VALUE
        assert result["pdf_url"] == MISSING_VALUE
        assert result["date"] == MISSING_VALUE
        assert result["archiveID"] == MISSING_VALUE
        assert result["journalAbbreviation"] == MISSING_VALUE
        assert result["volume"] == MISSING_VALUE
        assert result["issue"] == MISSING_VALUE
        assert result["pages"] == MISSING_VALUE

    def test_partial_row(self):
        """Test handling with only title and abstract."""
        row = {
            "title": "Test Paper",
            "abstract": "Test abstract.",
        }
        result = BioRxivtoZoteroFormat(row)
        assert result["title"] == "Test Paper"
        assert result["abstract"] == "Test abstract."
        assert result["DOI"] == MISSING_VALUE
        assert result["url"] == MISSING_VALUE

    def test_category_as_journal_abbreviation(self):
        """Test different categories are mapped correctly."""
        for category in [
            "neuroscience",
            "genomics",
            "cell biology",
            "bioinformatics",
        ]:
            row = {"category": category}
            result = BioRxivtoZoteroFormat(row)
            assert result["journalAbbreviation"] == category

    def test_missing_category(self):
        """Test missing category defaults to MISSING_VALUE."""
        row = {"title": "Test"}
        result = BioRxivtoZoteroFormat(row)
        assert result["journalAbbreviation"] == MISSING_VALUE

    def test_published_na_is_still_preprint(self):
        """Test that published='NA' keeps itemType as preprint."""
        row = {"published": "NA"}
        result = BioRxivtoZoteroFormat(row)
        assert result["itemType"] == "preprint"

    def test_published_empty_is_still_preprint(self):
        """Test that empty published field keeps itemType as preprint."""
        row = {"published": ""}
        result = BioRxivtoZoteroFormat(row)
        assert result["itemType"] == "preprint"

    def test_valid_fields_with_is_valid(self):
        """Test that output fields pass is_valid() check."""
        row = {
            "doi": "10.1101/2024.01.01.000001",
            "title": "Test Paper",
            "authors": "Smith, J.",
            "abstract": "This is a test.",
            "date": "2024-01-01",
            "category": "genomics",
        }
        result = BioRxivtoZoteroFormat(row)

        # These should all be valid
        assert is_valid(result["DOI"])
        assert is_valid(result["title"])
        assert is_valid(result["authors"])
        assert is_valid(result["abstract"])
        assert is_valid(result["date"])
        assert is_valid(result["url"])
        assert is_valid(result["pdf_url"])
        assert is_valid(result["archive"])
        assert is_valid(result["journalAbbreviation"])
