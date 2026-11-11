"""Enrich one paper of a review (from Explore), with the enrichers of ⑥ Enrich.

Each source runs exactly as in ⑥ Enrich, limited to that paper: what it
fills is written into the review's results (and shared through Zotero by the
sync). Cached answers are reused.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from scilex.gui.services.workspace import Review

SOURCES = {
    "crossref": "Crossref (abstract, venue, licence, citations)",
    "lpwc": "Linked Papers With Code (tasks, datasets, code)",
    "orkg": "ORKG (research fields and problems)",
    "paper_types": "Paper type (default type tag)",
    "search_keywords": "Search keywords (Collect_KW tags)",
}


def one_paper(key: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Row filter keeping the paper ``key`` only."""
    from scilex.gui.services.screening import paper_key

    def keep(data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return data
        return data[data.apply(paper_key, axis=1) == key]

    return keep


def enrich_paper(
    review: Review, key: str, source: str, progress, cancel_event=None
) -> str:
    """Run ``source`` on the paper ``key``; return the enricher's message.

    Raises:
        ValueError: Unknown source.
        AnalysisError: The enricher failed (e.g. offline).
    """
    from scilex.gui.services import analyses
    from scilex.gui.services.workspace import Workspace

    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}")
    config = Workspace.load_config(review)
    result = analyses.RUNNERS[source](
        config, progress, row_filter=one_paper(key), cancel_event=cancel_event
    )
    return result.message


def fresh_record(review: Review, key: str) -> dict | None:
    """The paper's row as written now (None if it is gone)."""
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.screening import paper_key

    data = read_results(review.results_path)
    if data is None:
        return None
    for row in data.to_dict("records"):
        if paper_key(row) == key:
            return row
    return None


def tag_types(results_path) -> int:
    """Give every paper without one its default ``PAPER_TYPE`` tag.

    Called after each collect, import and extension, so every paper of a
    review has a type. Tags people set are kept. Never raises: a failure only
    leaves the papers untyped (the analyses still use the default type).

    Returns:
        The number of papers tagged.
    """
    import logging
    from pathlib import Path

    from scilex import paper_types
    from scilex.gui.services import results_store
    from scilex.gui.services.extend import read_results

    try:
        data = read_results(Path(results_path))
        if data is None or data.empty:
            return 0
        before = data.copy()
        if "tags" not in before.columns:
            before["tags"] = ""
        tagged = paper_types.annotate(data)
        if tagged:
            results_store.write_changes(results_path, before, data)
        return tagged
    except Exception:
        logging.getLogger(__name__).warning("Cannot tag the paper types", exc_info=True)
        return 0
