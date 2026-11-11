"""Tests for scilex.export_to_bibtex module - all pure functions."""

import pandas as pd
import pytest

from scilex.export_to_bibtex import (
    ITEMTYPE_TO_BIBTEX,
    _escape_url,
    escape_bibtex,
    extract_year,
    format_authors,
    format_bibtex_entry,
    format_pages,
    generate_citation_key,
    parse_tags,
    safe_get,
)


# -------------------------------------------------------------------------
# safe_get
# -------------------------------------------------------------------------
class TestSafeGet:
    def test_named_tuple_attribute(self):
        row = pd.Series({"title": "My Paper"}).rename("row")
        # itertuples gives named tuples; for unit testing we use the function directly
        assert safe_get(row, "title") == "My Paper"

    def test_missing_attribute_returns_none(self):
        row = pd.Series({"title": "My Paper"})
        assert safe_get(row, "nonexistent") is None

    def test_dict_input(self):
        d = {"key": "value"}
        assert safe_get(d, "key") == "value"

    def test_none_input(self):
        assert safe_get(None, "key") is None


# -------------------------------------------------------------------------
# parse_tags
# -------------------------------------------------------------------------
class TestParseTags:
    def test_semicolon_separated(self):
        assert parse_tags("TASK:NER;PTM:BERT") == ["TASK:NER", "PTM:BERT"]

    def test_single_tag(self):
        assert parse_tags("TASK:NER") == ["TASK:NER"]

    def test_na_returns_empty(self):
        assert parse_tags("NA") == []

    def test_none_returns_empty(self):
        assert parse_tags(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_tags("") == []

    def test_strips_whitespace(self):
        assert parse_tags("TASK:NER ; PTM:BERT") == ["TASK:NER", "PTM:BERT"]

    def test_filters_empty_segments(self):
        assert parse_tags("TASK:NER;;PTM:BERT") == ["TASK:NER", "PTM:BERT"]


# -------------------------------------------------------------------------
# escape_bibtex
# -------------------------------------------------------------------------
class TestEscapeBibtex:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("A & B", r"A \& B"),
            ("100%", r"100\%"),
            ("C#", r"C\#"),
            ("my_var", r"my\_var"),
            ("$10", r"\$10"),
            ("{x}", r"\{x\}"),
            ("a\\b", r"a\textbackslash{}b"),
            ("~", r"\textasciitilde{}"),
            ("^", r"\textasciicircum{}"),
            ("50% R&D", r"50\% R\&D"),
        ],
    )
    def test_exact_escaping(self, raw, expected):
        assert escape_bibtex(raw) == expected

    def test_na_returns_empty(self):
        assert escape_bibtex("NA") == ""

    def test_none_returns_empty(self):
        assert escape_bibtex(None) == ""

    def test_normal_text_unchanged(self):
        assert escape_bibtex("Normal text here") == "Normal text here"


class TestEscapeUrl:
    def test_percent_and_hash_escaped(self):
        assert _escape_url("http://a.org/x%20y#frag") == r"http://a.org/x\%20y\#frag"

    def test_underscore_and_tilde_untouched(self):
        assert _escape_url("http://a.org/~u/a_b") == "http://a.org/~u/a_b"

    def test_balanced_braces_untouched(self):
        assert _escape_url("http://a.org/{x}") == "http://a.org/{x}"

    def test_unbalanced_braces_escaped(self):
        assert _escape_url("http://a.org/}x{") == r"http://a.org/\}x\{"

    def test_missing_returns_empty(self):
        assert _escape_url("NA") == ""


