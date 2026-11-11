"""Unit tests for the shared converter helpers."""

import math

import pytest

from scilex.constants import MISSING_VALUE
from scilex.crawlers.converter_utils import (
    ZOTERO_FIELDS,
    dig,
    fill_record,
    first_of,
    first_valid,
    get_valid,
    item_type_from_text,
    join_authors,
    map_item_type,
    new_record,
    page_range,
)


class TestNewRecord:
    def test_has_all_fields_in_order(self):
        record = new_record("X")
        assert list(record) == list(ZOTERO_FIELDS)
        assert record["archive"] == "X"
        assert record["itemType"] == MISSING_VALUE
        assert record["title"] == MISSING_VALUE

    def test_item_type_and_extra_keys(self):
        record = new_record("X", item_type="book", extra_keys=("tags",))
        assert record["itemType"] == "book"
        assert list(record)[-1] == "tags"
        assert record["tags"] == MISSING_VALUE


class TestGetValid:
    @pytest.mark.parametrize("value", [None, "", "NA", math.nan, [], {}])
    def test_invalid_values_give_none(self, value):
        assert get_valid({"k": value}, "k") is None

    def test_missing_key_and_non_dict(self):
        assert get_valid({}, "k") is None
        assert get_valid(None, "k") is None
        assert get_valid("text", "k") is None

    def test_valid_values_returned(self):
        assert get_valid({"k": "v"}, "k") == "v"
        assert get_valid({"k": 0}, "k") == 0
        assert get_valid({"k": ["a"]}, "k") == ["a"]


class TestDig:
    def test_nested_lookup(self):
        assert dig({"a": {"b": [{"c": 1}]}}, "a", "b", 0, "c") == 1

    @pytest.mark.parametrize(
        "obj, path",
        [
            ({}, ("a",)),
            ({"a": None}, ("a", "b")),
            ({"a": "text"}, ("a", "b")),
            ({"a": []}, ("a", 0)),
            (None, ("a",)),
        ],
    )
    def test_never_raises(self, obj, path):
        assert dig(obj, *path, default="d") == "d"

    def test_none_leaf_gives_default(self):
        assert dig({"a": None}, "a", default="d") == "d"


class TestSmallHelpers:
    def test_first_of(self):
        assert first_of(["a", "b"]) == "a"
        assert first_of([]) is None
        assert first_of("a") == "a"
        assert first_of(None) is None

    def test_first_valid(self):
        assert first_valid({"a": "", "b": "x"}, "a", "b") == "x"
        assert first_valid({}, "a") is None

    def test_join_authors(self):
        assert join_authors(["A", None, "", "B"]) == "A;B"
        assert join_authors([]) == MISSING_VALUE
        assert join_authors(None) == MISSING_VALUE
        assert join_authors("Solo") == "Solo"

    def test_page_range(self):
        assert page_range("1", "9") == "1-9"
        assert page_range(1, 9) == "1-9"
        assert page_range("1", None) == MISSING_VALUE
        assert page_range("", "9") == MISSING_VALUE

    def test_map_item_type(self):
        mapping = {"a": "book"}
        assert map_item_type("a", mapping, "d") == "book"
        assert map_item_type("z", mapping, "d") == "d"
        assert map_item_type(["a"], mapping, "d") == "d"
        assert map_item_type(None, mapping, "d") == "d"

    def test_item_type_from_text(self):
        patterns = (("Conf", "conferencePaper"), ("Art", "journalArticle"))
        assert (
            item_type_from_text("Conference Paper", patterns, "d") == "conferencePaper"
        )
        assert item_type_from_text(["Art"], patterns, "d") == "journalArticle"
        assert item_type_from_text(None, patterns, "d") == "d"

    def test_fill_record_skips_none_only(self):
        record = new_record("X")
        fill_record(record, title=None, volume=0, issue="2")
        assert record["title"] == MISSING_VALUE
        assert record["volume"] == 0
        assert record["issue"] == "2"
