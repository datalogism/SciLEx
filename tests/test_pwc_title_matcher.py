"""Characterization tests for TitleMatcher."""

from scilex.PapersWithCode.title_matcher import TitleMatcher


def test_normalize_title_basic():
    assert (
        TitleMatcher.normalize_title("BERT: Pre-training of Deep Bidirectional")
        == "bert pre-training of deep bidirectional"
    )


def test_normalize_title_latex_and_accents():
    assert (
        TitleMatcher.normalize_title(r"\textbf{Bold} Café $x^2$ model") == "cafe model"
    )


def test_normalize_title_missing():
    assert TitleMatcher.normalize_title("NA") == ""
    assert TitleMatcher.normalize_title(None) == ""


def test_default_threshold():
    assert TitleMatcher().threshold == 85


def test_find_best_match_exact():
    matcher = TitleMatcher()
    candidates = [
        {"title": "Other paper entirely"},
        {"title": "Attention Is All You Need"},
    ]
    match, score = matcher.find_best_match(
        "Attention is all you need!", candidates, key="title"
    )
    assert match is candidates[1]
    assert score == 100


def test_find_best_match_token_sort_reordering():
    matcher = TitleMatcher()
    candidates = [{"title": "need you all is Attention"}]
    match, score = matcher.find_best_match(
        "Attention is all you need", candidates, key="title"
    )
    assert match is not None
    assert score == 100


def test_find_best_match_below_threshold():
    matcher = TitleMatcher()
    match, score = matcher.find_best_match(
        "Graph neural networks", [{"modelId": "resnet-50"}]
    )
    assert (match, score) == (None, 0)


def test_find_best_match_empty_candidates():
    assert TitleMatcher().find_best_match("x", []) == (None, 0)
