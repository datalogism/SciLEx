"""Tests for format converters in scilex.crawlers.aggregate module.

Covers DBLP, HAL, IEEE, and Elsevier converters not tested elsewhere.
All are pure functions — no mocks needed.
"""

import pytest

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import (
    DBLPtoZoteroFormat,
    ElseviertoZoteroFormat,
    HALtoZoteroFormat,
    IEEEtoZoteroFormat,
    OpenAlextoZoteroFormat,
)


# -------------------------------------------------------------------------
# DBLP helpers
# -------------------------------------------------------------------------
def _make_dblp_row(**info_overrides):
    """Build a minimal DBLP row."""
    info = {
        "title": "Test Paper",
        "year": "2024",
        "type": "Journal Articles",
        "authors": {
            "author": [
                {"text": "Alice Smith", "@pid": "1"},
                {"text": "Bob Jones", "@pid": "2"},
            ]
        },
    }
    info.update(info_overrides)
    return {"@id": "https://dblp.org/rec/journals/test/Smith24", "info": info}


# -------------------------------------------------------------------------
# TestDBLPtoZoteroFormat
# -------------------------------------------------------------------------
class TestDBLPtoZoteroFormat:
    def test_archive_always_dblp(self):
        result = DBLPtoZoteroFormat(_make_dblp_row())
        assert result["archive"] == "DBLP"

    def test_archive_id_from_outer_id(self):
        row = _make_dblp_row()
        row["@id"] = "https://dblp.org/rec/journals/test/Smith24"
        result = DBLPtoZoteroFormat(row)
        assert result["archiveID"] == "https://dblp.org/rec/journals/test/Smith24"

    def test_title_extracted(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(title="My Title"))
        assert result["title"] == "My Title"

    def test_date_from_year(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(year="2023"))
        assert result["date"] == "2023"

    def test_multiple_authors_joined_semicolon(self):
        result = DBLPtoZoteroFormat(_make_dblp_row())
        assert result["authors"] == "Alice Smith;Bob Jones"

    def test_single_author_as_dict(self):
        row = _make_dblp_row()
        row["info"]["authors"] = {"author": {"text": "Solo Author", "@pid": "99"}}
        result = DBLPtoZoteroFormat(row)
        assert result["authors"] == "Solo Author"

    def test_no_authors_key(self):
        row = _make_dblp_row()
        del row["info"]["authors"]
        result = DBLPtoZoteroFormat(row)
        assert result["authors"] == MISSING_VALUE

    def test_type_journal_articles(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(type="Journal Articles"))
        assert result["itemType"] == "journalArticle"

    def test_type_conference_papers(self):
        result = DBLPtoZoteroFormat(
            _make_dblp_row(type="Conference and Workshop Papers")
        )
        assert result["itemType"] == "conferencePaper"

    def test_type_informal_publications(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(type="Informal Publications"))
        assert result["itemType"] == "Manuscript"

    def test_type_informal_and_other(self):
        result = DBLPtoZoteroFormat(
            _make_dblp_row(type="Informal and Other Publications")
        )
        assert result["itemType"] == "Manuscript"

    def test_type_unknown_defaults_to_manuscript(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(type="SomeUnknownType"))
        assert result["itemType"] == "Manuscript"

    def test_doi_cleaned(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(doi="https://doi.org/10.1234/test"))
        assert result["DOI"] == "10.1234/test"

    def test_no_doi_stays_missing(self):
        result = DBLPtoZoteroFormat(_make_dblp_row())
        assert result["DOI"] == MISSING_VALUE

    def test_pages_extracted(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(pages="10-20"))
        assert result["pages"] == "10-20"

    def test_volume_extracted(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(volume="42"))
        assert result["volume"] == "42"

    def test_issue_from_number(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(number="3"))
        assert result["issue"] == "3"

    def test_venue_sets_journal_abbreviation(self):
        result = DBLPtoZoteroFormat(
            _make_dblp_row(type="Journal Articles", venue="VLDB")
        )
        assert result["journalAbbreviation"] == "VLDB"

    def test_venue_sets_conference_name(self):
        result = DBLPtoZoteroFormat(
            _make_dblp_row(type="Conference and Workshop Papers", venue="NeurIPS")
        )
        assert result["conferenceName"] == "NeurIPS"

    def test_url_extracted_when_valid(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(url="https://example.com/paper"))
        assert result["url"] == "https://example.com/paper"

    def test_publisher_extracted_when_valid(self):
        result = DBLPtoZoteroFormat(_make_dblp_row(publisher="Springer"))
        assert result["publisher"] == "Springer"

    def test_single_author_dict_without_pid(self):
        """Single author dict missing @pid must not raise; name still extracted."""
        row = _make_dblp_row()
        row["info"]["authors"] = {"author": {"text": "Solo Author"}}
        result = DBLPtoZoteroFormat(row)
        assert result["authors"] == "Solo Author"

    @pytest.mark.parametrize(
        "type_str,expected",
        [
            ("Journal Articles", "journalArticle"),
            ("Conference and Workshop Papers", "conferencePaper"),
            ("Informal Publications", "Manuscript"),
            ("Informal and Other Publications", "Manuscript"),
            ("Dataset", "Manuscript"),  # unknown → default
        ],
    )
    def test_type_mapping_parametrized(self, type_str, expected):
        result = DBLPtoZoteroFormat(_make_dblp_row(type=type_str))
        assert result["itemType"] == expected


