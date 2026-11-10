"""Fetchers for outgoing references and incoming citers with fallback chains.

Outgoing references (what a paper cites) — three tiers:
  1. SemanticScholar /references  (fast, rich)
  2. CrossRef /works/{doi}        (free, no key; mailto for polite pool)
  3. OpenCitations /references    (3 req/sec shared; last resort)

Incoming citers (who cites a paper) — two tiers:
  1. SemanticScholar /citations   (fast, rich)
  2. OpenCitations /citations     (3 req/sec shared; CrossRef has no free citedBy API)
"""

import json
import logging
import os
import time
import urllib.parse
from collections.abc import Callable

import requests
from ratelimit import limits, sleep_and_retry
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from scilex.citations.citations_tools import getCitations, getReferences

logger = logging.getLogger(__name__)

StopFn = Callable[[], bool] | None
ProgressFn = Callable[[int, int], None] | None


def _stop_requested(should_stop: StopFn) -> bool:
    return should_stop is not None and should_stop()


SS_REFERENCES_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/references"
)
SS_CITATIONS_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/citations"
SS_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
# Papers per batch request: the API accepts 500, but the response is capped at
# 10 MB and nested reference lists are large.
SS_BATCH_SIZE = 100
# The batch endpoint returns at most this many nested links per paper, and it
# silently empties the lists of some papers when a response holds too many
# links (seen with citations: a paper with 9177 citers came back with []).
SS_BATCH_LINK_CAP = 9999
# A batch list shorter than this share of the paper's count is treated as cut.
SS_BATCH_MIN_COMPLETENESS = 0.9
# Seconds to wait before retrying the batches that failed (usually on 429).
SS_BATCH_RETRY_PAUSE = 30
# Consecutive one-by-one SS failures (429, 5xx, timeouts) after which the
# remaining papers skip SemanticScholar and go straight to the fallbacks.
SS_SINGLE_FAILURE_LIMIT = 3
# Log a progress line every this many papers.
PROGRESS_LOG_EVERY = 10
CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"


# ---------------------------------------------------------------------------
# Low-level SS request helpers (two variants for different rate limits)
# ---------------------------------------------------------------------------


def _is_retryable_ss_error(exc: BaseException) -> bool:
    """Return True only for transient SemanticScholar errors worth retrying.

    Retries on 429 (rate-limited), 5xx (server errors), Timeout, and
    ConnectionError.  Does NOT retry on 4xx client errors (401, 403, 404)
    because those will not improve on retry.

    Args:
        exc: The exception to evaluate.

    Returns:
        True if the request should be retried, False otherwise.
    """
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status == 429 or (status is not None and status >= 500)
    return isinstance(
        exc, requests.exceptions.Timeout | requests.exceptions.ConnectionError
    )


