"""Deterministic canonical citation count (issue #47).

Several sources report a citation count for the same paper and they disagree.
``canonical_citation_count`` picks one value with a fixed priority so the
citation filter and the ranking are reproducible:

    Semantic Scholar > OpenAlex > CrossRef > raw collected value (``nb_citation``)
"""

import logging
import re

import pandas as pd

from scilex.config_defaults import DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD

CANONICAL_COLUMN = "canonical_citation_count"
SOURCE_PRIORITY = ("semantic_scholar", "openalex", "crossref", "raw")

_EXTRA_SOURCE_PATTERN = re.compile(r"""['"]source['"]\s*:\s*['"]([a-z_]+)['"]""")


def _to_count(value):
    """Return a non-negative int, or None for missing/invalid values."""
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric) or numeric < 0:
        return None
    return int(numeric)


def _fetched_source(extra):
    """Source name recorded by the citation fetcher in the ``extra`` column."""
    match = _EXTRA_SOURCE_PATTERN.search(str(extra))
    return match.group(1) if match else None


def collect_source_counts(row):
    """Gather the citation count each source reports for one paper.

    The fetcher stores a single ``nb_citation``; its ``extra`` column says which
    source produced it, which lets us attribute it to CrossRef or fall back to
    "raw" (OpenCitations / collected value).

    Args:
        row: Mapping-like paper record.

    Returns:
        dict: ``{source: count}`` limited to the sources with a value.
    """
    counts = {
        "semantic_scholar": _to_count(row.get("ss_citation_count")),
        "openalex": _to_count(row.get("oa_citation_count")),
    }
    resolved = _to_count(row.get("nb_citation"))
    fetched_source = _fetched_source(row.get("extra"))
    if fetched_source == "crossref":
        counts["crossref"] = resolved
    elif fetched_source not in ("semantic_scholar", "openalex"):
        counts["raw"] = resolved
    return {source: count for source, count in counts.items() if count is not None}


def pick_canonical_count(source_counts):
    """Pick the count of the highest-priority source, or None if empty."""
    for source in SOURCE_PRIORITY:
        if source in source_counts:
            return source_counts[source]
    return None


def relative_discrepancy(source_counts):
    """Largest relative gap ``(max - min) / max`` across sources (0 if < 2 sources)."""
    values = list(source_counts.values())
    if len(values) < 2 or max(values) == 0:
        return 0.0
    return (max(values) - min(values)) / max(values)


def apply_canonical_citations(
    df, discrepancy_threshold=DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD
):
    """Add the ``canonical_citation_count`` column and log source disagreements.

    Args:
        df: DataFrame with ``nb_citation`` and optionally ``ss_citation_count``,
            ``oa_citation_count``, ``extra``.
        discrepancy_threshold: Relative gap above which a paper is reported.

    Returns:
        pd.DataFrame: ``df`` with the new column (nullable Int64; NA when no
        source has a value).
    """
    canonical = []
    discrepant = []
    for _, row in df.iterrows():
        source_counts = collect_source_counts(row)
        canonical.append(pick_canonical_count(source_counts))
        gap = relative_discrepancy(source_counts)
        if gap > discrepancy_threshold:
            discrepant.append((row.get("DOI"), source_counts, gap))

    df[CANONICAL_COLUMN] = pd.array(canonical, dtype="Int64")

    for doi, source_counts, gap in discrepant[:20]:
        logging.warning(
            f"Citation counts disagree for {doi}: {source_counts} (gap {gap:.0%})"
        )
    if discrepant:
        logging.warning(
            f"{len(discrepant):,} papers have citation sources disagreeing by more than "
            f"{discrepancy_threshold:.0%}; canonical value follows "
            f"{' > '.join(SOURCE_PRIORITY)}"
        )
    logging.info(
        f"Canonical citations: {int(df[CANONICAL_COLUMN].notna().sum()):,} "
        f"of {len(df):,} papers resolved"
    )
    return df
