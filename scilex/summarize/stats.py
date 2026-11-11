"""Compute statistical summaries per cluster from the clusters CSV."""

import logging
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from scilex.constants import is_valid
from scilex.keyword_suggestions.extractor import title_bigrams
from scilex.pipeline_utils import parse_keyword_values

logger = logging.getLogger(__name__)


@dataclass
class ClusterStats:
    """Summary statistics for a single cluster."""

    cluster_id: int
    size: int
    top_keywords: list[tuple[str, int]] = field(default_factory=list)
    top_authors: list[tuple[str, int]] = field(default_factory=list)
    year_range: tuple[int | None, int | None] = (None, None)
    hub_paper: str = ""
    hub_pagerank: float = 0.0


def compute_cluster_stats(
    df: pd.DataFrame,
    top_n_keywords: int = 10,
    top_n_authors: int = 5,
) -> list[ClusterStats]:
    """Compute summary statistics for each cluster.

    Args:
        df: DataFrame with at least ``cluster_id``, ``pagerank`` columns,
            and optionally ``tags``/``keywords``, ``authors``, ``date``, ``title``.
        top_n_keywords: Number of top keywords to extract per cluster.
        top_n_authors: Number of top authors to extract per cluster.

    Returns:
        List of ClusterStats, one per cluster, sorted by cluster_id.
    """
    if "cluster_id" not in df.columns:
        logger.warning("No cluster_id column found")
        return []

    stats = []
    for cluster_id, group in df.groupby("cluster_id"):
        if cluster_id == -1:
            continue  # Skip unclustered papers

        cs = ClusterStats(cluster_id=int(cluster_id), size=len(group))

        # Top keywords
        cs.top_keywords = _extract_keywords(group, top_n_keywords)

        # Top authors
        cs.top_authors = _extract_authors(group, top_n_authors)

        # Year range
        cs.year_range = _extract_year_range(group)

        # Hub paper (highest PageRank)
        if "pagerank" in group.columns:
            hub_idx = group["pagerank"].astype(float).idxmax()
            hub_row = group.loc[hub_idx]
            cs.hub_paper = str(hub_row.get("title", ""))
            cs.hub_pagerank = float(hub_row["pagerank"])

        stats.append(cs)

    stats.sort(key=lambda s: s.cluster_id)
    logger.info(f"Computed stats for {len(stats)} clusters")
    return stats


def _extract_keywords(group: pd.DataFrame, top_n: int) -> list[tuple[str, int]]:
    """Extract top keywords from a cluster group.

    Uses the ``tags``/``keywords`` columns; when they are absent or empty (the
    aggregated CSV has none), falls back to title bigrams, counted once per paper.
    """
    counter: Counter[str] = Counter()

    for col in ("tags", "keywords", "keyword"):
        if col not in group.columns:
            continue
        for val in group[col]:
            if not is_valid(val):
                continue
            for kw in parse_keyword_values(str(val)):
                counter[kw] += 1

    if not counter and "title" in group.columns:
        for title in group["title"]:
            if is_valid(title):
                counter.update(set(title_bigrams(str(title))))

    return counter.most_common(top_n)


def _extract_authors(group: pd.DataFrame, top_n: int) -> list[tuple[str, int]]:
    """Extract top authors from a cluster group."""
    counter: Counter[str] = Counter()

    if "authors" not in group.columns:
        return []

    for val in group["authors"]:
        if not is_valid(val):
            continue
        for author in str(val).split(";"):
            author = author.strip()
            if author and len(author) > 1:
                counter[author] += 1

    return counter.most_common(top_n)


def _extract_year_range(
    group: pd.DataFrame,
) -> tuple[int | None, int | None]:
    """Extract min and max publication year from a cluster group."""
    years = []
    for col in ("date", "year"):
        if col not in group.columns:
            continue
        for val in group[col]:
            if not is_valid(val):
                continue
            try:
                year = int(str(val)[:4])
                if 1900 <= year <= 2100:
                    years.append(year)
            except (ValueError, IndexError):
                continue
        if years:
            break

    if not years:
        return (None, None)
    return (min(years), max(years))
