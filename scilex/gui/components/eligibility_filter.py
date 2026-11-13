"""Eligibility filter shared by Explore and Screen.

Each paper is judged against the enabled eligibility criteria of the review
(on the whole corpus, so duplicates and "top % by PageRank" rules are right);
the filter keeps the eligible papers, those failing any or one given
criterion, or those kept by an exception.
"""

from __future__ import annotations

import pandas as pd

from scilex.gui.services import criteria as criteria_service
from scilex.gui.services.screening import INCLUDE, ScreeningSession

# Special values; "fail:<id>" for one criterion.
ELIGIBLE_ALL = "all"
ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
KEPT_BY_EXCEPTION = "kept"
FAIL_PREFIX = "fail:"

Verdicts = dict[str, dict[str, tuple[str, str]]]


def compute_eligibility(session: ScreeningSession, items: list) -> Verdicts:
    """Each paper's verdicts for the enabled criteria (see :mod:`criteria`)."""
    if not any(c.enabled for c in items) or not session.rows:
        return {}
    data = pd.DataFrame([session.record(row["paper_key"]) for row in session.rows])
    included = {key for key, d in session.decisions.items() if d.decision == INCLUDE}
    return criteria_service.eligibility(items, data, included)


def enabled(items: list) -> list:
    """The enabled criteria of ``items``."""
    return [c for c in items if c.enabled]


def options(keys: list[str], items: list, verdicts: Verdicts) -> dict[str, str]:
    """Choices of the Eligibility filter for papers ``keys``, with their counts."""
    failing = {
        k
        for k in keys
        if any(s == criteria_service.EXCLUDED for s, _ in verdicts.get(k, {}).values())
    }
    kept = {
        k
        for k in keys
        if any(s == criteria_service.KEPT for s, _ in verdicts.get(k, {}).values())
    }
    choices = {
        ELIGIBLE_ALL: "All papers",
        ELIGIBLE: f"Meet all criteria ({len(keys) - len(failing)})",
        NOT_ELIGIBLE: f"Fail a criterion ({len(failing)})",
        KEPT_BY_EXCEPTION: f"Kept by an exception ({len(kept)})",
    }
    for criterion in enabled(items):
        count = sum(
            1
            for verdict in verdicts.values()
            if verdict.get(criterion.id, ("",))[0] == criteria_service.EXCLUDED
        )
        choices[f"{FAIL_PREFIX}{criterion.id}"] = (
            f"Excluded by {criterion.id} – {criterion.name} ({count})"
        )
    return choices


def matches(chosen: str, states: dict[str, tuple[str, str]]) -> bool:
    """Whether a paper with verdicts ``states`` passes the filter value ``chosen``."""
    if chosen == ELIGIBLE_ALL:
        return True
    if chosen == ELIGIBLE:
        return all(s != criteria_service.EXCLUDED for s, _ in states.values())
    if chosen == NOT_ELIGIBLE:
        return any(s == criteria_service.EXCLUDED for s, _ in states.values())
    if chosen == KEPT_BY_EXCEPTION:
        return any(s == criteria_service.KEPT for s, _ in states.values())
    cid = chosen.removeprefix(FAIL_PREFIX)
    return states.get(cid, ("",))[0] == criteria_service.EXCLUDED


def criteria_cells(row: dict, states: dict[str, tuple[str, str]]) -> dict:
    """``row`` with its Criteria column (ids not met, causes as tooltip)."""
    ids = [
        cid + ("*" if state == criteria_service.KEPT else "")
        for cid, (state, _) in states.items()
    ]
    causes = "; ".join(f"{cid}: {cause}" for cid, (_, cause) in states.items())
    return {**row, "criteria": ", ".join(ids), "criteria_causes": causes}


CRITERIA_COLUMN = {
    "field": "criteria",
    "headerName": "Criteria",
    "width": 110,
    "tooltipField": "criteria_causes",
    "headerTooltip": "Eligibility criteria the paper does not meet "
    "(* kept by an exception)",
}
