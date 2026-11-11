"""canonical_citation_count: priority, discrepancy logging, filter/ranking use."""

import logging

import pandas as pd

from scilex.pipeline.canonical_citations import (
    apply_canonical_citations,
    collect_source_counts,
    pick_canonical_count,
    relative_discrepancy,
)
from scilex.pipeline.citation_filter import apply_time_aware_citation_filter
from scilex.pipeline.ranking import calculate_relevance_score


def _row(**kwargs):
    base = {
        "DOI": "10.1/x",
        "nb_citation": 5,
        "ss_citation_count": None,
        "oa_citation_count": None,
        "extra": "{'source': 'opencitations'}",
    }
    base.update(kwargs)
    return pd.Series(base)


def test_priority_ss_over_openalex_over_crossref_over_raw():
    assert pick_canonical_count({"raw": 1, "crossref": 2}) == 2
    assert pick_canonical_count({"crossref": 2, "openalex": 3}) == 3
    assert pick_canonical_count({"openalex": 3, "semantic_scholar": 9}) == 9
    assert pick_canonical_count({}) is None


def test_crossref_attributed_from_extra_and_raw_otherwise():
    assert collect_source_counts(_row(extra="{'source': 'crossref'}")) == {
        "crossref": 5
    }
    assert collect_source_counts(_row()) == {"raw": 5}
    counts = collect_source_counts(_row(ss_citation_count=7, oa_citation_count=0))
    assert counts["semantic_scholar"] == 7 and counts["openalex"] == 0


def test_relative_discrepancy():
    assert relative_discrepancy({"a": 10}) == 0.0
    assert relative_discrepancy({"a": 10, "b": 4}) == 0.6
    assert relative_discrepancy({"a": 0, "b": 0}) == 0.0


def test_apply_sets_column_and_warns(caplog):
    df = pd.DataFrame([_row(ss_citation_count=100, oa_citation_count=10)])
    with caplog.at_level(logging.WARNING):
        out = apply_canonical_citations(df, discrepancy_threshold=0.5)
    assert out["canonical_citation_count"].iloc[0] == 100
    assert "disagree" in caplog.text


def test_no_warning_below_threshold(caplog):
    df = pd.DataFrame([_row(ss_citation_count=10, oa_citation_count=9)])
    with caplog.at_level(logging.WARNING):
        apply_canonical_citations(df, discrepancy_threshold=0.5)
    assert "disagree" not in caplog.text


def test_citation_filter_uses_canonical_column():
    df = pd.DataFrame(
        {
            "DOI": ["10.1/a", "10.1/b"],
            "date": ["2015-01-01", "2015-01-01"],
            "nb_citation": [0, 100],
            "canonical_citation_count": [100, 0],
        }
    )
    result = apply_time_aware_citation_filter(df)
    assert list(result["DOI"]) == ["10.1/a"]


def test_ranking_prefers_canonical():
    base = {"title": "t", "abstract": "a", "quality_score": 0, "itemType": "x"}
    low = calculate_relevance_score(
        pd.Series({**base, "nb_citation": 0}), [], has_citations=True
    )
    high = calculate_relevance_score(
        pd.Series({**base, "nb_citation": 0, "canonical_citation_count": 500}),
        [],
        has_citations=True,
    )
    assert high > low
