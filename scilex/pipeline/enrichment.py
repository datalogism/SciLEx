"""URL and citation enrichment fallback functions for the aggregation pipeline."""

import logging

import pandas as pd

from scilex.constants import doi_to_url, is_valid


def fill_missing_urls_from_doi(df):
    """Fill missing URLs using DOI resolver (https://doi.org/).

    Papers without URLs but with valid DOIs get a URL generated from their DOI.

    Args:
        df: DataFrame with 'url' and 'DOI' columns

    Returns:
        tuple: (DataFrame with URLs filled, stats dict)
    """
    if "url" not in df.columns or "DOI" not in df.columns:
        logging.warning("Cannot fill URLs: missing 'url' or 'DOI' column")
        return df, {"filled": 0, "already_valid": 0, "no_doi": 0}

    df = df.copy()
    url_valid = df["url"].map(is_valid)
    doi_valid = df["DOI"].map(is_valid)
    fill_mask = ~url_valid & doi_valid
    df.loc[fill_mask, "url"] = df.loc[fill_mask, "DOI"].map(doi_to_url)

    stats = {
        "filled": int(fill_mask.sum()),
        "already_valid": int(url_valid.sum()),
        "no_doi": int((~url_valid & ~doi_valid).sum()),
    }

    logging.info(
        f"URL fallback: {stats['filled']} URLs generated from DOIs, "
        f"{stats['already_valid']} already valid, "
        f"{stats['no_doi']} papers without DOI"
    )

    return df, stats


def _fill_unset(df, target_col, source_col):
    """Copy ``source_col`` into ``target_col`` where the target is unset/zero.

    Rows whose source value is NaN are left untouched. Modifies ``df`` in place.
    """
    unset_mask = _unset_citation_mask(df[target_col])
    mask = unset_mask & df[source_col].notna()
    df.loc[mask, target_col] = df.loc[mask, source_col]


def _unset_citation_mask(series):
    """Boolean mask of citation values that are unset (None/NaN/empty) or zero."""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.isna() | (numeric == 0)


def _count_unset_citations(df):
    """Number of rows whose ``nb_citation`` is unset or zero."""
    return int(_unset_citation_mask(df["nb_citation"]).sum())


def use_semantic_scholar_citations_fallback(df):
    """Use Semantic Scholar citation data as fallback when OpenCitations data is missing.

    Args:
        df: DataFrame with both OpenCitations and Semantic Scholar citation data

    Returns:
        pd.DataFrame: DataFrame with citation data filled from Semantic Scholar
    """
    if "ss_citation_count" not in df.columns:
        logging.info(
            "Semantic Scholar citation data not available (only papers from SS API have this)"
        )
        return df

    has_ss_data = df["ss_citation_count"].notna().sum()
    logging.info(f"Found Semantic Scholar citation data for {has_ss_data:,} papers")

    if has_ss_data == 0:
        return df

    initial_zero_count = _count_unset_citations(df)

    _fill_unset(df, "nb_citation", "ss_citation_count")
    _fill_unset(df, "nb_cited", "ss_reference_count")

    final_zero_count = _count_unset_citations(df)
    improved_count = initial_zero_count - final_zero_count

    improved_pct = (improved_count / has_ss_data * 100) if has_ss_data > 0 else 0.0
    logging.info("Semantic Scholar fallback applied:")
    logging.info(f"  Papers with 0 citations before: {initial_zero_count:,}")
    logging.info(f"  Papers with 0 citations after: {final_zero_count:,}")
    logging.info(
        f"  Improved: {improved_count:,} papers ({improved_pct:.1f}% of papers with SS data)"
    )

    return df


def use_openalex_citations_fallback(df):
    """Use OpenAlex citation data as fallback when citation count is still missing.

    Args:
        df: DataFrame with OpenAlex citation data

    Returns:
        pd.DataFrame: DataFrame with nb_citation filled from OpenAlex
    """
    if "oa_citation_count" not in df.columns:
        logging.info(
            "OpenAlex citation data not available (only papers from OpenAlex API have this)"
        )
        return df

    has_oa_data = df["oa_citation_count"].notna().sum()
    logging.info(f"Found OpenAlex citation data for {has_oa_data:,} papers")

    if has_oa_data == 0:
        return df

    initial_zero_count = _count_unset_citations(df)

    _fill_unset(df, "nb_citation", "oa_citation_count")

    final_zero_count = _count_unset_citations(df)
    improved_count = initial_zero_count - final_zero_count

    improved_pct = (improved_count / has_oa_data * 100) if has_oa_data > 0 else 0.0
    logging.info("OpenAlex fallback applied:")
    logging.info(f"  Papers with 0 citations before: {initial_zero_count:,}")
    logging.info(f"  Papers with 0 citations after: {final_zero_count:,}")
    logging.info(
        f"  Improved: {improved_count:,} papers ({improved_pct:.1f}% of papers with OA data)"
    )

    return df