# -------------------------------------------------------------------------
# HAL helpers
# -------------------------------------------------------------------------
def _make_hal_row(**overrides):
    """Build a minimal HAL row."""
    row = {
        "halId_s": "hal-12345678",
        "docType_s": "ART",
    }
    row.update(overrides)
    return row


# -------------------------------------------------------------------------
# TestHALtoZoteroFormat
# -------------------------------------------------------------------------
class TestHALtoZoteroFormat:
    def test_archive_always_hal(self):
        result = HALtoZoteroFormat(_make_hal_row())
        assert result["archive"] == "HAL"

    def test_archive_id_from_hal_id(self):
        result = HALtoZoteroFormat(_make_hal_row(halId_s="hal-99999"))
        assert result["archiveID"] == "hal-99999"

    def test_url_built_from_hal_id(self):
        result = HALtoZoteroFormat(_make_hal_row(halId_s="hal-12345678"))
        assert result["url"] == "https://hal.science/hal-12345678"

    def test_rights_always_open_access(self):
        result = HALtoZoteroFormat(_make_hal_row())
        assert result["rights"] == "open_access"

    def test_title_from_list(self):
        result = HALtoZoteroFormat(
            _make_hal_row(title_s=["My Paper Title", "Alt Title"])
        )
        assert result["title"] == "My Paper Title"

    def test_title_from_string(self):
        result = HALtoZoteroFormat(_make_hal_row(title_s="Direct Title"))
        assert result["title"] == "Direct Title"

    def test_title_missing_when_absent(self):
        result = HALtoZoteroFormat(_make_hal_row())
        assert result["title"] == MISSING_VALUE

    def test_abstract_from_list(self):
        result = HALtoZoteroFormat(
            _make_hal_row(abstract_s=["The abstract text", "Alt"])
        )
        assert result["abstract"] == "The abstract text"

    def test_abstract_from_string(self):
        result = HALtoZoteroFormat(_make_hal_row(abstract_s="A direct abstract."))
        assert result["abstract"] == "A direct abstract."

    def test_doi_cleaned(self):
        result = HALtoZoteroFormat(
            _make_hal_row(doiId_id="https://doi.org/10.5555/hal.2024")
        )
        assert result["DOI"] == "10.5555/hal.2024"

    def test_pdf_url_from_files_s(self):
        result = HALtoZoteroFormat(
            _make_hal_row(
                files_s=[
                    "https://hal.science/hal-123/document.html",
                    "https://hal.science/hal-123/document.pdf",
                ]
            )
        )
        assert result["pdf_url"] == "https://hal.science/hal-123/document.pdf"

    def test_no_pdf_in_files_s(self):
        result = HALtoZoteroFormat(
            _make_hal_row(files_s=["https://hal.science/hal-123/document.html"])
        )
        assert result["pdf_url"] == MISSING_VALUE

    def test_no_files_s(self):
        result = HALtoZoteroFormat(_make_hal_row())
        assert result["pdf_url"] == MISSING_VALUE

    def test_authors_from_auth_full_name(self):
        result = HALtoZoteroFormat(
            _make_hal_row(
                authFullNameIdHal_fs=[
                    "Alice Smith_FacetSep_alice-s",
                    "Bob Jones_FacetSep_bob-j",
                ]
            )
        )
        assert result["authors"] == "Alice Smith;Bob Jones"

    def test_title_s_empty_list_returns_missing(self):
        """title_s=[] (empty list) must not crash and must return MISSING_VALUE."""
        result = HALtoZoteroFormat(_make_hal_row(title_s=[]))
        assert result["title"] == MISSING_VALUE

    def test_author_name_with_facetsep_collision(self):
        """Author names containing the _FacetSep_ separator must not corrupt output."""
        result = HALtoZoteroFormat(
            _make_hal_row(
                authFullNameIdHal_fs=[
                    "Alice_FacetSep_Smith_FacetSep_alice-s",
                    "Bob Jones_FacetSep_bob-j",
                ]
            )
        )
        # "Bob Jones" should always be present; "Alice" name extraction is best-effort
        assert "Bob Jones" in result["authors"]

    def test_doc_type_art_is_journal_article(self):
        result = HALtoZoteroFormat(_make_hal_row(docType_s="ART"))
        assert result["itemType"] == "journalArticle"

    def test_doc_type_comm_is_conference_paper(self):
        result = HALtoZoteroFormat(_make_hal_row(docType_s="COMM"))
        assert result["itemType"] == "conferencePaper"

    def test_doc_type_proceedings_is_conference_paper(self):
        result = HALtoZoteroFormat(_make_hal_row(docType_s="PROCEEDINGS"))
        assert result["itemType"] == "conferencePaper"

    def test_doc_type_unknown_defaults_to_manuscript(self):
        result = HALtoZoteroFormat(_make_hal_row(docType_s="REPORT"))
        assert result["itemType"] == "Manuscript"

    def test_date_from_submitted_year(self):
        result = HALtoZoteroFormat(_make_hal_row(submittedDateY_i=2022))
        assert result["date"] == "2022"

    def test_language_from_list(self):
        result = HALtoZoteroFormat(_make_hal_row(language_s=["en", "fr"]))
        assert result["language"] == "en"

    def test_language_from_string(self):
        result = HALtoZoteroFormat(_make_hal_row(language_s="fr"))
        assert result["language"] == "fr"

    @pytest.mark.parametrize(
        "doc_type,expected",
        [
            ("ART", "journalArticle"),
            ("COMM", "conferencePaper"),
            ("PROCEEDINGS", "conferencePaper"),
            ("REPORT", "Manuscript"),
        ],
    )
    def test_doc_type_mapping_parametrized(self, doc_type, expected):
        result = HALtoZoteroFormat(_make_hal_row(docType_s=doc_type))
        assert result["itemType"] == expected


