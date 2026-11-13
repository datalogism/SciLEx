"""Inter-annotator agreement: Krippendorff's alpha with the MASI distance.

Each annotation dimension (``TASK``, ``GRANULARITY``…) is a multi-label field:
an annotator gives a paper a *set* of values (``{"Ner", "RelationExtraction"}``).
Agreement on such sets is measured, as in the SciLEx review of relation
extraction, with Krippendorff's alpha and the MASI distance (Passonneau 2006):

    MASI(A, B) = 1 - J(A, B) * M(A, B)

with J the Jaccard index and M = 1 if A = B, 2/3 if one includes the other,
1/3 if they overlap otherwise, 0 if they are disjoint.

    alpha = 1 - D_o / D_e

D_o is the mean distance between the values given to the same paper, D_e the
mean distance between any two values given in the study. Only papers coded by
at least two annotators count (Krippendorff's "pairable" values).

Reading guide (Krippendorff 2004): alpha >= 0.8 good, >= 0.667 tentative
conclusions only; below, :func:`level` uses moderate (>= 0.4), fair (>= 0.2)
and poor, the scale of the review's Table 3.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

PLACEHOLDER = "?"


def masi_distance(a: frozenset, b: frozenset) -> float:
    """MASI distance between two sets of values (0: identical, 1: disjoint)."""
    if a == b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    jaccard = len(a & b) / len(union)
    if a <= b or b <= a:
        monotonicity = 2 / 3
    elif a & b:
        monotonicity = 1 / 3
    else:
        monotonicity = 0.0
    return 1.0 - jaccard * monotonicity


def alpha(units: Iterable[Iterable[frozenset]], distance=masi_distance) -> float:
    """Krippendorff's alpha of ``units`` (one list of coders' values per paper).

    Returns NaN when fewer than two pairable values exist, and 1.0 when every
    value is the same (no disagreement is possible).
    """
    pairable = [list(values) for values in units]
    pairable = [values for values in pairable if len(values) >= 2]
    n = sum(len(values) for values in pairable)
    if n < 2:
        return math.nan
    observed = 0.0
    for values in pairable:
        m = len(values)
        total = sum(
            distance(values[i], values[j]) for i in range(m) for j in range(m) if i != j
        )
        observed += total / (m - 1)
    observed /= n
    pooled = [value for values in pairable for value in values]
    expected = sum(
        distance(pooled[i], pooled[j]) for i in range(n) for j in range(n) if i != j
    ) / (n * (n - 1))
    if expected == 0:
        return 1.0 if observed == 0 else math.nan
    return 1.0 - observed / expected


def level(value: float) -> str:
    """Reading of an alpha: good, tentative, moderate, fair, poor (or n/a)."""
    if value is None or math.isnan(value):
        return "n/a"
    for threshold, name in (
        (0.8, "good"),
        (0.667, "tentative"),
        (0.4, "moderate"),
        (0.2, "fair"),
    ):
        if value >= threshold:
            return name
    return "poor"


def codes_by_dimension(tags: Iterable[str]) -> dict[str, frozenset]:
    """``DIMENSION:value`` tags as ``{DIMENSION: {values}}`` (placeholders left out)."""
    from scilex import review_tags
    from scilex.tagging.auto_tags import is_auto_tag

    found: dict[str, set] = {}
    for tag in tags:
        tag = str(tag).strip()
        if not tag or review_tags.is_workflow_tag(tag) or is_auto_tag(tag):
            continue  # LLM proposals (DIM-AUTO:value) are not codes
        dimension, sep, value = tag.partition(":")
        dimension, value = dimension.strip().upper(), value.strip()
        if not sep or not dimension or " " in dimension or not value:
            continue
        if value == PLACEHOLDER:
            found.setdefault(dimension, set())
            continue
        found.setdefault(dimension, set()).add(value)
    return {dimension: frozenset(values) for dimension, values in found.items()}


@dataclass
class DimensionAgreement:
    """Agreement on one dimension."""

    dimension: str
    alpha: float
    papers: int  # papers coded on it by at least two annotators
    values: int  # pairable values

    @property
    def level(self) -> str:
        return level(self.alpha)


def by_dimension(
    copies: Mapping[str, Mapping[str, Iterable[str]]],
    *,
    skip_uncoded: bool = True,
) -> list[DimensionAgreement]:
    """Agreement per dimension of a cross-annotation study.

    Args:
        copies: ``{paper: {annotator: tags}}``, the tags each annotator gave
            their copy of the paper.
        skip_uncoded: An annotator who left a dimension empty (or ``?``) does
            not count for it; otherwise "no value" is a value.
    """
    coded = {
        paper: {who: codes_by_dimension(tags) for who, tags in by_coder.items()}
        for paper, by_coder in copies.items()
    }
    dimensions = sorted(
        {d for by_coder in coded.values() for codes in by_coder.values() for d in codes}
    )
    result = []
    for dimension in dimensions:
        units = []
        for by_coder in coded.values():
            values = []
            for codes in by_coder.values():
                value = codes.get(dimension, frozenset())
                if skip_uncoded and not value:
                    continue
                values.append(value)
            if len(values) >= 2:
                units.append(values)
        result.append(
            DimensionAgreement(
                dimension=dimension,
                alpha=alpha(units),
                papers=len(units),
                values=sum(len(values) for values in units),
            )
        )
    return result


@dataclass
class MergeProposal:
    """Codes to write on a reference paper after a cross-annotation."""

    agreed: list[str]  # given by every annotator who coded the dimension
    majority: list[str]  # given by more than half of them
    disputed: list[str]  # the others (to adjudicate)


def merge_proposal(by_coder: Mapping[str, Iterable[str]]) -> MergeProposal:
    """Split the codes of one paper's copies into agreed / majority / disputed."""
    coded = [codes_by_dimension(tags) for tags in by_coder.values()]
    agreed, majority, disputed = [], [], []
    for dimension in sorted({d for codes in coded for d in codes}):
        coders = [codes[dimension] for codes in coded if codes.get(dimension)]
        if not coders:
            continue
        for value in sorted(set().union(*coders)):
            votes = sum(value in values for values in coders)
            tag = f"{dimension}:{value}"
            if votes == len(coders):
                agreed.append(tag)
            elif votes * 2 > len(coders):
                majority.append(tag)
            else:
                disputed.append(tag)
    return MergeProposal(agreed, majority, disputed)
