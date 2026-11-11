"""First/last author h-index enrichment via Semantic Scholar (issue #45).

Two batch calls: ``POST /graph/v1/paper/batch`` (authors.authorId by DOI) then
``POST /graph/v1/author/batch`` (hIndex). Adds ``first_author_hindex`` and
``last_author_hindex`` columns; does not influence the relevance score.
"""

import logging
import time

import pandas as pd
import requests
from tenacity import retry, retry_if_exception, stop_after_attempt

from scilex.citations.citations_tools import (
    is_retryable_http_error,
    wait_retry_after_or_backoff,
)
from scilex.config_defaults import get_rate_limit
from scilex.constants import normalize_doi

SS_API_BASE = "https://api.semanticscholar.org/graph/v1"
PAPER_BATCH_SIZE = 500
AUTHOR_BATCH_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


@retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_retry_after_or_backoff,
    reraise=True,
)
def _post_batch_request(endpoint, ids, fields, api_key, session=None):
    """POST one batch, retrying 429/5xx/network errors with backoff."""
    http = session or requests
    headers = {"x-api-key": api_key} if api_key else {}
    response = http.post(
        f"{SS_API_BASE}/{endpoint}/batch",
        params={"fields": fields},
        json={"ids": ids},
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _post_batch(endpoint, ids, fields, api_key, session=None):
    """POST one batch; return the list of results (None for unknown ids)."""
    try:
        return _post_batch_request(endpoint, ids, fields, api_key, session)
    except (requests.RequestException, ValueError) as error:
        logging.warning(f"Semantic Scholar {endpoint}/batch failed: {error}")
        return [None] * len(ids)


def extract_first_last_author_ids(paper_record):
    """Return ``(first_author_id, last_author_id)`` from a paper/batch record."""
    authors = (paper_record or {}).get("authors") or []
    ids = [author.get("authorId") for author in authors]
    if not ids:
        return None, None
    return ids[0], ids[-1]


def enrich_with_author_hindex(df, api_key=None, session=None, pause_seconds=None):
    """Add ``first_author_hindex`` / ``last_author_hindex`` (nullable Int64).

    Args:
        df: DataFrame with a ``DOI`` column.
        api_key: Semantic Scholar API key (optional but recommended).
        session: Injectable HTTP client exposing ``post`` (tests).
        pause_seconds: Delay between calls; defaults to the configured SS rate limit.

    Returns:
        pd.DataFrame: copy of ``df`` with the two columns (NA when unknown).
    """
    df = df.copy()
    if pause_seconds is None:
        pause_seconds = 1.0 / get_rate_limit("SemanticScholar", bool(api_key))
    dois = df["DOI"].map(normalize_doi)
    unique_dois = sorted({doi for doi in dois if doi})

    author_ids_by_doi = {}
    for chunk in _chunks(unique_dois, PAPER_BATCH_SIZE):
        records = _post_batch(
            "paper",
            [f"DOI:{doi}" for doi in chunk],
            "authors.authorId",
            api_key,
            session,
        )
        for doi, record in zip(chunk, records, strict=False):
            author_ids_by_doi[doi] = extract_first_last_author_ids(record)
        time.sleep(pause_seconds)

    needed_author_ids = sorted(
        {aid for pair in author_ids_by_doi.values() for aid in pair if aid}
    )
    hindex_by_author = {}
    for chunk in _chunks(needed_author_ids, AUTHOR_BATCH_SIZE):
        records = _post_batch("author", chunk, "hIndex,citationCount", api_key, session)
        for author_id, record in zip(chunk, records, strict=False):
            if record and record.get("hIndex") is not None:
                hindex_by_author[author_id] = int(record["hIndex"])
        time.sleep(pause_seconds)

    def hindex_for(doi, position):
        author_id = author_ids_by_doi.get(doi, (None, None))[position]
        return hindex_by_author.get(author_id)

    df["first_author_hindex"] = pd.array(
        [hindex_for(doi, 0) for doi in dois], dtype="Int64"
    )
    df["last_author_hindex"] = pd.array(
        [hindex_for(doi, 1) for doi in dois], dtype="Int64"
    )
    logging.info(
        f"Author h-index: first author resolved for "
        f"{int(df['first_author_hindex'].notna().sum()):,}/{len(df):,} papers"
    )
    return df