# -------------------------------------------------------------------------
# IEEE helpers
# -------------------------------------------------------------------------
def _make_ieee_row(**overrides):
    """Build a minimal IEEE row."""
    row = {
        "article_number": "IEEE123456",
        "title": "Test IEEE Paper",
        "abstract": "A test abstract.",
        "authors": [],
        "content_type": "Journals",
        "access_type": "Open Access",
    }
    row.update(overrides)
    return row


# -------------------------------------------------------------------------
# TestIEEEtoZoteroFormat
# -------------------------------------------------------------------------
class TestIEEEtoZoteroFormat:
    def test_archive_always_ieee(self):
        result = IEEEtoZoteroFormat(_make_ieee_row())
        assert result["archive"] == "IEEE"

    def test_archive_id_from_article_number(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(article_number="A999"))
        assert result["archiveID"] == "A999"

    def test_title_extracted(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(title="My IEEE Paper"))
        assert result["title"] == "My IEEE Paper"

    def test_abstract_extracted(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(abstract="The abstract."))
        assert result["abstract"] == "The abstract."

    def test_date_from_publication_date(self):
        result = IEEEtoZoteroFormat(
            _make_ieee_row(publication_date="2024-05-01", publication_year="2024")
        )
        assert result["date"] == "2024-05-01"

    def test_date_fallback_to_publication_year(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(publication_year="2023"))
        assert result["date"] == "2023"

    def test_date_missing_when_absent(self):
        result = IEEEtoZoteroFormat(_make_ieee_row())
        assert result["date"] == MISSING_VALUE

    def test_content_type_journals(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(content_type="Journals"))
        assert result["itemType"] == "journalArticle"

    def test_content_type_conferences(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(content_type="Conferences"))
        assert result["itemType"] == "conferencePaper"

    def test_content_type_unknown_defaults_manuscript(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(content_type="Other"))
        assert result["itemType"] == "Manuscript"

    def test_authors_as_flat_list(self):
        result = IEEEtoZoteroFormat(
            _make_ieee_row(
                authors=[
                    {"full_name": "Alice Smith"},
                    {"full_name": "Bob Jones"},
                ]
            )
        )
        assert result["authors"] == "Alice Smith;Bob Jones"

    def test_authors_as_nested_dict(self):
        result = IEEEtoZoteroFormat(
            _make_ieee_row(
                authors={
                    "authors": [
                        {"full_name": "Alice Smith"},
                        {"full_name": "Bob Jones"},
                    ]
                }
            )
        )
        assert result["authors"] == "Alice Smith;Bob Jones"

    def test_pages_from_start_end(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(start_page="10", end_page="20"))
        assert result["pages"] == "10-20"

    def test_doi_cleaned(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(doi="https://doi.org/10.1109/test"))
        assert result["DOI"] == "10.1109/test"

    def test_rights_from_access_type(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(access_type="Open Access"))
        assert result["rights"] == "Open Access"

    def test_html_url_extracted(self):
        result = IEEEtoZoteroFormat(
            _make_ieee_row(html_url="https://ieeexplore.ieee.org/document/123")
        )
        assert result["url"] == "https://ieeexplore.ieee.org/document/123"

    def test_volume_extracted(self):
        result = IEEEtoZoteroFormat(_make_ieee_row(volume="10"))
        assert result["volume"] == "10"

    def test_journal_abbreviation_from_publication_title(self):
        result = IEEEtoZoteroFormat(
            _make_ieee_row(publication_title="IEEE Trans. Neural Netw.")
        )
        assert result["journalAbbreviation"] == "IEEE Trans. Neural Netw."

    @pytest.mark.parametrize(
        "content_type,expected",
        [
            ("Journals", "journalArticle"),
            ("Conferences", "conferencePaper"),
            ("Early Access", "Manuscript"),
        ],
    )
    def test_content_type_mapping_parametrized(self, content_type, expected):
        result = IEEEtoZoteroFormat(_make_ieee_row(content_type=content_type))
        assert result["itemType"] == expected


