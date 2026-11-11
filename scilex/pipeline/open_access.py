"""Open-access status enrichment through Unpaywall (issue #44).

Adds an ``oa_type`` column with one of gold, green, bronze, hybrid, closed
(or ``MISSING_VALUE`` when unknown). It does not influence the relevance score.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from scilex.constants import MISSING_VALUE, normalize_doi

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
REQUEST_TIMEOUT_SECONDS = 20
VALID_OA_TYPES = {"gold", "green", "bronze", "hybrid", "closed"}
# Unpaywall allows 100k calls/day; stay well below 10 requests per second.
MIN_SECONDS_BETWEEN_REQUESTS = 0.1


def parse_oa_type(payload):
    """Map an Unpaywall response to an ``oa_type`` value."""
    status = str((payload or {}).get("oa_status", "")).lower()
    return status if status in VALID_OA_TYPES else MISSING_VALUE


def fetch_oa_type(doi, email, session=None):
    """Query Unpaywall for one DOI; return its ``oa_type`` or ``MISSING_VALUE``."""
    http = session or requests
    try:
        response = http.get(
            UNPAYWALL_URL.format(doi=doi),
            params={"email": email},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return MISSING_VALUE
        response.raise_for_status()
        return parse_oa_type(response.json())
    except (requests.RequestException, ValueError) as error:
        logging.debug(f"Unpaywall lookup failed for {doi}: {error}")
        return MISSING_VALUE


def enrich_with_unpaywall(df, email, num_workers=4, fetch=fetch_oa_type):
    """Add the ``oa_type`` column (no-op without ``email``).

    Args:
        df: DataFrame with a ``DOI`` column.
        email: Contact email required by Unpaywall; falsy disables enrichment.
        num_workers: Parallel requests.
        fetch: Injectable ``(doi, email) -> oa_type`` function (tests).

    Returns:
        pd.DataFrame: copy of ``df`` with ``oa_type``.
    """
    if not email:
        logging.warning("Unpaywall enrichment skipped: no email configured")
        return df
    df = df.copy()
    dois = df["DOI"].map(normalize_doi)
    unique_dois = sorted({doi for doi in dois if doi})

    def throttled_fetch(doi):
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)
        return doi, fetch(doi, email)

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        oa_by_doi = dict(executor.map(throttled_fetch, unique_dois))

    df["oa_type"] = [
        oa_by_doi.get(doi, MISSING_VALUE) if doi else MISSING_VALUE for doi in dois
    ]
    known = int((df["oa_type"] != MISSING_VALUE).sum())
    logging.info(f"Unpaywall: oa_type resolved for {known:,}/{len(df):,} papers")
    return df