class TestEntryEscaping:
    def _entry(self, **fields):
        row = pd.Series({"itemType": "journalArticle", "title": "T", **fields})
        return format_bibtex_entry(row, "k")

    def test_keywords_escaped(self):
        assert r"keywords = {R&D}" not in self._entry(tags="R&D;a_b")
        assert r"keywords = {R\&D, a\_b}" in self._entry(tags="R&D;a_b")

    def test_authors_escaped(self):
        assert r"author = {Smith \& Sons and A\_B}" in self._entry(
            authors="Smith & Sons;A_B"
        )

    def test_url_fields_escaped_minimally(self):
        entry = self._entry(
            url="http://a.org/p_1?q=50%&r#x",
            pdf_url="http://a.org/f%20.pdf",
            pwc_url="http://pwc.co/a#b",
            github_repo="http://gh.com/a_b/~c#d",
        )
        assert r"url = {http://a.org/p_1?q=50\%&r\#x}" in entry
        assert r"file = {http://a.org/f\%20.pdf}" in entry
        assert r"pwcurl = {http://pwc.co/a\#b}" in entry
        assert r"howpublished = {http://gh.com/a_b/~c\#d}" in entry

    def test_pwc_url_exported_as_pwcurl(self):
        entry = self._entry(pwc_url="https://paperswithcode.co/paper/2307.03172")
        assert "pwcurl = {https://paperswithcode.co/paper/2307.03172}" in entry
        assert "hfurl" not in entry

    def test_legacy_hf_url_falls_back_to_pwcurl(self):
        entry = self._entry(hf_url="https://huggingface.co/papers/2401.12345")
        assert "pwcurl = {https://huggingface.co/papers/2401.12345}" in entry


# -------------------------------------------------------------------------
# format_authors
# -------------------------------------------------------------------------
class TestFormatAuthors:
    def test_multiple_authors(self):
        assert format_authors("John Smith;Jane Doe") == "John Smith and Jane Doe"

    def test_single_author(self):
        assert format_authors("John Smith") == "John Smith"

    def test_three_authors(self):
        result = format_authors("A;B;C")
        assert result == "A and B and C"

    def test_na_returns_empty(self):
        assert format_authors("NA") == ""

    def test_none_returns_empty(self):
        assert format_authors(None) == ""

    def test_strips_whitespace(self):
        assert format_authors("John Smith ; Jane Doe") == "John Smith and Jane Doe"

    def test_empty_segments_filtered(self):
        assert format_authors("John Smith;;Jane Doe") == "John Smith and Jane Doe"


# -------------------------------------------------------------------------
# format_pages
# -------------------------------------------------------------------------
class TestFormatPages:
    def test_dash_to_double_dash(self):
        assert format_pages("123-456") == "123--456"

    def test_already_double_dash(self):
        assert format_pages("123--456") == "123--456"

    def test_na_returns_empty(self):
        assert format_pages("NA") == ""

    def test_single_page(self):
        assert format_pages("42") == "42"

    def test_strips_whitespace(self):
        assert format_pages("  123-456  ") == "123--456"


# -------------------------------------------------------------------------
# extract_year
# -------------------------------------------------------------------------
class TestExtractYear:
    def test_iso_date(self):
        assert extract_year("2024-03-15") == "2024"

    def test_year_only(self):
        assert extract_year("2023") == "2023"

    def test_partial_date(self):
        assert extract_year("2022-01") == "2022"

    def test_na_returns_empty(self):
        assert extract_year("NA") == ""

    def test_none_returns_empty(self):
        assert extract_year(None) == ""

    def test_no_year_found(self):
        assert extract_year("abc") == ""

    def test_year_in_text(self):
        assert extract_year("Published in 2021") == "2021"


# -------------------------------------------------------------------------
# generate_citation_key
# -------------------------------------------------------------------------
class TestGenerateCitationKey:
    def test_doi_based_key(self):
        row = pd.Series({"authors": "Smith", "date": "2024", "title": "Test"})
        used = set()
        key = generate_citation_key("10.1234/test.2024", row, used)
        assert key == "10_1234_test_2024"
        assert key in used

    def test_collision_adds_suffix(self):
        row = pd.Series({"authors": "Smith", "date": "2024", "title": "Test"})
        used = {"10_1234_test_2024"}
        key = generate_citation_key("10.1234/test.2024", row, used)
        assert key == "10_1234_test_2024_a"

    def test_double_collision(self):
        row = pd.Series({"authors": "Smith", "date": "2024", "title": "Test"})
        used = {"10_1234_test_2024", "10_1234_test_2024_a"}
        key = generate_citation_key("10.1234/test.2024", row, used)
        assert key == "10_1234_test_2024_b"

    def test_fallback_without_doi(self):
        row = pd.Series(
            {"authors": "John Smith;Jane Doe", "date": "2024-01", "title": "My Paper"}
        )
        used = set()
        key = generate_citation_key("NA", row, used)
        # Should use author-year format
        assert "Smith" in key or "Doe" in key or "Unknown" in key

    def test_fallback_no_authors_no_doi(self):
        row = pd.Series({"authors": "NA", "date": "NA", "title": "Some Title"})
        used = set()
        key = generate_citation_key(None, row, used)
        assert "Unknown" in key

    def test_multiple_underscores_collapsed(self):
        row = pd.Series({"authors": "A", "date": "2024", "title": "T"})
        used = set()
        key = generate_citation_key("10..1234//test", row, used)
        assert "__" not in key


