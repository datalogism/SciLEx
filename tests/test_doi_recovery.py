"""DOI recovery via CrossRef (HTTP mocked)."""

from unittest.mock import MagicMock

import pandas as pd

from scilex.pipeline.doi_recovery import (
    first_author_family_name,
    lookup_doi,
    recover_missing_dois,
    select_best_candidate,
    title_similarity,
)


def _item(title, doi, year=2020):
    return {"title": [title], "DOI": doi, "issued": {"date-parts": [[year]]}}


def test_title_similarity_ignores_case_and_punctuation():
    assert title_similarity("Deep Learning: A Survey!", "deep learning a survey") == 1.0


def test_first_author_family_name():
    assert first_author_family_name("Doe, Jane; Roe, Rick") == "Doe"
    assert first_author_family_name("Jane Doe;Rick Roe") == "Doe"
    assert first_author_family_name("NA") is None


def test_select_best_candidate_threshold_and_year():
    items = [_item("Graph neural networks for chemistry", "10.1/ABC", 2020)]
    assert (
        select_best_candidate(items, "Graph neural networks for chemistry", 2020, 0.9)
        == "10.1/abc"
    )
    assert select_best_candidate(items, "Totally different title", 2020, 0.9) is None
    assert (
        select_best_candidate(items, "Graph neural networks for chemistry", 2015, 0.9)
        is None
    )


def test_lookup_doi_uses_expected_query_and_survives_errors():
    session = MagicMock()
    session.get.return_value.json.return_value = {
        "message": {"items": [_item("A study of things", "10.2/xyz")]}
    }
    assert lookup_doi("A study of things", "Doe", 2020, session=session) == "10.2/xyz"
    params = session.get.call_args.kwargs["params"]
    assert params["query.bibliographic"] == "A study of things"
    assert params["query.author"] == "Doe" and params["rows"] == 3

    import requests

    session.get.side_effect = requests.ConnectionError("down")
    assert lookup_doi("A study of things", "Doe", session=session) is None


def test_recover_fills_and_removes_duplicates(tmp_path):
    df = pd.DataFrame(
        {
            "title": ["Paper one", "Paper two", "Paper three"],
            "authors": ["Doe, J", "Roe, R", "Poe, E"],
            "date": ["2020", "2021", "2022"],
            "DOI": ["NA", "NA", "10.9/existing"],
        }
    )
    answers = {"Paper one": "10.1/one", "Paper two": "10.9/existing"}
    calls = []

    def fake_lookup(title, author, year, min_similarity, mailto):
        calls.append(title)
        return answers.get(title)

    cache_path = str(tmp_path / "cache.json")
    out, stats = recover_missing_dois(df, cache_path=cache_path, lookup=fake_lookup)
    assert list(out["DOI"]) == ["10.1/one", "10.9/existing"]
    assert stats["recovered"] == 1 and stats["duplicates_removed"] == 1
    assert df["DOI"].tolist()[0] == "NA"  # input untouched

    calls.clear()
    _, stats2 = recover_missing_dois(df, cache_path=cache_path, lookup=fake_lookup)
    assert calls == [] and stats2["cache_hits"] == 2
