"""Krippendorff's alpha with MASI, per dimension, and merge proposals."""

import math

import pytest

from scilex import annotation_agreement as ag

F = frozenset


def test_masi_distance():
    assert ag.masi_distance(F("ab"), F("ab")) == 0
    assert ag.masi_distance(F("a"), F("b")) == 1
    assert ag.masi_distance(F("a"), F("ab")) == pytest.approx(1 - 0.5 * 2 / 3)
    assert ag.masi_distance(F("ab"), F("bc")) == pytest.approx(1 - (1 / 3) * (1 / 3))
    assert ag.masi_distance(F(), F()) == 0


def test_alpha_matches_the_nominal_hand_computation():
    # 3 papers, 2 coders, single labels: (a,a) (a,b) (b,b).
    # D_o = 2/6, D_e = 18/30 -> alpha = 1 - (1/3)/0.6 = 4/9.
    units = [[F("a"), F("a")], [F("a"), F("b")], [F("b"), F("b")]]
    assert ag.alpha(units) == pytest.approx(4 / 9)
    assert ag.alpha([[F("a"), F("a")], [F("a"), F("a")]]) == 1.0
    assert math.isnan(ag.alpha([[F("a")]]))  # nothing pairable


def test_levels():
    assert [ag.level(v) for v in (0.9, 0.7, 0.5, 0.3, 0.1)] == [
        "good",
        "tentative",
        "moderate",
        "fair",
        "poor",
    ]
    assert ag.level(math.nan) == "n/a"


def test_by_dimension_ignores_workflow_tags_and_placeholders():
    copies = {
        "rebel": {
            "ann": ["TASK:RE", "LANG:English", "ANNOT:ann", "GRANULARITY:?"],
            "bob": ["TASK:RE", "LANG:English", "ANNOT:bob"],
        },
        "docred": {
            "ann": ["TASK:RE", "LANG:English"],
            "bob": ["TASK:NER", "LANG:English", "GRANULARITY:Document"],
        },
    }
    result = {d.dimension: d for d in ag.by_dimension(copies)}
    assert set(result) == {"TASK", "LANG", "GRANULARITY"}
    assert result["LANG"].alpha == 1.0 and result["LANG"].papers == 2
    assert result["TASK"].alpha < 0.5
    assert result["GRANULARITY"].papers == 0  # coded by one annotator only
    assert "ANNOT" not in result


def test_merge_proposal():
    proposal = ag.merge_proposal(
        {
            "a": ["TASK:RE", "TASK:NER", "LANG:English"],
            "b": ["TASK:RE", "LANG:English"],
            "c": ["TASK:RE", "TASK:NER", "LANG:French"],
        }
    )
    assert proposal.agreed == ["TASK:RE"]
    assert proposal.majority == ["LANG:English", "TASK:NER"]
    assert proposal.disputed == ["LANG:French"]
