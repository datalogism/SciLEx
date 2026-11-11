"""Tests for pure functions in scilex.crawlers.aggregate module."""

import pandas as pd
import pytest

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import (
    ArxivtoZoteroFormat,
    IstextoZoteroFormat,
    OpenAlextoZoteroFormat,
    SpringertoZoteroFormat,
    clean_doi,
    getquality,
    quality_scores,
    reconstruct_abstract_from_inverted_index,
    safe_get,
)


# -------------------------------------------------------------------------
# safe_get
# -------------------------------------------------------------------------
class TestSafeGet:
    def test_existing_key(self):
        assert safe_get({"a": 1}, "a") == 1

    def test_missing_key_returns_default(self):
        assert safe_get({"a": 1}, "b") is None

    def test_custom_default(self):
        assert safe_get({"a": 1}, "b", default="x") == "x"

    def test_empty_string_value_returns_default(self):
        assert safe_get({"a": ""}, "a") is None

    def test_non_dict_returns_default(self):
        assert safe_get("not a dict", "a") is None

    def test_none_input_returns_default(self):
        assert safe_get(None, "a") is None


# -------------------------------------------------------------------------
# clean_doi
# -------------------------------------------------------------------------
class TestCleanDoi:
    def test_already_clean(self):
        assert clean_doi("10.1234/test") == "10.1234/test"

    def test_https_prefix(self):
        assert clean_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_http_prefix(self):
        assert clean_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_dx_doi_prefix(self):
        assert clean_doi("https://dx.doi.org/10.1234/test") == "10.1234/test"

    def test_http_dx_doi_prefix(self):
        assert clean_doi("http://dx.doi.org/10.1234/test") == "10.1234/test"

    def test_na_returns_missing(self):
        assert clean_doi("NA") == MISSING_VALUE

    def test_none_returns_missing(self):
        assert clean_doi(None) == MISSING_VALUE

    def test_empty_returns_missing(self):
        assert clean_doi("") == MISSING_VALUE

    def test_case_insensitive_prefix(self):
        assert clean_doi("HTTPS://DOI.ORG/10.1234/test") == "10.1234/test"

    def test_preserves_complex_doi(self):
        doi = "10.1021/acsomega.2c06948"
        assert clean_doi(doi) == doi


# -------------------------------------------------------------------------
# getquality
# -------------------------------------------------------------------------
class TestGetQuality:
    def test_all_critical_fields(self):
        row = {"DOI": "10.1234", "title": "Test", "authors": "A", "date": "2024"}
        columns = ["DOI", "title", "authors", "date"]
        score = getquality(row, columns)
        assert score == 20  # 4 critical fields * 5

    def test_important_fields(self):
        row = {"abstract": "text", "journalAbbreviation": "J.", "volume": "1"}
        columns = ["abstract", "journalAbbreviation", "volume"]
        score = getquality(row, columns)
        assert score == 9  # 3 important fields * 3

    def test_volume_and_issue_bonus(self):
        row = {"volume": "1", "issue": "2"}
        columns = ["volume", "issue"]
        score = getquality(row, columns)
        assert score == 7  # 2*3 + 1 bonus

    def test_missing_values_not_counted(self):
        row = {"DOI": "NA", "title": "Test"}
        columns = ["DOI", "title"]
        score = getquality(row, columns)
        assert score == 5  # Only title (critical)

    def test_nice_to_have_fields(self):
        row = {"url": "https://example.com", "language": "en"}
        columns = ["url", "language"]
        score = getquality(row, columns)
        assert score == 2  # 2 * 1

    def test_empty_row(self):
        row = {"DOI": "NA", "title": "NA"}
        columns = ["DOI", "title"]
        score = getquality(row, columns)
        assert score == 0

    def test_mixed_fields(self):
        row = {
            "DOI": "10.1234",
            "title": "Test",
            "abstract": "text",
            "url": "https://example.com",
        }
        columns = ["DOI", "title", "abstract", "url"]
        score = getquality(row, columns)
        assert score == 5 + 5 + 3 + 1  # critical + critical + important + nice


# -------------------------------------------------------------------------
# reconstruct_abstract_from_inverted_index
# -------------------------------------------------------------------------
class TestReconstructAbstractFromInvertedIndex:
    def test_simple_reconstruction(self):
        inverted_index = {"Hello": [0], "world": [1]}
        assert reconstruct_abstract_from_inverted_index(inverted_index) == "Hello world"

    def test_word_at_multiple_positions(self):
        inverted_index = {"the": [0, 2], "cat": [1], "dog": [3]}
        result = reconstruct_abstract_from_inverted_index(inverted_index)
        assert result == "the cat the dog"

    def test_empty_index_returns_none(self):
        assert reconstruct_abstract_from_inverted_index({}) is None

    def test_none_input_returns_none(self):
        assert reconstruct_abstract_from_inverted_index(None) is None

    def test_real_world_example(self):
        """OpenAlex-style inverted index."""
        inverted_index = {
            "We": [0],
            "present": [1],
            "a": [2, 7],
            "novel": [3],
            "approach": [4],
            "to": [5],
            "build": [6],
            "knowledge": [8],
            "graph.": [9],
        }
        result = reconstruct_abstract_from_inverted_index(inverted_index)
        assert result == "We present a novel approach to build a knowledge graph."

    def test_single_word(self):
        inverted_index = {"Abstract": [0]}
        assert reconstruct_abstract_from_inverted_index(inverted_index) == "Abstract"