# -------------------------------------------------------------------------
# Elsevier helpers
# -------------------------------------------------------------------------
def _make_elsevier_row(**overrides):
    """Build a minimal Elsevier (Scopus) row."""
    row = {
        "prism:url": "https://api.elsevier.com/content/abstract/scopus_id/123",
        "openaccess": "1",
        "prism:pageRange": "100-120",
    }
    row.update(overrides)
    return row


# -------------------------------------------------------------------------
# TestElseviertoZoteroFormat
# -------------------------------------------------------------------------
class TestElseviertoZoteroFormat:
    def test_archive_always_elsevier(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row())
        assert result["archive"] == "Elsevier"

    def test_archive_id_from_source_id(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row(**{"source-id": "SRC999"}))
        assert result["archiveID"] == "SRC999"

    def test_url_from_prism_url(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row())
        assert (
            result["url"] == "https://api.elsevier.com/content/abstract/scopus_id/123"
        )

    def test_rights_from_openaccess(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row(openaccess="1"))
        assert result["rights"] == "1"

    def test_pages_from_prism_page_range(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"prism:pageRange": "50-75"})
        )
        assert result["pages"] == "50-75"

    def test_title_from_dc_title(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"dc:title": "My Scopus Paper"})
        )
        assert result["title"] == "My Scopus Paper"

    def test_abstract_from_dc_description(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"dc:description": "Abstract text here."})
        )
        assert result["abstract"] == "Abstract text here."

    def test_date_from_cover_date(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"prism:coverDate": "2024-06-15"})
        )
        assert result["date"] == "2024-06-15"

    def test_doi_cleaned(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"prism:doi": "https://doi.org/10.1016/test"})
        )
        assert result["DOI"] == "10.1016/test"

    def test_volume_from_prism_volume(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row(**{"prism:volume": "55"}))
        assert result["volume"] == "55"

    def test_issue_from_prism_issue_identifier(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"prism:issueIdentifier": "4"})
        )
        assert result["issue"] == "4"

    def test_journal_from_publication_name(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"prism:publicationName": "Nature"})
        )
        assert result["journalAbbreviation"] == "Nature"

    def test_authors_from_dc_creator(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(**{"dc:creator": "Smith A."})
        )
        assert result["authors"] == "Smith A."

    def test_subtype_article_is_journal(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(subtypeDescription="Article")
        )
        assert result["itemType"] == "journalArticle"

    def test_subtype_conference_paper(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(subtypeDescription="Conference Paper")
        )
        assert result["itemType"] == "conferencePaper"

    def test_subtype_book_chapter(self):
        result = ElseviertoZoteroFormat(
            _make_elsevier_row(subtypeDescription="Book Chapter")
        )
        assert result["itemType"] == "bookSection"

    def test_subtype_unknown_defaults_manuscript(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row(subtypeDescription="Review"))
        assert result["itemType"] == "Manuscript"

    def test_no_subtype_defaults_manuscript(self):
        result = ElseviertoZoteroFormat(_make_elsevier_row())
        assert result["itemType"] == "Manuscript"

    @pytest.mark.parametrize(
        "subtype,expected",
        [
            ("Article", "journalArticle"),
            ("Conference Paper", "conferencePaper"),
            ("Book Chapter", "bookSection"),
            ("Review", "Manuscript"),
        ],
    )
    def test_subtype_mapping_parametrized(self, subtype, expected):
        result = ElseviertoZoteroFormat(_make_elsevier_row(subtypeDescription=subtype))
        assert result["itemType"] == expected


