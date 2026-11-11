"""Container-aware validity and text normalization helpers."""

import numpy as np

from scilex.constants import is_valid, normalize_text_field


def test_is_valid_containers():
    assert is_valid(["a", "b"]) is True
    assert is_valid(("a",)) is True
    assert is_valid({"p": ["x"]}) is True
    assert is_valid({1, 2}) is True
    assert is_valid([]) is False
    assert is_valid({}) is False


def test_normalize_text_field():
    assert normalize_text_field({"p": ["a", "b"]}) == "a b"
    assert normalize_text_field(["a", "b"]) == "a b"
    assert normalize_text_field(None) == ""
    assert normalize_text_field(np.nan) == ""
    assert normalize_text_field("NA") == ""
    assert normalize_text_field("Hello") == "Hello"
