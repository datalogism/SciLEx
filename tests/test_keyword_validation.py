"""Tests for scilex.keyword_validation module."""

from scilex.keyword_validation import (
    check_keyword_in_text,
    normalize_text,
)


# -------------------------------------------------------------------------
# normalize_text
# -------------------------------------------------------------------------
class TestNormalizeText:
    def test_simple_lowercase(self):
        assert normalize_text("Hello World") == "hello world"

    def test_na_returns_empty(self):
        assert normalize_text("NA") == ""

    def test_none_returns_empty(self):
        assert normalize_text(None) == ""

    def test_dict_format_paragraphs(self):
        text = {"p": ["First paragraph.", "Second paragraph."]}
        assert normalize_text(text) == "first paragraph. second paragraph."

    def test_dict_without_p_key(self):
        # Non-paragraph dict should be stringified
        text = {"other": "value"}
        result = normalize_text(text)
        assert "other" in result

    def test_numeric_input(self):
        assert normalize_text(42) == "42"


# -------------------------------------------------------------------------
# check_keyword_in_text
# -------------------------------------------------------------------------
class TestCheckKeywordInText:
    def test_keyword_found(self):
        assert (
            check_keyword_in_text("machine learning", "A paper about machine learning")
            is True
        )

    def test_keyword_case_insensitive(self):
        assert (
            check_keyword_in_text("Machine Learning", "machine learning study") is True
        )

    def test_keyword_not_found(self):
        assert (
            check_keyword_in_text("quantum computing", "A paper about biology") is False
        )

    def test_empty_text(self):
        assert check_keyword_in_text("test", "") is False

    def test_na_text(self):
        assert check_keyword_in_text("test", "NA") is False

    def test_none_text(self):
        assert check_keyword_in_text("test", None) is False

    def test_empty_keyword(self):
        assert check_keyword_in_text("", "some text") is False

    def test_phrase_matching(self):
        assert (
            check_keyword_in_text(
                "knowledge graph", "Building a knowledge graph system"
            )
            is True
        )

    def test_partial_word_match(self):
        # "learn" should match inside "learning"
        assert check_keyword_in_text("learn", "deep learning approach") is True