@retry(
    retry=retry_if_exception(_is_retryable_ss_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # SS public: 1 req/sec
def _fetch_ss_no_key(doi: str) -> list[str]:
    """Fetch reference DOIs from SemanticScholar without an API key."""
    return _do_ss_request(doi, api_key=None)


@retry(
    retry=retry_if_exception(_is_retryable_ss_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # SS keys default to 1 req/sec
def _fetch_ss_with_key(doi: str, api_key: str) -> list[str]:
    """Fetch reference DOIs from SemanticScholar with an API key."""
    return _do_ss_request(doi, api_key=api_key)


def _do_ss_request(doi: str, api_key: str | None) -> list[str]:
    """Execute the SemanticScholar references HTTP request.

    Args:
        doi: Clean DOI string (no https://doi.org/ prefix).
        api_key: Optional SS API key.

    Returns:
        List of cited DOI strings (lowercase, stripped).

    Raises:
        requests.exceptions.RequestException: On HTTP errors.
    """
    url = SS_REFERENCES_URL.format(doi=urllib.parse.quote(doi, safe="/"))
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    params = {"fields": "externalIds", "limit": 500}

    resp = requests.get(url, headers=headers, params=params, timeout=15)

    if resp.status_code == 404:
        logger.debug(f"SS: paper not found for DOI {doi}")
        return []

    resp.raise_for_status()
    data = resp.json().get("data") or []

    result = []
    for item in data:
        cited_ids = item.get("citedPaper", {}).get("externalIds") or {}
        cited_doi = cited_ids.get("DOI")
        if cited_doi:
            result.append(cited_doi.strip())

    return result


# ---------------------------------------------------------------------------
# SemanticScholar batch lookup (one request for SS_BATCH_SIZE papers)
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception(_is_retryable_ss_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # SS: 1 req/sec, with or without a key
def _post_ss_batch(ids: list[str], fields: str, api_key: str | None) -> list:
    """POST one chunk of paper ids to the SemanticScholar batch endpoint."""
    headers = {"x-api-key": api_key} if api_key else {}
    resp = requests.post(
        SS_BATCH_URL,
        params={"fields": fields},
        json={"ids": ids},
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _pause(seconds: float, should_stop: StopFn = None) -> None:
    """Sleep for *seconds*, waking up early when a stop is requested."""
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if _stop_requested(should_stop):
            return
        time.sleep(min(remaining, 1.0))


def _ss_batch_lookup(
    dois: list[str],
    link_field: str,
    api_key: str | None = None,
    should_stop: StopFn = None,
) -> dict[str, list[str]]:
    """Fetch linked DOIs for many papers with the SemanticScholar batch endpoint.

    A chunk that fails (usually on 429) is retried once, after the other
    chunks and a pause, since one batch request replaces SS_BATCH_SIZE
    one-by-one requests.

    Args:
        dois: Clean DOI strings.
        link_field: ``"references"`` (cited papers) or ``"citations"`` (citers).
        api_key: Optional SemanticScholar API key.
        should_stop: Optional callable checked between chunks.

    Returns:
        Dict mapping each DOI SemanticScholar answered for to its linked DOIs.
        DOIs from a chunk that failed twice, or whose list came back cut
        (shorter than the paper's citation/reference count), are absent, so
        the caller can retry them one by one.
    """
    linked_key = "citedPaper" if link_field == "references" else "citingPaper"
    count_field = "referenceCount" if link_field == "references" else "citationCount"
    incomplete = 0
    answered: dict[str, list[str]] = {}
    chunks = [dois[i : i + SS_BATCH_SIZE] for i in range(0, len(dois), SS_BATCH_SIZE)]

    def post_chunk(chunk_index: int, chunk: list[str], last_try: bool) -> bool:
        nonlocal incomplete
        try:
            papers = _post_ss_batch(
                [f"DOI:{doi}" for doi in chunk],
                f"{link_field}.externalIds,{count_field}",
                api_key,
            )
        except (requests.exceptions.RequestException, OSError, ValueError) as e:
            outcome = (
                "its papers will be fetched one by one"
                if last_try
                else "it will be retried after the other batches"
            )
            logger.warning(
                f"SS batch {chunk_index}/{len(chunks)} failed ({e}); {outcome}"
            )
            return False
        for doi, paper in zip(chunk, papers, strict=False):
            links = (paper or {}).get(link_field) or []
            expected = min((paper or {}).get(count_field) or 0, SS_BATCH_LINK_CAP)
            if len(links) < expected * SS_BATCH_MIN_COMPLETENESS:
                incomplete += 1
                continue
            answered[doi] = [
                linked_doi.strip()
                for item in links
                if (
                    linked_doi := (
                        (item.get(linked_key, item) or {}).get("externalIds") or {}
                    ).get("DOI")
                )
            ]
        logger.info(f"  SS batch {chunk_index}/{len(chunks)} done")
        return True

    failed: list[tuple[int, list[str]]] = []
    for chunk_index, chunk in enumerate(chunks, 1):
        if _stop_requested(should_stop):
            return answered
        if not post_chunk(chunk_index, chunk, last_try=False):
            failed.append((chunk_index, chunk))
    if failed:
        logger.info(
            f"  Retrying {len(failed)} failed SS batch(es) in {SS_BATCH_RETRY_PAUSE} s"
        )
        _pause(SS_BATCH_RETRY_PAUSE, should_stop)
        for chunk_index, chunk in failed:
            if _stop_requested(should_stop):
                return answered
            post_chunk(chunk_index, chunk, last_try=True)
    if incomplete:
        logger.info(
            f"  SS batch: {incomplete} paper(s) with a cut {link_field} list "
            "will be fetched one by one"
        )
    return answered


class _SSSingleBreaker:
    """Stop one-by-one SemanticScholar requests once SS keeps throttling.

    Each failed request already costs about 30 s of retries; after
    SS_SINGLE_FAILURE_LIMIT consecutive transient failures (429, 5xx,
    timeouts) the remaining papers go straight to the fallback sources.
    """

    def __init__(self, fetch: Callable[..., list[str]], api_key: str | None):
        self._fetch = fetch
        self._api_key = api_key
        self._failures = 0

    @property
    def is_open(self) -> bool:
        return self._failures >= SS_SINGLE_FAILURE_LIMIT

    def fetch(self, doi: str) -> list[str]:
        """Return SS links for *doi*, or [] without a request once open."""
        if self.is_open:
            return []
        errors: list[BaseException] = []
        links = self._fetch(doi, api_key=self._api_key, on_failure=errors.append)
        if errors and _is_retryable_ss_error(errors[0]):
            self._failures += 1
            if self.is_open:
                logger.warning(
                    f"SemanticScholar failed {self._failures} times in a row; "
                    "the remaining papers skip it and use the fallback sources"
                )
        else:
            self._failures = 0
        return links


def _clean(doi: str) -> str:
    return doi.replace("https://doi.org/", "").strip()


def fetch_references_ss(
    doi: str,
    api_key: str | None = None,
    on_failure: Callable[[BaseException], None] | None = None,
) -> list[str]:
    """Return list of DOIs cited by *doi* via SemanticScholar.

    Args:
        doi: DOI string (with or without https://doi.org/ prefix).
        api_key: Optional SemanticScholar API key for higher rate limits.
        on_failure: Optional callable receiving the exception when the
            request fails (as opposed to a paper with no references).

    Returns:
        List of cited DOI strings, or empty list if not found / error.
    """
    clean_doi = doi.replace("https://doi.org/", "").strip()
    try:
        if api_key:
            return _fetch_ss_with_key(clean_doi, api_key) or []
        else:
            return _fetch_ss_no_key(clean_doi) or []
    except (requests.exceptions.RequestException, OSError) as e:
        logger.warning(f"SS fetch failed for DOI {clean_doi}: {e}")
        if on_failure is not None:
            on_failure(e)
        return []


def _fetch_references_oc(doi: str) -> list[str]:
    """Return cited DOI list from OpenCitations for a single DOI.

    Args:
        doi: Clean DOI string.

    Returns:
        List of cited DOI strings.
    """
    success, response, _ = getReferences(doi)
    if not success or response is None:
        return []
    try:
        data = response.json()
        return [
            item["cited"].replace("https://doi.org/", "").strip()
            for item in data
            if item.get("cited")
        ]
    except (ValueError, KeyError) as e:
        logger.warning(f"OC parse error for DOI {doi}: {e}")
        return []


def _is_retryable_crossref_error(exc: BaseException) -> bool:
    """Return True only for transient CrossRef errors worth retrying.

    Retries on 429 (rate-limited) and 5xx (server errors).
    Does NOT retry on 4xx client errors (e.g. 404) — those won't improve.
    """
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status == 429 or (status is not None and status >= 500)
    return isinstance(exc, requests.exceptions.Timeout)


@retry(
    retry=retry_if_exception(_is_retryable_crossref_error),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # Conservative: 1 req/sec avoids server-side throttling
def _fetch_references_crossref(doi: str, mailto: str | None = None) -> list[str]:
    """Fetch reference DOIs from CrossRef /works/{doi} endpoint.

    Args:
        doi: Clean DOI string (no https://doi.org/ prefix).
        mailto: Optional email address for CrossRef polite pool.

    Returns:
        List of cited DOI strings, or empty list if not found / no refs.
    """
    url = CROSSREF_WORKS_URL.format(doi=urllib.parse.quote(doi, safe="/"))
    params: dict[str, str] = {}
    if mailto:
        params["mailto"] = mailto
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code in (400, 404):
        logger.debug(f"CrossRef: no record for DOI {doi} (HTTP {resp.status_code})")
        return []
    resp.raise_for_status()
    refs = resp.json().get("message", {}).get("reference", [])
    return [r["DOI"].strip() for r in refs if r.get("DOI")]


def fetch_references_batch(
    dois: list[str],
    api_key: str | None = None,
    cache_path: str | None = None,
    fallback_opencitations: bool = True,
    mailto: str | None = None,
    should_stop: StopFn = None,
    on_progress: ProgressFn = None,
    use_semantic_scholar: bool = True,
    use_crossref: bool = True,
) -> dict[str, list[str]]:
    """Fetch reference DOI lists for many papers with cache and three-tier fallback.

    Fallback chain per paper:
      1. SemanticScholar (primary, fast, rich).
      2. CrossRef /works/{doi} (middle tier, free, no key needed).
      3. OpenCitations (last resort, 3 req/sec shared).

    Results are cached to a JSON file for resumability across interrupted runs.

    Args:
        dois: List of DOI strings to look up.
        api_key: Optional SemanticScholar API key.
        cache_path: Path to JSON cache file. Pass None to skip caching.
        fallback_opencitations: If True, use OpenCitations when CrossRef also
            returns an empty list.
        mailto: Optional email for CrossRef polite pool (higher rate limits).
        should_stop: Optional callable checked before each paper and between
            fallback tiers; when it returns True, fetching stops and the papers
            done so far are cached. Unfetched DOIs are absent from the result.
        on_progress: Optional callable receiving (papers done, papers to fetch).
        use_semantic_scholar: False skips tier 1 (e.g. OpenCitations or
            CrossRef chosen as the source).
        use_crossref: False skips tier 2.

    Returns:
        Dict mapping each fetched or cached DOI to its list of cited DOIs.
    """
    # Load existing cache
    cache: dict[str, list[str]] = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached entries from {cache_path}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load cache {cache_path}: {e}")

    results: dict[str, list[str]] = {}
    pending = [d for d in dois if d not in cache]

    logger.info(
        f"Fetching references: {len(dois)} DOIs total, "
        f"{len(cache)} cached, {len(pending)} to fetch"
    )
    ss_answers = (
        _ss_batch_lookup(
            [d for d in dict.fromkeys(_clean(d) for d in pending) if d],
            "references",
            api_key=api_key,
            should_stop=should_stop,
        )
        if use_semantic_scholar
        else {}
    )
    ss_single = _SSSingleBreaker(fetch_references_ss, api_key)

    for i, doi in enumerate(pending, 1):
        if _stop_requested(should_stop):
            break
        clean_doi = doi.replace("https://doi.org/", "").strip()
        if not clean_doi:
            results[doi] = []
            continue

        # Tier 1: SemanticScholar (batch answer, else one request)
        if not use_semantic_scholar:
            refs = []
        elif clean_doi in ss_answers:
            refs = ss_answers[clean_doi]
        else:
            refs = ss_single.fetch(clean_doi)
        if not refs and _stop_requested(should_stop):
            break

        # Tier 2: CrossRef (when SS returned nothing)
        if not refs and use_crossref:
            logger.debug(f"SS empty for {clean_doi}, trying CrossRef...")
            try:
                refs = _fetch_references_crossref(clean_doi, mailto=mailto) or []
                if refs:
                    logger.debug(f"CrossRef found {len(refs)} refs for {clean_doi}")
            except Exception as e:
                logger.warning(f"CrossRef fetch failed for DOI {clean_doi}: {e}")
                refs = []
            if not refs and _stop_requested(should_stop):
                break

        # Tier 3: OpenCitations (when CrossRef also returned nothing)
        if not refs and fallback_opencitations:
            logger.debug(f"CrossRef empty for {clean_doi}, trying OpenCitations...")
            refs = _fetch_references_oc(clean_doi)
            if refs:
                logger.debug(f"OC found {len(refs)} refs for {clean_doi}")

        results[doi] = refs

        # Persist cache incrementally
        if cache_path and i % 10 == 0:
            _save_cache(cache_path, {**cache, **results})

        if i % PROGRESS_LOG_EVERY == 0 or i == len(pending):
            logger.info(f"  Progress: {i}/{len(pending)} fetched")
        if on_progress is not None:
            on_progress(i, len(pending))

    return _finish_batch(dois, cache, results, cache_path)


def _finish_batch(
    dois: list[str],
    cache: dict[str, list[str]],
    results: dict[str, list[str]],
    cache_path: str | None,
) -> dict[str, list[str]]:
    """Merge new results into the cache, save it and return the requested DOIs.

    DOIs neither cached nor fetched (fetch stopped early) are left out, so the
    caller can tell them apart from papers with no known links.
    """
    combined = {**cache, **results}
    if cache_path:
        _save_cache(cache_path, combined)
    return {doi: combined[doi] for doi in dois if doi in combined}


def _save_cache(cache_path: str, data: dict[str, list[str]]) -> None:
    """Write cache dict to JSON file, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Incoming citers — who cites each paper (SS primary, OC fallback)
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception(_is_retryable_ss_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # SS public: 1 req/sec
def _fetch_ss_citers_no_key(doi: str) -> list[str]:
    """Fetch citing-paper DOIs from SemanticScholar without an API key."""
    return _do_ss_citers_request(doi, api_key=None)


@retry(
    retry=retry_if_exception(_is_retryable_ss_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
@sleep_and_retry
@limits(calls=1, period=1)  # SS keys default to 1 req/sec
def _fetch_ss_citers_with_key(doi: str, api_key: str) -> list[str]:
    """Fetch citing-paper DOIs from SemanticScholar with an API key."""
    return _do_ss_citers_request(doi, api_key=api_key)


def _do_ss_citers_request(doi: str, api_key: str | None) -> list[str]:
    """Execute the SemanticScholar incoming-citations HTTP request.

    Args:
        doi: Clean DOI string (no https://doi.org/ prefix).
        api_key: Optional SS API key.

    Returns:
        List of citing DOI strings (stripped).

    Raises:
        requests.exceptions.RequestException: On HTTP errors.
    """
    url = SS_CITATIONS_URL.format(doi=urllib.parse.quote(doi, safe="/"))
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    params = {"fields": "externalIds", "limit": 500}

    resp = requests.get(url, headers=headers, params=params, timeout=15)

    if resp.status_code == 404:
        logger.debug(f"SS: paper not found for DOI {doi}")
        return []

    resp.raise_for_status()
    data = resp.json().get("data") or []

    result = []
    for item in data:
        citing_ids = item.get("citingPaper", {}).get("externalIds") or {}
        citing_doi = citing_ids.get("DOI")
        if citing_doi:
            result.append(citing_doi.strip())

    return result


def fetch_citers_ss(
    doi: str,
    api_key: str | None = None,
    on_failure: Callable[[BaseException], None] | None = None,
) -> list[str]:
    """Return list of DOIs that cite *doi* via SemanticScholar.

    Args:
        doi: DOI string (with or without https://doi.org/ prefix).
        api_key: Optional SemanticScholar API key for higher rate limits.
        on_failure: Optional callable receiving the exception when the
            request fails (as opposed to a paper with no citers).

    Returns:
        List of citing DOI strings, or empty list if not found / error.
    """
    clean_doi = doi.replace("https://doi.org/", "").strip()
    try:
        if api_key:
            return _fetch_ss_citers_with_key(clean_doi, api_key) or []
        else:
            return _fetch_ss_citers_no_key(clean_doi) or []
    except Exception as e:
        logger.warning(f"SS citers fetch failed for DOI {clean_doi}: {e}")
        if on_failure is not None:
            on_failure(e)
        return []


def _fetch_citers_oc(doi: str) -> list[str]:
    """Return list of DOIs citing *doi* from OpenCitations.

    Args:
        doi: Clean DOI string.

    Returns:
        List of citing DOI strings.
    """
    success, response, _ = getCitations(doi)
    if not success or response is None:
        return []
    try:
        data = response.json()
        return [
            item["citing"].replace("https://doi.org/", "").strip()
            for item in data
            if item.get("citing")
        ]
    except (ValueError, KeyError) as e:
        logger.warning(f"OC citers parse error for DOI {doi}: {e}")
        return []


def fetch_citers_batch(
    dois: list[str],
    api_key: str | None = None,
    cache_path: str | None = None,
    fallback_opencitations: bool = True,
    should_stop: StopFn = None,
    on_progress: ProgressFn = None,
    use_semantic_scholar: bool = True,
) -> dict[str, list[str]]:
    """Fetch citing-paper DOI lists for many papers with cache and fallback.

    Fallback chain per paper:
      1. SemanticScholar /citations (primary, fast, rich).
      2. OpenCitations /citations/{doi} (fallback; CrossRef has no free
         citedBy endpoint).

    Results are cached to a JSON file for resumability.

    Args:
        dois: List of DOI strings to look up.
        api_key: Optional SemanticScholar API key.
        cache_path: Path to JSON cache file. Pass None to skip caching.
        fallback_opencitations: If True, use OpenCitations when SS returns
            an empty list.
        should_stop: Optional callable checked before each paper and between
            fallback tiers; when it returns True, fetching stops and the papers
            done so far are cached. Unfetched DOIs are absent from the result.
        on_progress: Optional callable receiving (papers done, papers to fetch).

    Returns:
        Dict mapping each fetched or cached DOI to its list of citing DOIs.
    """
    cache: dict[str, list[str]] = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached citer entries from {cache_path}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load citers cache {cache_path}: {e}")

    results: dict[str, list[str]] = {}
    pending = [d for d in dois if d not in cache]

    logger.info(
        f"Fetching citers: {len(dois)} DOIs total, "
        f"{len(cache)} cached, {len(pending)} to fetch"
    )
    ss_answers = (
        _ss_batch_lookup(
            [d for d in dict.fromkeys(_clean(d) for d in pending) if d],
            "citations",
            api_key=api_key,
            should_stop=should_stop,
        )
        if use_semantic_scholar
        else {}
    )
    ss_single = _SSSingleBreaker(fetch_citers_ss, api_key)

    for i, doi in enumerate(pending, 1):
        if _stop_requested(should_stop):
            break
        clean_doi = doi.replace("https://doi.org/", "").strip()
        if not clean_doi:
            results[doi] = []
            continue

        # Tier 1: SemanticScholar (batch answer, else one request)
        if not use_semantic_scholar:
            citers = []
        elif clean_doi in ss_answers:
            citers = ss_answers[clean_doi]
        else:
            citers = ss_single.fetch(clean_doi)
        if not citers and _stop_requested(should_stop):
            break

        # Tier 2: OpenCitations
        if not citers and fallback_opencitations:
            logger.debug(f"SS empty for {clean_doi}, trying OpenCitations...")
            citers = _fetch_citers_oc(clean_doi)
            if citers:
                logger.debug(f"OC found {len(citers)} citers for {clean_doi}")

        results[doi] = citers

        if cache_path and i % 10 == 0:
            _save_cache(cache_path, {**cache, **results})

        if i % PROGRESS_LOG_EVERY == 0 or i == len(pending):
            logger.info(f"  Progress: {i}/{len(pending)} fetched")
        if on_progress is not None:
            on_progress(i, len(pending))

    return _finish_batch(dois, cache, results, cache_path)
