"""A missing abstract ("NA"/NaN) must never contribute text to keyword matching."""

import numpy as np
import pandas as pd

from scilex.keyword_validation import generate_keyword_validation_report
from scilex.pipeline.ranking import count_keyword_matches
from scilex.pipeline.text_filter import record_passes_text_filter


def test_ranking_ignores_na_and_nan_abstract():
    for missing in ("NA", np.nan, None):
        row = {"title": "Graphs", "abstract": missing}
        assert count_keyword_matches(row, [["na"], []]) == 0
    assert count_keyword_matches({"title": "x", "abstract": np.nan}, [["nan"]]) == 0


def test_text_filter_ignores_na_abstract_and_joins_paragraph_dict():
    assert not record_passes_text_filter({"title": "t", "abstract": "NA"}, ["na"])
    record = {"title": "t", "abstract": {"p": ["alpha beta", "gamma"]}}
    assert record_passes_text_filter(record, ["gamma"])


def test_report_ignores_na_abstract():
    df = pd.DataFrame({"title": ["Graphs"], "abstract": ["NA"]})
    report = generate_keyword_validation_report(df, [["na"]])
    assert "'na': 0" in report
