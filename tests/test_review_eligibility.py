"""Screening state computed from workflow tags (V7 SCREEN / EXCLUSION view)."""

import pandas as pd

from scilex import review_tags as rt
from scilex.gui.services import criteria as cr
from scilex.tagging.grid import dimension_values, normalize_grid

CODES = {"C3": "C3-Language", "C8": "IF-Citation", "C9": "IF-Citation"}
ORDER = ["C1", "C3", "C6", "C8", "C9"]


def test_filter_discard_alone_is_an_automatic_exclusion():
    tags = "DELETED_BY:filter:C9 Citations 0 < 1;DELETED_BY:filter:C3 written in fr"
    state = rt.eligibility(tags, CODES, ORDER)
    assert state.excluded
    assert state.method == rt.AUTO
    # Protocol order, not tag order; codes of the grid.
    assert state.exclusion == "C3-Language"
    assert state.exclusion_all == ["C3-Language", "IF-Citation"]
    assert state.exceptions == []


def test_screen_include_keeps_a_paper_failing_criteria():
    tags = "SCREEN:Include;DELETED_BY:filter:C8 Citations 0 < 2;KEEP:C1"
    assert not rt.workflow(tags).deleted
    state = rt.eligibility(tags, CODES, ORDER)
    assert not state.excluded
    assert state.method == rt.MANUAL
    assert state.exclusion == ""
    assert state.exceptions == ["IF-Citation", "C1"]


def test_screened_collection_keeps_a_paper():
    state = rt.eligibility("KEEP:screened;DELETED_BY:filter:C6 no DOI", {}, ORDER)
    assert not state.excluded
    assert state.exceptions == ["C6"]


def test_a_person_discard_wins_over_a_keep():
    tags = "SCREEN:Include;DELETED_BY:0000-0002-1825-0097;DELETED_BY:filter:C6 x"
    state = rt.eligibility(tags, CODES, ORDER)
    assert state.excluded
    assert state.method == rt.MANUAL
    assert state.exclusion == "C6"


def test_undecided_paper():
    state = rt.eligibility("TASK:RE", CODES, ORDER)
    assert (state.excluded, state.method, state.exclusion) == (False, "", "")


def test_screen_tags_are_not_kept_as_keep_or_workflow():
    state = rt.workflow("SCREEN:Exclude;KEEP:C2")
    assert state.excluded and not state.included
    assert state.keep == ["C2"]
    assert rt.eligibility(state).method == rt.MANUAL


def test_exclusion_codes_from_grid_values():
    grid = normalize_grid(
        pd.DataFrame(
            {
                "tag": ["EXCLUSION"],
                "detail": ["Reason code. Values: C1-Period, C3-Language, IF-Citation"],
            }
        )
    )
    values = dimension_values(grid, "EXCLUSION")
    assert values == ["C1-Period", "C3-Language", "IF-Citation"]
    criteria = [
        cr.Criterion("C1", "Period", "period"),
        cr.Criterion("C3", "Language", "language"),
        cr.Criterion(
            "C9",
            "InterCitation",
            "metric",
            params={"conditions": [{"metric": "cited_in_corpus"}]},
        ),
        cr.Criterion("C10", "Custom", "text"),
    ]
    assert cr.exclusion_codes(criteria, values) == {
        "C1": "C1-Period",
        "C3": "C3-Language",
        "C9": "IF-Citation",
        "C10": "C10",
    }


def test_allowed_values_column_wins():
    grid = normalize_grid(
        pd.DataFrame(
            {"tag": ["X"], "detail": ["Values: a"], "Allowed values": ["b · c, d"]}
        )
    )
    assert dimension_values(grid, "x") == ["b", "c", "d"]
    assert dimension_values(grid, "missing") == []
