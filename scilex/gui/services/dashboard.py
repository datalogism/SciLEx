"""Data of the Dashboard step: every paper with its properties, and the network.

The page (``scilex/gui/assets/dashboard.js``, D3 + crossfilter) draws
cross-filtered charts from this payload: brushing years or citations,
clicking a bar or a network node filters every other view. Nothing here
draws; the payload is plain JSON:

``papers``
    one entry per paper: key, title, year, numbers (citations, citations
    from the corpus, PageRank, relevance), screening decision, eligibility
    (criteria not met) and the values of each facet of
    :data:`scilex.gui.services.screening.FACETS` plus the paper type.
``links``
    citation links between corpus papers (``[citing index, cited index]``),
    from the citation network fetched in Enrich.
``facets``
    facet id -> label, only the facets with more than one value.
"""

from __future__ import annotations

import math

from scilex.constants import is_valid, normalize_doi
from scilex.gui.services import criteria as criteria_service
from scilex.gui.services.screening import (
    DECISION_LABELS,
    FACETS,
    NONE_VALUE,
    CitationNetwork,
    ScreeningSession,
)

# Facets left out of the charts (one value per paper, or noise).
SKIPPED_FACETS = {"imported"}
PAPER_TYPE = "paper_type"
DECISION = "decision"
ELIGIBILITY = "eligibility"
VALIDATED_BY = "validated_by"  # ANNOT_VALID_BY:<id> tags
ALWAYS_SHOWN = (DECISION, ELIGIBILITY, VALIDATED_BY)
ELIGIBLE, NOT_ELIGIBLE, KEPT = (
    "Meets the criteria",
    "Fails a criterion",
    "Kept by an exception",
)
MAX_VALUES = 40  # values per facet sent to the charts (the most frequent)


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _metric(record: dict, *columns: str) -> float | None:
    for column in columns:
        if is_valid(record.get(column)):
            number = _number(record.get(column))
            if number is not None:
                return number
    return None


def eligibility_label(states: dict[str, tuple[str, str]]) -> str:
    if any(state == criteria_service.EXCLUDED for state, _ in states.values()):
        return NOT_ELIGIBLE
    if any(state == criteria_service.KEPT for state, _ in states.values()):
        return KEPT
    return ELIGIBLE


def payload(
    session: ScreeningSession,
    verdicts: dict[str, dict[str, tuple[str, str]]] | None = None,
    network: CitationNetwork | None = None,
    criteria: list | None = None,
) -> dict:
    """The dashboard data of the papers of ``session``."""
    from scilex.paper_types import effective_types

    verdicts = verdicts or {}
    papers = []
    index_of_doi: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    for row in session.rows:
        key = row["paper_key"]
        record = session.record(key)
        facets = {
            facet: sorted(values - {NONE_VALUE})
            for facet, values in session.facets_of(key).items()
            if facet not in SKIPPED_FACETS
        }
        facets[PAPER_TYPE] = effective_types(record)
        decision = session.decision_of(key)
        facets[DECISION] = [
            DECISION_LABELS[decision.decision] if decision else "Undecided"
        ]
        states = verdicts.get(key, {})
        facets[ELIGIBILITY] = [eligibility_label(states)]
        for facet, values in facets.items():
            bucket = counts.setdefault(facet, {})
            for value in values:
                bucket[value] = bucket.get(value, 0) + 1
        doi = (
            normalize_doi(str(record.get("DOI"))) if is_valid(record.get("DOI")) else ""
        )
        if doi:
            index_of_doi[doi] = len(papers)
        papers.append(
            {
                "key": key,
                "title": row["title"] or "(no title)",
                "year": row["year"],
                "venue": row["venue"],
                "citations": row["citations"],
                "in_corpus": row["cited_in_corpus"],
                "pagerank": _metric(record, "metric_pagerank", "pagerank"),
                "relevance": row["score"],
                "fails": {
                    cid: cause
                    for cid, (state, cause) in states.items()
                    if state == criteria_service.EXCLUDED
                },
                "f": facets,
            }
        )
    # Keep the most frequent values of each facet; the rest become "Other".
    kept_values = {
        facet: {v for v, _ in sorted(c.items(), key=lambda x: -x[1])[:MAX_VALUES]}
        for facet, c in counts.items()
    }
    for paper in papers:
        for facet, values in paper["f"].items():
            known = [v for v in values if v in kept_values[facet]]
            if len(known) < len(values):
                known.append("Other")
            paper["f"][facet] = known
    labels = {
        PAPER_TYPE: "Paper type",
        DECISION: "Screening decision",
        ELIGIBILITY: "Eligibility",
        **{f: label for f, label in FACETS.items() if f not in SKIPPED_FACETS},
    }
    facets = {
        facet: label
        for facet, label in labels.items()
        if len(counts.get(facet, {})) > 1
        # Always charted when present: the quick filters of the dashboard use them.
        or (facet in ALWAYS_SHOWN and counts.get(facet))
    }
    links = []
    if network:
        seen = set()
        for doi, i in index_of_doi.items():
            for cited in network.references.get(doi, ()):
                j = index_of_doi.get(cited)
                if j is not None and j != i and (i, j) not in seen:
                    seen.add((i, j))
            for citer in network.citers.get(doi, ()):
                j = index_of_doi.get(citer)
                if j is not None and j != i and (j, i) not in seen:
                    seen.add((j, i))
        links = sorted(seen)
    return {
        "papers": papers,
        "links": [list(link) for link in links],
        "facets": facets,
        "criteria": {c.id: c.name for c in criteria or [] if c.enabled},
    }
