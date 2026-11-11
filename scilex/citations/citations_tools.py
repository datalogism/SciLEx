import logging
from urllib.parse import quote

import requests
from ratelimit import limits, sleep_and_retry
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from scilex.constants import normalize_doi

# Direct host: opencitations.net/index/coci/api/v1/ answers with two redirects.
_OC_V1 = "https://api.opencitations.net/index/v1/"
_OC_V2 = "https://api.opencitations.net/index/v2/"
_OC_LIST_KINDS = ("citations", "references")
_OC_COUNT_KINDS = ("citation-count", "reference-count")
_MAX_RETRY_AFTER_SECONDS = 60
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_backoff = wait_exponential(multiplier=1, min=2, max=10)


def is_retryable_http_error(exc: BaseException) -> bool:
    """Retry only transient failures: timeouts, connection errors, 429 and 5xx."""
    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        return (
            response is not None
            and getattr(response, "status_code", None) in _RETRYABLE_STATUS_CODES
        )
    return isinstance(
        exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    )


def wait_retry_after_or_backoff(retry_state) -> float:
    """Honor a numeric Retry-After header (capped at 60 s), else back off."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        retry_after = float(headers.get("Retry-After"))
    except (TypeError, ValueError):
        return _backoff(retry_state)
    return min(max(retry_after, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _oc_url(kind, doi):
    """URL of an OpenCitations operation: v1 for DOI lists, v2 for counts."""
    if kind in _OC_COUNT_KINDS:
        return f"{_OC_V2}{kind}/doi:{quote(doi, safe='/')}"
    return f"{_OC_V1}{kind}/{quote(doi, safe='/')}"


@retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_retry_after_or_backoff,
    reraise=True,
)
@sleep_and_retry
@limits(calls=3, period=1)  # OpenCitations limit: 180 req/min per IP, all threads
def _oc_request(kind, doi):
    """Perform one OpenCitations GET; raises on any HTTP/network failure."""
    logging.debug(f"Requesting {kind} for DOI: {doi}")
    resp = requests.get(_oc_url(kind, doi), timeout=10)
    resp.raise_for_status()
    return resp


def _oc_get(kind, doi):
    """Call one OpenCitations operation for a DOI.

    Transient failures (timeouts, connection errors, 429, 5xx) are retried up to
    3 times; other 4xx errors fail immediately.

    Args:
        kind: "citations", "references", "citation-count" or "reference-count"
        doi: DOI (any common spelling; normalized before the request)

    Returns:
        tuple: (success: bool, data: Response|None, error_type: str)
            error_type is "success", "timeout" or "error".
    """
    clean_doi = normalize_doi(doi)
    if clean_doi is None:
        return (False, None, "error")
    try:
        return (True, _oc_request(kind, clean_doi), "success")
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout while fetching {kind} for DOI: {clean_doi}")
        return (False, None, "timeout")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request failed for {kind} DOI {clean_doi}: {e}")
        return (False, None, "error")


def getCitations(doi):
    """Fetch the list of citing works of a DOI from OpenCitations.

    Returns:
        tuple: (success: bool, data: Response|None, error_type: str)
            error_type is "success", "timeout" or "error".
    """
    return _oc_get("citations", doi)


def getReferences(doi):
    """Fetch the list of works cited by a DOI from OpenCitations.

    Returns:
        tuple: (success: bool, data: Response|None, error_type: str)
            error_type is "success", "timeout" or "error".
    """
    return _oc_get("references", doi)


def _oc_count(kind, doi):
    """Return ``(count, status)`` for one OpenCitations count operation."""
    success, response, status = _oc_get(kind, doi)
    if not success:
        return 0, status
    try:
        return int(response.json()[0]["count"]), "success"
    except (ValueError, KeyError, IndexError, TypeError) as e:
        logging.warning(f"Error parsing {kind} JSON for DOI {doi}: {e}")
        return 0, "error"


def getCitationCounts(doi_str):
    """Fetch the citation and reference counts of a DOI from OpenCitations.

    Uses the v2 count operations: two tiny responses instead of the full lists
    of citing and cited DOIs. An unknown DOI has counts of zero.

    Args:
        doi_str: The DOI string (any common spelling, e.g. with https://doi.org/)

    Returns:
        tuple: (counts_dict, stats_dict)
            - counts_dict: ``{"nb_citations": int, "nb_cited": int}``
            - stats_dict: ``cit_status`` and ``ref_status``, each "success",
              "timeout" or "error"
    """
    clean_doi = normalize_doi(doi_str)
    if clean_doi is None:
        return {"nb_citations": 0, "nb_cited": 0}, {
            "cit_status": "error",
            "ref_status": "error",
        }
    nb_citations, cit_status = _oc_count("citation-count", clean_doi)
    nb_cited, ref_status = _oc_count("reference-count", clean_doi)
    return (
        {"nb_citations": nb_citations, "nb_cited": nb_cited},
        {"cit_status": cit_status, "ref_status": ref_status},
    )


# ============================================================================
# CrossRef Batch Citation Lookup
# ============================================================================

CROSSREF_BATCH_SIZE = 20
"""Max DOIs per CrossRef batch request (URL length safety)."""


@retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_retry_after_or_backoff,
    reraise=True,
)
@sleep_and_retry
@limits(calls=3, period=1)  # Conservative: 3 req/sec (each covers ~20 DOIs)
def getCrossRefCitationsBatch(dois, mailto=None):
    """Fetch citation counts for multiple DOIs in a single CrossRef API call.

    Uses the CrossRef works endpoint with DOI filter and field selection
    to retrieve citation and reference counts in bulk. Much faster than
    per-DOI lookups via OpenCitations (~60 DOIs/sec vs 1 DOI/sec).

    Transient errors (timeouts, connection errors, 429, 5xx) are retried. On a
    400 response the batch is bisected so one malformed DOI only loses itself;
    a lone DOI rejected with 400 is omitted from the result.

    Args:
        dois: List of DOI strings (max ~20 per batch for URL length safety).
        mailto: Email for CrossRef polite pool (10 req/sec vs 5 req/sec).

    Returns:
        dict: {doi_lowercase: (citation_count, reference_count)} for found DOIs.
            DOIs not found in CrossRef are simply omitted from the result.
    """
    clean_dois = [d for d in map(normalize_doi, dois or []) if d is not None]
    if not clean_dois:
        return {}

    filter_str = ",".join(f"doi:{quote(doi, safe='/')}" for doi in clean_dois)
    url = (
        f"https://api.crossref.org/works?"
        f"filter={filter_str}"
        f"&select=DOI,is-referenced-by-count,references-count"
        f"&rows={len(clean_dois)}"
    )
    if mailto:
        url += f"&mailto={mailto}"

    resp = requests.get(url, timeout=30)
    if resp.status_code == 400:
        if len(clean_dois) == 1:
            logging.warning(f"CrossRef rejected DOI {clean_dois[0]} (400); skipping")
            return {}
        middle = len(clean_dois) // 2
        logging.debug(f"CrossRef 400 on batch of {len(clean_dois)}; bisecting")
        results = getCrossRefCitationsBatch(clean_dois[:middle], mailto=mailto)
        results.update(getCrossRefCitationsBatch(clean_dois[middle:], mailto=mailto))
        return results
    resp.raise_for_status()
    items = resp.json()["message"]["items"]

    return {
        item["DOI"].lower(): (
            item.get("is-referenced-by-count", 0),
            item.get("references-count", 0),
        )
        for item in items
    }
