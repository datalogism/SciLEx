"""Abstract validation: one scoring pass, one acceptability definition, configured word limits."""

from unittest.mock import patch

import pandas as pd

import scilex.abstract_validation as av

GOOD = (
    "We propose a novel graph neural network architecture for knowledge graph "
    "completion. We evaluate on several benchmarks and report strong results "
    "on link prediction tasks across datasets."
)


def _df(abstracts):
    return pd.DataFrame({"abstract": abstracts, "title": ["T"] * len(abstracts)})


def test_configured_min_words_is_honoured():
    df = _df([GOOD])
    _, lenient = av.validate_dataframe_abstracts(df, min_words=5, generate_report=False)
    _, strict = av.validate_dataframe_abstracts(
        df, min_words=500, generate_report=False
    )
    assert lenient["too_short"] == 0
    assert strict["too_short"] == 1


def test_configured_max_words_is_honoured():
    _, stats = av.validate_dataframe_abstracts(
        _df([GOOD]), min_words=5, max_words=10, generate_report=False
    )
    assert stats["too_long"] == 1


def test_single_acceptability_definition():
    # Missing abstract scores 60 (>= threshold 60) but has a critical issue:
    # stats and the acceptable column must agree that it is not acceptable.
    df = _df(["NA", GOOD])
    scored, stats = av.validate_dataframe_abstracts(
        df, min_quality_score=60, min_words=5, generate_report=False
    )
    assert stats["acceptable"] == 1
    assert scored["abstract_quality_acceptable"].tolist() == [False, True]


def test_each_abstract_scored_once():
    df = _df([GOOD, GOOD, "NA"])
    with patch.object(
        av, "validate_abstract_quality", wraps=av.validate_abstract_quality
    ) as spy:
        av.validate_dataframe_abstracts(df, min_words=5, generate_report=False)
    assert spy.call_count == 3
