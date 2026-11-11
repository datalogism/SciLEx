"""Apply quality filters to snowballed papers.

Reuses the existing quality filter infrastructure but **disables keyword
filtering** by default, since snowballed papers are found by citation
proximity, not vocabulary match.
"""

import logging

import pandas as pd

from scilex.constants import is_valid

# Minimum abstract length in characters for the lightweight snowball filter.
# This is intentionally simpler than the word-count check in the full pipeline.
_MIN_ABSTRACT_CHARS = 50

logger = logging.getLogger(__name__)


def apply_snowball_filters(
    papers: list[dict],
    require_abstract: bool = True,
    require_doi: bool = True,
    min_author_count: int = 1,
) -> pd.DataFrame:
    """Filter snowballed papers by basic quality criteria.

    This is intentionally lighter than the full aggregation pipeline:
    no keyword filter, no citation filter (the papers are selected by
    citation proximity), no relevance ranking.

    Args:
        papers: List of paper dicts in internal format.
        require_abstract: Remove papers without abstracts.
        require_doi: Remove papers without DOIs.
        min_author_count: Minimum number of authors.

    Returns:
        DataFrame of papers that passed all filters.
    """
    if not papers:
        return pd.DataFrame()

    df = pd.DataFrame(papers)
    initial = len(df)

    # DOI filter
    if require_doi and "DOI" in df.columns:
        df = df[df["DOI"].apply(lambda x: is_valid(x) and str(x).strip() != "")]
        logger.info(f"DOI filter: {initial} → {len(df)}")

    # Abstract filter
    if require_abstract and "abstract" in df.columns:
        df = df[
            df["abstract"].apply(
                lambda x: is_valid(x) and len(str(x).strip()) > _MIN_ABSTRACT_CHARS
            )
        ]
        logger.info(f"Abstract filter: → {len(df)}")

    # Author count filter
    if "authors" in df.columns:
        df = df[
            df["authors"].apply(
                lambda x: (
                    len(str(x).split(";")) >= min_author_count if is_valid(x) else False
                )
            )
        ]
        logger.info(f"Author filter (>={min_author_count}): → {len(df)}")

    logger.info(f"Snowball filter: {initial} → {len(df)} papers kept")
    return df.reset_index(drop=True)
