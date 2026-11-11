"""Dedup winner tracking and robustness tests for simple_deduplicate."""

import pandas as pd

from scilex.crawlers.aggregate_parallel import simple_deduplicate


def test_doi_then_title_merge_keeps_true_winner_starred():
    df = pd.DataFrame(
        [
            {"DOI": "10.1/a", "title": "Same Title", "archive": "S"},
            {
                "DOI": "10.1/a",
                "title": "Same Title",
                "archive": "O",
                "abstract": "full abstract",
                "authors": "A B",
                "date": "2024",
            },
            {"DOI": "NA", "title": "Same Title!", "archive": "H"},
        ]
    )
    result, stats = simple_deduplicate(df)
    assert len(result) == 1
    assert result.iloc[0]["archive"] == "S;O*;H"
    assert stats["doi_removed"] == 1
    assert stats["title_removed"] == 1


def test_internal_columns_do_not_leak():
    df = pd.DataFrame(
        [
            {"DOI": "10.1/a", "title": "T", "archive": "S"},
            {"DOI": "10.1/a", "title": "T", "archive": "O"},
        ]
    )
    result, _ = simple_deduplicate(df)
    assert set(result.columns) == {"DOI", "title", "archive"}


def test_empty_dataframe_does_not_raise():
    result, stats = simple_deduplicate(pd.DataFrame())
    assert result.empty
    assert stats["initial_count"] == 0
    assert stats["removal_rate"] == 0


def test_missing_doi_column_still_dedups_by_title():
    df = pd.DataFrame(
        [
            {"title": "Same", "archive": "S"},
            {"title": "same", "archive": "O"},
        ]
    )
    result, stats = simple_deduplicate(df)
    assert len(result) == 1
    assert stats["doi_removed"] == 0
    assert stats["title_removed"] == 1


def test_nan_archive_does_not_crash():
    df = pd.DataFrame(
        [
            {"DOI": "10.1/a", "title": "T", "archive": float("nan")},
            {"DOI": "10.1/a", "title": "T", "archive": "O"},
            {"DOI": "NA", "title": "T", "archive": float("nan")},
        ]
    )
    result, _ = simple_deduplicate(df)
    assert len(result) == 1


def test_no_valid_doi_papers_does_not_crash():
    df = pd.DataFrame(
        [
            {"DOI": "NA", "title": "A", "archive": "S", "collect_keywords": "k1"},
            {"DOI": "NA", "title": "B", "archive": "O", "collect_keywords": "k2"},
        ]
    )
    result, stats = simple_deduplicate(df)
    assert len(result) == 2
    assert stats["doi_removed"] == 0