# -------------------------------------------------------------------------
# format_bibtex_entry
# -------------------------------------------------------------------------
class TestFormatBibtexEntry:
    def _make_row(self, **overrides):
        defaults = {
            "title": "Test Paper",
            "authors": "John Smith;Jane Doe",
            "date": "2024-01-15",
            "DOI": "10.1234/test",
            "itemType": "journalArticle",
            "journalAbbreviation": "J. Test",
            "abstract": "This is a test abstract.",
            "url": "https://example.com",
            "volume": "1",
            "issue": "2",
            "pages": "10-20",
            "language": "en",
            "archive": "SemanticScholar",
            "archiveID": "abc123",
            "pdf_url": "NA",
            "publisher": "NA",
            "rights": "NA",
            "serie": "NA",
            "conferenceName": "NA",
            "tags": "NA",
            "pwc_url": "NA",
            "github_repo": "NA",
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_article_entry_type(self):
        row = self._make_row()
        entry = format_bibtex_entry(row, "test_key")
        assert entry.startswith("@article{test_key,")

    def test_inproceedings_entry_type(self):
        row = self._make_row(itemType="conferencePaper", conferenceName="ICML 2024")
        entry = format_bibtex_entry(row, "conf_key")
        assert entry.startswith("@inproceedings{conf_key,")
        assert "booktitle = {ICML 2024}" in entry

    def test_contains_title(self):
        row = self._make_row(title="My Great Paper")
        entry = format_bibtex_entry(row, "key")
        assert "title = {My Great Paper}" in entry

    def test_contains_authors(self):
        row = self._make_row(authors="Alice;Bob")
        entry = format_bibtex_entry(row, "key")
        assert "author = {Alice and Bob}" in entry

    def test_missing_authors_shows_unknown(self):
        row = self._make_row(authors="NA")
        entry = format_bibtex_entry(row, "key")
        assert "author = {Unknown}" in entry

    def test_contains_year(self):
        row = self._make_row(date="2024-03-15")
        entry = format_bibtex_entry(row, "key")
        assert "year = {2024}" in entry

    def test_contains_doi(self):
        row = self._make_row(DOI="10.1234/test")
        entry = format_bibtex_entry(row, "key")
        assert "doi = {10" in entry

    def test_contains_abstract(self):
        row = self._make_row(abstract="Test abstract content")
        entry = format_bibtex_entry(row, "key")
        assert "abstract = {Test abstract content}" in entry

    def test_pages_formatted_with_double_dash(self):
        row = self._make_row(pages="10-20")
        entry = format_bibtex_entry(row, "key")
        assert "pages = {10--20}" in entry

    def test_pdf_url_in_file_field(self):
        row = self._make_row(pdf_url="https://arxiv.org/pdf/2401.12345.pdf")
        entry = format_bibtex_entry(row, "key")
        assert "file = {https://arxiv.org/pdf/2401.12345.pdf}" in entry

    def test_na_fields_excluded(self):
        row = self._make_row(publisher="NA", rights="NA", pdf_url="NA")
        entry = format_bibtex_entry(row, "key")
        assert "publisher" not in entry
        assert "copyright" not in entry
        assert "file" not in entry

    def test_hf_tags_in_dedicated_fields(self):
        row = self._make_row(tags="TASK:NER;PTM:BERT;transfer learning")
        entry = format_bibtex_entry(row, "key")
        assert "task = {NER}" in entry
        assert "ptm = {BERT}" in entry
        assert "keywords = {transfer learning}" in entry

    def test_entry_closes_properly(self):
        row = self._make_row()
        entry = format_bibtex_entry(row, "key")
        assert entry.rstrip().endswith("}")
        # Last field line should NOT have trailing comma
        lines = entry.strip().split("\n")
        # Second-to-last line (before closing brace) should not end with comma
        assert not lines[-2].endswith(",")

    def test_unknown_itemtype_falls_back_to_misc(self):
        row = self._make_row(itemType="thesis")
        entry = format_bibtex_entry(row, "key")
        assert entry.startswith("@misc{key,")

    def test_publisher_only_for_books(self):
        """Publisher should NOT appear in @article entries."""
        row = self._make_row(publisher="Springer", itemType="journalArticle")
        entry = format_bibtex_entry(row, "key")
        assert "publisher" not in entry

    def test_publisher_appears_for_book(self):
        row = self._make_row(publisher="Springer", itemType="book")
        entry = format_bibtex_entry(row, "key")
        assert "publisher = {Springer}" in entry


# -------------------------------------------------------------------------
# ITEMTYPE_TO_BIBTEX mapping
# -------------------------------------------------------------------------
class TestItemtypeMapping:
    def test_journal_article(self):
        assert ITEMTYPE_TO_BIBTEX["journalArticle"] == "article"

    def test_conference_paper(self):
        assert ITEMTYPE_TO_BIBTEX["conferencePaper"] == "inproceedings"

    def test_book_section(self):
        assert ITEMTYPE_TO_BIBTEX["bookSection"] == "incollection"

    def test_book(self):
        assert ITEMTYPE_TO_BIBTEX["book"] == "book"

    def test_preprint(self):
        assert ITEMTYPE_TO_BIBTEX["preprint"] == "misc"

    def test_manuscript(self):
        assert ITEMTYPE_TO_BIBTEX["Manuscript"] == "misc"


class TestMainErrorHandling:
    def test_value_error_exits_1(self, monkeypatch):
        import scilex.export_to_bibtex as mod

        monkeypatch.setattr("sys.argv", ["scilex-export-bibtex"])
        monkeypatch.setattr(mod, "load_config", lambda **_: {"collect_name": "c"})

        def raise_value_error(_config):
            raise ValueError("bad csv")

        monkeypatch.setattr(mod, "load_aggregated_data", raise_value_error)
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1


def test_export_uses_normalized_collect_name(tmp_path):
    import scilex.export_to_bibtex as mod

    directory = tmp_path / "mycoll"
    directory.mkdir()
    data = pd.DataFrame([{"itemType": "book", "title": "T", "DOI": "10.1/a"}])
    output = mod.export_to_bibtex(
        data, {"output_dir": str(tmp_path), "collect_name": "/mycoll/"}
    )
    assert output == str(directory / "aggregated_results.bib")


class TestFormatPagesDashes:
    def test_en_dash(self):
        assert format_pages("10\u201320") == "10--20"

    def test_em_dash_with_spaces(self):
        assert format_pages("10 \u2014 20") == "10--20"

    def test_many_hyphens(self):
        assert format_pages("10----20") == "10--20"


class TestCitationKeyRobustness:
    def test_suffixes_continue_past_z(self):
        row = pd.Series({"title": "T"})
        used = {"10_1_x"}
        keys = [generate_citation_key("10.1/x", row, used) for _ in range(28)]
        assert keys[0] == "10_1_x_a"
        assert keys[25] == "10_1_x_z"
        assert keys[26] == "10_1_x_aa"
        assert keys[27] == "10_1_x_ab"
        assert len(set(keys)) == 28

    def test_fallback_key_sanitized(self):
        row = pd.Series({"authors": "A B", "date": "2020", "title": "Q&A: {x}, y"})
        assert generate_citation_key("NA", row, set()) == "B2020_QA:"

    def test_last_first_author_format(self):
        row = pd.Series(
            {"authors": "Smith, John;Doe, Jane", "date": "2020", "title": "Hi"}
        )
        assert generate_citation_key("NA", row, set()) == "Smith2020_Hi"

    def test_doi_with_invalid_chars_sanitized(self):
        key = generate_citation_key("10.1002/(SICI)1097<x>", pd.Series({}), set())
        assert key == "10_1002_SICI1097x"
