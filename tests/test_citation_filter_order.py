"""citation_filter: column hygiene, row-order preservation, year-only dates."""

from datetime import datetime

import pandas as pd

from scilex.pipeline.citation_filter import (
    apply_time_aware_citation_filter,
    calculate_paper_age_months,
)


def test_no_doi_early_return_has_no_temp_column_and_leaves_input_untouched():
    df = pd.DataFrame(
        {
            "DOI": ["NA", "NA"],
            "date": ["2020-01-01", "2021-01-01"],
            "nb_citation": [0, 0],
        }
    )
    result = apply_time_aware_citation_filter(df)
    assert "paper_age_months" not in result.columns
    assert "citation_threshold" in result.columns
    assert list(df.columns) == ["DOI", "date", "nb_citation"]


def test_original_row_order_is_preserved():
    df = pd.DataFrame(
        {
            "title": ["a", "b", "c", "d"],
            "DOI": ["10.1/a", "NA", "10.1/c", "NA"],
            "date": [datetime.now().strftime("%Y-%m-%d")] * 4,
            "nb_citation": [0, 0, 0, 0],
        }
    )
    result = apply_time_aware_citation_filter(df)
    assert result["title"].tolist() == ["a", "b", "c", "d"]


def test_year_only_date_is_mid_year_regardless_of_today():
    now = datetime.now()
    age = calculate_paper_age_months(str(now.year - 3))
    expected = (now.year - (now.year - 3)) * 12 + (now.month - 7)
    assert age == expected


def test_no_doi_rows_keep_fallback_citation_count():
    """No-DOI papers bypass the filter without losing SS/OpenAlex fallback counts."""
    df = pd.DataFrame(
        {
            "DOI": ["NA", "10.1/a"],
            "date": ["2015-01-01", "2015-01-01"],
            "nb_citation": [7, 50],
        }
    )
    result = apply_time_aware_citation_filter(df)
    assert result.loc[result["DOI"] == "NA", "nb_citation"].iloc[0] == 7
