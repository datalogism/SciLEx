"""Relevance ranking for the aggregation pipeline."""

import logging
import math

import pandas as pd

from scilex.config_defaults import (
    DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS,
    DEFAULT_RELEVANCE_WEIGHTS,
)
from scilex.keyword_validation import build_searchable_text
from scilex.pipeline.venue_ranking import venue_rank_score


def _lowercase_keywords(keyword_groups, bonus_keywords):
    """Flatten keyword groups and lowercase them, ignoring non-list groups."""
    mandatory = [
        keyword.lower()
        for group in keyword_groups or []
        if isinstance(group, list)
        for keyword in group
    ]
    bonus = [keyword.lower() for keyword in bonus_keywords or []]
    return mandatory, bonus


def _count_matches(row, mandatory_lower, bonus_lower):
    """Count keyword occurrences in the row's title+abstract (bonus at 0.5)."""
    if not mandatory_lower and not bonus_lower:
        return 0

    combined_text = build_searchable_text(row.get("title"), row.get("abstract")).lower()

    match_count = sum(combined_text.count(keyword) for keyword in mandatory_lower)
    if bonus_lower:
        bonus_match_count = sum(combined_text.count(keyword) for keyword in bonus_lower)
        match_count += bonus_match_count * 0.5
    return match_count


def count_keyword_matches(row, keyword_groups, bonus_keywords=None):
    """Count total keyword matches in title and abstract.

    Args:
        row: DataFrame row (paper record)
        keyword_groups: List of mandatory keyword groups from config
        bonus_keywords: Optional list of bonus keywords (counted at 0.5 weight)

    Returns:
        float: Total number of keyword matches found (bonus keywords weighted at 0.5)
    """
    if not keyword_groups and not bonus_keywords:
        return 0
    return _count_matches(row, *_lowercase_keywords(keyword_groups, bonus_keywords))


def build_relevance_scorer(
    keyword_groups, has_citations=False, config=None, bonus_keywords=None
):
    """Return a ``row -> score`` function with all row-invariant work hoisted.

    The weights merge, lowercased keyword lists and ``quality_filters`` reads
    are done once here instead of once per paper.

    Components (all normalized to 0-10 scale):
    1. Keyword relevance: Content relevance to search terms
    2. Metadata quality: Completeness and richness of metadata
    3. Publication type: Scholarly publication venue (blended with the
       CORE/SJR venue rank when ``use_venue_ranking`` is enabled)
    4. Citation impact: Research impact (minimal weight to avoid recency bias)

    Args:
        keyword_groups: List of mandatory keyword groups from config
        has_citations: Whether citation data is available
        config: Configuration dict containing quality_filters
        bonus_keywords: Optional list of bonus keywords (weighted at 0.5)

    Returns:
        Callable taking a paper record and returning its 0-10 relevance score.
    """
    quality_filters = (config or {}).get("quality_filters") or {}
    weights = {
        **DEFAULT_RELEVANCE_WEIGHTS,
        **(quality_filters.get("relevance_weights") or {}),
    }
    # Keep the score on 0-10 when user weights do not sum to 1.
    weight_total = sum(
        weights[name] for name in ("keywords", "quality", "itemtype", "citations")
    )
    if weight_total > 0 and not math.isclose(weight_total, 1.0):
        weights = {name: value / weight_total for name, value in weights.items()}
    itemtype_weights = quality_filters.get(
        "itemtype_relevance_weights", DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS
    )
    use_venue_ranking = quality_filters.get("use_venue_ranking", False)
    mandatory_lower, bonus_lower = _lowercase_keywords(keyword_groups, bonus_keywords)
    has_keywords = bool(keyword_groups) or bool(bonus_keywords)

    def score_row(row):
        # 1. Keyword relevance (normalize to 0-10)
        keyword_matches = (
            _count_matches(row, mandatory_lower, bonus_lower) if has_keywords else 0
        )
        keyword_score = min(keyword_matches, 10)

        # 2. Metadata quality (normalize to 0-10)
        quality = row.get("quality_score", 0)
        try:
            quality_score = min(float(quality) / 5, 10)
        except (ValueError, TypeError):
            quality_score = 0

        # 3. Publication type (0 or 10 based on config)
        item_type = str(row.get("itemType", "")).strip()
        itemtype_score = 10 if itemtype_weights.get(item_type, False) else 0
        # Opt-in: blend the CORE / SJR rank of the venue into this component.
        if use_venue_ranking:
            venue_score = venue_rank_score(row.get("venue_rank"))
            if venue_score is not None:
                itemtype_score = (itemtype_score + venue_score) / 2

        # 4. Citation impact (minimal weight to avoid recency bias)
        citation_score = 0
        if has_citations:
            citation_count = pd.to_numeric(
                row.get("canonical_citation_count"), errors="coerce"
            )
            if pd.isna(citation_count):
                citation_count = pd.to_numeric(
                    row.get("nb_citation", 0), errors="coerce"
                )
            if pd.notna(citation_count) and citation_count > 0:
                citation_score = min(math.log(1 + float(citation_count)) * 2.17, 10)

        final_score = (
            keyword_score * weights["keywords"]
            + quality_score * weights["quality"]
            + itemtype_score * weights["itemtype"]
            + citation_score * weights["citations"]
        )

        return round(final_score, 2)

    return score_row


def calculate_relevance_score(
    row, keyword_groups, has_citations=False, config=None, bonus_keywords=None
):
    """Calculate composite relevance score for a single paper.

    Convenience wrapper around ``build_relevance_scorer``; when scoring many
    papers, build the scorer once instead.

    Returns:
        float: Relevance score (0-10 scale, higher = more relevant)
    """
    return build_relevance_scorer(
        keyword_groups, has_citations, config, bonus_keywords
    )(row)


def apply_relevance_ranking(
    df,
    keyword_groups,
    top_n=None,
    has_citations=False,
    config=None,
    bonus_keywords=None,
):
    """Apply composite relevance ranking to DataFrame.

    Args:
        df: DataFrame with papers
        keyword_groups: List of mandatory keyword groups from config
        top_n: Optional - keep only top N most relevant papers
        has_citations: Whether citation data is available
        config: Configuration dict containing quality_filters
        bonus_keywords: Optional list of bonus keywords (weighted at 0.5)

    Returns:
        pd.DataFrame: Ranked DataFrame with relevance_score column
    """
    logging.info("Calculating normalized relevance scores (0-10 scale)...")

    score_row = build_relevance_scorer(
        keyword_groups, has_citations, config, bonus_keywords
    )
    df["relevance_score"] = df.apply(score_row, axis=1)

    df_ranked = df.sort_values("relevance_score", ascending=False).copy()

    logging.info("Relevance scoring complete (normalized 0-10 scale)")
    logging.info(
        f"  Score range: {df_ranked['relevance_score'].min():.2f} - {df_ranked['relevance_score'].max():.2f}"
    )
    logging.info(f"  Mean score: {df_ranked['relevance_score'].mean():.2f}")
    logging.info(f"  Median score: {df_ranked['relevance_score'].median():.2f}")

    if top_n and top_n < len(df_ranked):
        initial_count = len(df_ranked)
        df_ranked = df_ranked.head(top_n)
        logging.warning(
            f"max_papers={top_n}: truncated to the top {top_n} most relevant papers "
            f"(removed {initial_count - top_n:,} of {initial_count:,})"
        )

    return df_ranked
