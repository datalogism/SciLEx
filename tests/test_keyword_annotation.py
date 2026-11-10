"""Tagging papers with the search keywords found in their text."""

import pandas as pd

from scilex import keyword_annotation as kw


def frame():
    return pd.DataFrame(
        {
            "title": [
                "Relation Extraction with BART",
                "A survey of slot filling",
                "Other",
            ],
            "abstract": ["We study data to text.", "NA", "Nothing here."],
            "collect_keywords": ["Collect_KW1:Triple Extraction", "NA", ""],
        }
    )


def test_keyword_groups_accepts_groups_and_flat_lists():
    assert kw.keyword_groups({"keywords": [["a", " b "], ["c"]]}) == [["a", "b"], ["c"]]
    assert kw.keyword_groups({"keywords": ["a", "b"]}) == [["a", "b"]]
    assert kw.keyword_groups({}) == []


def test_annotate_adds_matches_and_keeps_existing_tags():
    data = frame()
    groups = [["Relation extraction", "Slot Filling"], ["Survey"]]
    report = kw.annotate_keywords(data, groups, ["Data to text"])

    assert data.loc[0, "collect_keywords"] == (
        "Collect_KW1:Triple Extraction;Collect_KW1:Relation extraction"
    )
    assert (
        data.loc[1, "collect_keywords"] == "Collect_KW1:Slot Filling;Collect_KW2:Survey"
    )
    assert data.loc[2, "collect_keywords"] == ""
    assert data.loc[0, "bonus_keyword_tags"] == "BK:Data to text"
    assert (report.papers, report.matched, report.updated, report.tags_added) == (
        3,
        2,
        2,
        4,
    )
    assert "Never found" not in report.message()

    # A second run adds nothing (tags are compared case-insensitively).
    again = kw.annotate_keywords(data, groups, ["Data to text"])
    assert again.tags_added == 0 and again.updated == 0


def test_row_filter_limits_the_papers():
    data = frame()
    report = kw.annotate_keywords(
        data, [["Slot Filling", "Missing term"]], row_filter=lambda d: d.iloc[1:2]
    )
    assert report.papers == 1 and report.updated == 1
    assert "Never found: Missing term" in report.message()
    assert data.loc[0, "collect_keywords"] == "Collect_KW1:Triple Extraction"
