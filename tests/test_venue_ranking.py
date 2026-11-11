"""Venue ranking (CORE / SJR) matching and ranking integration."""

import pandas as pd

from scilex.pipeline.ranking import calculate_relevance_score
from scilex.pipeline.venue_ranking import (
    add_venue_rank,
    extract_acronyms,
    load_rankings,
    lookup_venue_rank,
    normalize_venue,
    venue_rank_score,
)


def test_normalization_drops_noise():
    assert (
        normalize_venue(
            "Proceedings of the 22nd International Semantic Web Conference (ISWC 2023)"
        )
        == "semantic web conference iswc"
    )
    assert normalize_venue("PLoS ONE") == normalize_venue("PLOS ONE.")


def test_extract_acronyms():
    assert extract_acronyms("Semantic Web Conference (ISWC 2023)") == ["ISWC"]
    assert extract_acronyms("No acronym here") == []


# Small fixture tables, independent of the shipped data files.
FIXTURE_RANKINGS = (
    {
        normalize_venue("International Conference on Machine Learning"): "A*",
        normalize_venue("International Semantic Web Conference"): "A",
    },
    {"ESWC": "A", "ISWC": "A"},
    {
        normalize_venue("Bioinformatics"): "Q1",
        normalize_venue("Nucleic Acids Research"): "Q1",
    },
)


def test_lookup_journal_conference_acronym_and_unknown():
    def lookup(name):
        return lookup_venue_rank(name, FIXTURE_RANKINGS)

    assert lookup("Bioinformatics") == "Q1"
    assert lookup("International Conference on Machine Learning") == "A*"
    assert lookup("Some Workshop Proceedings (ESWC 2022)") == "A"
    assert lookup("Obscure Local Meeting") == "NA"
    assert lookup("NA") == "NA"


def test_shipped_core_data_loads():
    conference_titles, conference_acronyms, _ = load_rankings()
    assert len(conference_titles) > 100
    assert set(conference_acronyms.values()) <= {"A*", "A", "B", "C"}


def test_add_venue_rank_uses_conference_then_journal():
    df = pd.DataFrame(
        {
            "conferenceName": [
                "NA",
                "International Semantic Web Conference (ISWC)",
                "NA",
            ],
            "journalAbbreviation": ["Nucleic Acids Research", "NA", "Unknown"],
        }
    )
    ranked = add_venue_rank(df, FIXTURE_RANKINGS)
    assert list(ranked["venue_rank"]) == ["Q1", "A", "NA"]
    assert list(add_venue_rank(df.iloc[0:0], FIXTURE_RANKINGS)["venue_rank"]) == []


def test_rank_score():
    assert venue_rank_score("A*") == 10.0
    assert venue_rank_score("NA") is None


def test_ranking_blend_is_opt_in():
    row = pd.Series(
        {
            "title": "t",
            "abstract": "a",
            "quality_score": 0,
            "itemType": "other",
            "venue_rank": "A*",
        }
    )
    off = calculate_relevance_score(row, [])
    on = calculate_relevance_score(
        row, [], config={"quality_filters": {"use_venue_ranking": True}}
    )
    assert off == 0 and on > off
