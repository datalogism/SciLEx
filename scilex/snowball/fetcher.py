"""Fetch metadata for candidate DOIs via Semantic Scholar batch API.

Uses the POST /paper/batch endpoint to retrieve metadata for up to
500 papers per request, then converts each to the internal format
using SemanticScholartoZoteroFormat.
"""

import logging
import urllib.parse

import requests
from ratelimit import limits, sleep_and_retry
from tenacity import retry, retry_if_exception, stop_after_attempt

from scilex.citations.citations_tools import (
    is_retryable_http_error,
    wait_retry_after_or_backoff,
)
from scilex.crawlers.aggregate import SemanticScholartoZoteroFormat

logger = logging.getLogger(__name__)

SS_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"

# No "DOI" field in the S2 API (HTTP 400 "Unrecognized or unsupported fields"):
# the DOI comes from externalIds (see convert_ss_paper).
SS_FIELDS = (
    "title,abstract,authors,url,publicationTypes,publicationVenue,"
    "publicationDate,journal,venue,externalIds,openAccessPdf,"
    "citationCount,referenceCount,paperId"
)

# Maximum DOIs per batch request (SS API limit)
BATCH_SIZE = 500


@sleep_and_retry
@limits(calls=1, period=1)
def _batch_request_no_key(ids: list[str]) -> list[dict]:
    """POST batch request without API key (1 req/sec)."""
    return _do_batch_request(ids, api_key=None)


@sleep_and_retry
@limits(calls=1, period=1)  # S2 keys are granted 1 req/sec by default
def _batch_request_with_key(ids: list[str], api_key: str) -> list[dict]:
    """POST batch request with API key (1 req/sec)."""
    return _do_batch_request(ids, api_key=api_key)


@retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_retry_after_or_backoff,
    reraise=True,
)
def _do_batch_request(ids: list[str], api_key: str | None) -> list[dict]:
    """Execute the SS /paper/batch POST request.

    Args:
        ids: List of paper identifiers (e.g. ``["DOI:10.1234/..."]``).
        api_key: Optional SS API key.

    Transient failures (429, 5xx, network) are retried with exponential
    backoff, honouring ``Retry-After``.

    Returns:
        List of paper dicts (may contain None for not-found papers).
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    resp = requests.post(
        SS_BATCH_URL,
        headers=headers,
        params={"fields": SS_FIELDS},
        json={"ids": ids},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def convert_ss_paper(paper: dict) -> dict:
    """Convert one raw Semantic Scholar paper dict to the internal format.

    Shared by the snowball fetcher and the seed-papers recommendations.
    Missing ``DOI`` is filled from ``externalIds``.
    """
    paper = dict(paper)
    if "paperId" in paper and "paper_id" not in paper:
        paper["paper_id"] = paper["paperId"]
    if "publicationDate" in paper and "publication_date" not in paper:
        paper["publication_date"] = paper["publicationDate"]
    open_access = paper.get("openAccessPdf")
    if isinstance(open_access, dict) and open_access.get("url"):
        paper["open_access_pdf"] = open_access["url"]
    if "authors" not in paper:
        paper["authors"] = []
    external_ids = paper.get("externalIds")
    if not paper.get("DOI") and isinstance(external_ids, dict):
        paper["DOI"] = external_ids.get("DOI")
    return SemanticScholartoZoteroFormat(paper)


def fetch_metadata_batch(
    candidate_dois: list[str],
    api_key: str | None = None,
) -> list[dict]:
    """Fetch metadata for candidate DOIs and convert to internal format.

    Args:
        candidate_dois: List of DOI strings to look up.
        api_key: Optional SS API key for higher rate limits.

    Returns:
        List of paper dicts in internal (Zotero-like) format.
        Papers not found by SS are silently skipped.
    """
    results = []
    total = len(candidate_dois)

    for start in range(0, total, BATCH_SIZE):
        batch_dois = candidate_dois[start : start + BATCH_SIZE]
        ids = [f"DOI:{urllib.parse.quote(d, safe='/')}" for d in batch_dois]

        try:
            if api_key:
                raw_papers = _batch_request_with_key(ids, api_key)
            else:
                raw_papers = _batch_request_no_key(ids)
        except requests.exceptions.RequestException as e:
            logger.warning(f"SS batch request failed: {e}")
            continue

        for paper in raw_papers:
            if paper is None:
                continue
            try:
                results.append(convert_ss_paper(paper))
            except Exception as e:
                doi = paper.get("DOI", paper.get("externalIds", {}).get("DOI", "?"))
                logger.debug(f"Failed to convert paper {doi}: {e}")

        end = min(start + BATCH_SIZE, total)
        logger.info(f"Fetched {end}/{total} candidates ({len(results)} converted)")

    return results