# -------------------------------------------------------------------------
# ArxivtoZoteroFormat - PDF URL extraction
# -------------------------------------------------------------------------
def _minimal_arxiv_row(**overrides):
    """Build a minimal arXiv row that won't KeyError in ArxivtoZoteroFormat."""
    row = {
        "abstract": "",
        "authors": [],
        "doi": "",
        "title": "",
        "id": "",
        "published": "",
        "journal": "",
        "categories": [],
    }
    row.update(overrides)
    return row


class TestArxivPdfUrl:
    def test_bare_id_generates_pdf_url(self):
        row = _minimal_arxiv_row(id="2301.12345")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == "https://arxiv.org/pdf/2301.12345.pdf"

    def test_full_abs_url_generates_pdf_url(self):
        row = _minimal_arxiv_row(id="https://arxiv.org/abs/2301.12345")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == "https://arxiv.org/pdf/2301.12345.pdf"

    def test_full_abs_url_with_version_generates_pdf_url(self):
        row = _minimal_arxiv_row(id="https://arxiv.org/abs/2301.12345v2")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == "https://arxiv.org/pdf/2301.12345v2.pdf"

    def test_full_pdf_url_generates_pdf_url(self):
        row = _minimal_arxiv_row(id="https://arxiv.org/pdf/2301.12345.pdf")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == "https://arxiv.org/pdf/2301.12345.pdf"

    def test_old_style_id_with_category(self):
        row = _minimal_arxiv_row(id="cs/0601078")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == "https://arxiv.org/pdf/0601078.pdf"

    def test_empty_id_no_pdf_url(self):
        row = _minimal_arxiv_row(id="")
        result = ArxivtoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE


# -------------------------------------------------------------------------
# OpenAlextoZoteroFormat - PDF URL extraction fallback
# -------------------------------------------------------------------------
def _minimal_openalex_row(**overrides):
    """Build a minimal OpenAlex row that won't KeyError."""
    row = {
        "id": "https://openalex.org/W123",
        "doi": "",
        "title": "Test",
        "publication_date": "2024-01-01",
        "language": "",
        "best_oa_location": None,
        "primary_location": None,
        "abstract_inverted_index": None,
        "open_access": "",
        "authorships": [],
        "type": "journal-article",
        "biblio": {"volume": "", "issue": "", "first_page": "", "last_page": ""},
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "work_type, item_type",
    [
        ("preprint", "preprint"),
        ("review", "journalArticle"),
        ("dissertation", "thesis"),
        ("article", "journalArticle"),
        ("paratext", "Manuscript"),
    ],
)
def test_openalex_work_types(work_type, item_type):
    row = _minimal_openalex_row(type=work_type)
    assert OpenAlextoZoteroFormat(row)["itemType"] == item_type


class TestOpenAlexPdfUrl:
    def test_best_oa_location_pdf_url(self):
        row = _minimal_openalex_row(
            best_oa_location={
                "landing_page_url": "https://example.com/article",
                "pdf_url": "https://example.com/article.pdf",
            }
        )
        result = OpenAlextoZoteroFormat(row)
        assert result["pdf_url"] == "https://example.com/article.pdf"

    def test_primary_location_pdf_url_fallback(self):
        row = _minimal_openalex_row(
            best_oa_location=None,
            primary_location={
                "landing_page_url": "https://example.com/article",
                "pdf_url": "https://example.com/article.pdf",
                "source": None,
            },
        )
        result = OpenAlextoZoteroFormat(row)
        assert result["pdf_url"] == "https://example.com/article.pdf"
        assert result["url"] == "https://example.com/article"

    def test_no_oa_location_no_pdf_url(self):
        row = _minimal_openalex_row(
            best_oa_location=None,
            primary_location={
                "landing_page_url": "https://example.com",
                "source": None,
            },
        )
        result = OpenAlextoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE

    def test_best_oa_without_pdf_url(self):
        row = _minimal_openalex_row(
            best_oa_location={
                "landing_page_url": "https://example.com/article",
                "pdf_url": None,
            }
        )
        result = OpenAlextoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE


# -------------------------------------------------------------------------
# IstextoZoteroFormat - PDF URL extraction from fulltext array
# -------------------------------------------------------------------------
def _minimal_istex_row(**overrides):
    """Build a minimal Istex row that won't KeyError."""
    row = {
        "genre": ["research-article"],
        "title": "Test",
        "author": [],
        "arkIstex": "ark:/12345",
        "publicationDate": "2024",
        "doi": [],
        "host": {},
    }
    row.update(overrides)
    return row


class TestIstexPdfUrl:
    def test_fulltext_pdf_extraction(self):
        row = _minimal_istex_row(
            fulltext=[
                {
                    "extension": "zip",
                    "uri": "https://api.istex.fr/doc/123/fulltext/zip",
                },
                {
                    "extension": "pdf",
                    "uri": "https://api.istex.fr/doc/123/fulltext/pdf",
                },
                {
                    "extension": "tei",
                    "uri": "https://api.istex.fr/doc/123/fulltext/tei",
                },
            ]
        )
        result = IstextoZoteroFormat(row)
        assert result["pdf_url"] == "https://api.istex.fr/doc/123/fulltext/pdf"

    def test_no_fulltext_no_pdf_url(self):
        row = _minimal_istex_row()
        result = IstextoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE

    def test_fulltext_without_pdf(self):
        row = _minimal_istex_row(
            fulltext=[
                {
                    "extension": "zip",
                    "uri": "https://api.istex.fr/doc/123/fulltext/zip",
                },
            ]
        )
        result = IstextoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE

    def test_fulltext_empty_list(self):
        row = _minimal_istex_row(fulltext=[])
        result = IstextoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE


# -------------------------------------------------------------------------
# SpringertoZoteroFormat - PDF URL extraction from url array
# -------------------------------------------------------------------------
def _minimal_springer_row(**overrides):
    """Build a minimal Springer row that won't KeyError."""
    row = {
        "identifier": "doi:10.1234/test",
        "publicationDate": "2024-01-01",
        "title": "Test",
        "abstract": "",
        "url": [],
        "doi": "10.1234/test",
        "publisher": "Springer",
        "publicationName": "J. Test",
        "creators": [],
        "contentType": "Article",
    }
    row.update(overrides)
    return row


class TestSpringerPdfUrl:
    def test_pdf_format_extracted(self):
        row = _minimal_springer_row(
            url=[
                {
                    "format": "html",
                    "platform": "link",
                    "value": "https://link.springer.com/article/10.1234/test",
                },
                {
                    "format": "pdf",
                    "platform": "link",
                    "value": "https://link.springer.com/content/pdf/10.1234/test.pdf",
                },
            ]
        )
        result = SpringertoZoteroFormat(row)
        assert (
            result["pdf_url"]
            == "https://link.springer.com/content/pdf/10.1234/test.pdf"
        )
        assert result["url"] == "https://link.springer.com/article/10.1234/test"

    def test_only_html_no_pdf_url(self):
        row = _minimal_springer_row(
            url=[
                {
                    "format": "html",
                    "platform": "link",
                    "value": "https://link.springer.com/article/10.1234/test",
                },
            ]
        )
        result = SpringertoZoteroFormat(row)
        assert result["url"] == "https://link.springer.com/article/10.1234/test"
        assert result["pdf_url"] == MISSING_VALUE

    def test_only_pdf_also_sets_url_fallback(self):
        row = _minimal_springer_row(
            url=[
                {
                    "format": "pdf",
                    "platform": "link",
                    "value": "https://link.springer.com/content/pdf/10.1234/test.pdf",
                },
            ]
        )
        result = SpringertoZoteroFormat(row)
        assert (
            result["pdf_url"]
            == "https://link.springer.com/content/pdf/10.1234/test.pdf"
        )
        # url should fall back to the pdf value since no html format
        assert result["url"] == "https://link.springer.com/content/pdf/10.1234/test.pdf"

    def test_empty_url_list(self):
        row = _minimal_springer_row(url=[])
        result = SpringertoZoteroFormat(row)
        assert result["pdf_url"] == MISSING_VALUE


class TestQualityScores:
    def test_matches_getquality_row_by_row(self):
        df = pd.DataFrame(
            [
                {"DOI": "10.1", "title": "T", "volume": "1", "issue": "2", "url": "NA"},
                {"DOI": "NA", "title": "", "volume": "1", "issue": None, "url": "u"},
                {"DOI": None, "title": "T", "volume": "NA", "issue": "3", "url": "u"},
            ]
        )
        expected = [getquality(row, df.columns.tolist()) for _, row in df.iterrows()]
        assert quality_scores(df).tolist() == expected

    def test_without_volume_issue_columns(self):
        df = pd.DataFrame([{"title": "T", "abstract": "A"}])
        assert quality_scores(df).tolist() == [8]