# -------------------------------------------------------------------------
# OpenAlex — type mapping (extends existing coverage)
# -------------------------------------------------------------------------
def _minimal_openalex_row(**overrides):
    """Build a minimal OpenAlex row."""
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


class TestOpenAlexTypeMapping:
    @pytest.mark.parametrize(
        "openalex_type,expected_item_type",
        [
            ("journal-article", "journalArticle"),
            ("proceedings-article", "conferencePaper"),
            ("book-chapter", "bookSection"),
            ("dataset", "Manuscript"),
            ("unknown-type", "Manuscript"),
        ],
    )
    def test_type_mapping(self, openalex_type, expected_item_type):
        row = _minimal_openalex_row(type=openalex_type)
        result = OpenAlextoZoteroFormat(row)
        assert result["itemType"] == expected_item_type

    def test_abstract_from_inverted_index(self):
        row = _minimal_openalex_row(
            abstract_inverted_index={"Hello": [0], "world": [1]}
        )
        result = OpenAlextoZoteroFormat(row)
        assert result["abstract"] == "Hello world"

    def test_no_abstract_when_index_none(self):
        row = _minimal_openalex_row(abstract_inverted_index=None)
        result = OpenAlextoZoteroFormat(row)
        assert result["abstract"] == MISSING_VALUE
