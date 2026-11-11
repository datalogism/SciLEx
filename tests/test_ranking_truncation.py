"""apply_relevance_ranking logs a warning when max_papers truncates the result."""

import logging

import pandas as pd

from scilex.pipeline.ranking import apply_relevance_ranking


def test_truncation_logs_warning(caplog):
    df = pd.DataFrame(
        {"title": ["a", "b", "c"], "abstract": ["x"] * 3, "itemType": ["x"] * 3}
    )
    with caplog.at_level(logging.WARNING):
        result = apply_relevance_ranking(df, [["a"]], top_n=2)
    assert len(result) == 2
    assert any(
        "truncated" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )
