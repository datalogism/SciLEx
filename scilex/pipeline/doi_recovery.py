"""Recover missing DOIs through the CrossRef bibliographic search (issue #36).

For every paper without a DOI, CrossRef is queried with the title and the first
author. A candidate is accepted only when its title is at least
``min_similarity`` similar to ours and, when both years are known, the years
differ by at most one (preprint vs. published version).
"""

import json
import logging
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

import requests

from scilex.config_defaults import DEFAULT_DOI_RECOVERY_MIN_SIMILARITY
from scilex.constants import extract_year, is_missing, is_valid, normalize_doi

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
REQUEST_TIMEOUT_SECONDS = 20
CACHE_FILENAME = "doi_recovery_cache.json"
MAX_YEAR_GAP = 1


def normalize_title(title):
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", str(title))
    ascii_text = decomposed.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text.lower())).strip()


def title_similarity(title_a, title_b):
    """Similarity ratio (0-1) between two normalized titles."""
    return SequenceMatcher(
        None, normalize_title(title_a), normalize_title(title_b)
    ).ratio()


def first_author_family_name(authors):
    """Best-effort family name of the first author of a ``;``-joined list."""
    if is_missing(authors):
        return None
    first = str(authors).split(";")[0].strip()
    if not first:
        return None
    if "," in first:
        return first.split(",")[0].strip()
    return first.split()[-1]


def _crossref_item_year(item):
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def select_best_candidate(items, title, year, min_similarity):
    """Return the DOI of the best CrossRef candidate passing validation, else None.

    Args:
        items: ``message.items`` from the CrossRef ``/works`` response.
        title: Our paper title.
        year: Our publication year (int or None).
        min_similarity: Minimum title similarity (0-1).
    """
    best_doi, best_score = None, 0.0
    for item in items:
        candidate_titles = item.get("title") or []
        if not candidate_titles or not item.get("DOI"):
            continue
        score = title_similarity(title, candidate_titles[0])
        candidate_year = _crossref_item_year(item)
        if (
            year is not None
            and candidate_year is not None
            and abs(year - candidate_year) > MAX_YEAR_GAP
        ):
            continue
        if score >= min_similarity and score > best_score:
            best_doi, best_score = normalize_doi(item["DOI"]), score
    return best_doi


def lookup_doi(
    title,
    first_author,
    year=None,
    min_similarity=DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
    mailto=None,
    session=None,
):
    """Query CrossRef for one paper and return a validated DOI or None.

    Network or HTTP failures are logged and yield None (the paper simply stays
    without DOI).
    """
    params = {"query.bibliographic": title, "rows": 3}
    if first_author:
        params["query.author"] = first_author
    if mailto:
        params["mailto"] = mailto
    http = session or requests
    try:
        response = http.get(
            CROSSREF_WORKS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
    except (requests.RequestException, ValueError) as error:
        logging.debug(f"CrossRef DOI lookup failed for '{title[:60]}': {error}")
        return None
    return select_best_candidate(items, title, year, min_similarity)


def _load_cache(cache_path):
    if not cache_path or not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_cache(cache_path, cache):
    if not cache_path:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
    except OSError as error:
        logging.warning(f"Could not write DOI recovery cache: {error}")


def recover_missing_dois(
    df,
    min_similarity=DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
    mailto=None,
    cache_path=None,
    num_workers=4,
    lookup=lookup_doi,
):
    """Fill missing DOIs of ``df`` via CrossRef and drop resulting duplicates.

    A recovered DOI that already belongs to another row means the paper was a
    duplicate that deduplication could not see: the recovered (DOI-less) row is
    dropped and the original is kept.

    Args:
        df: DataFrame with ``title``, ``authors``, ``date`` and ``DOI`` columns.
        min_similarity: Minimum title similarity to accept a candidate.
        mailto: Email for the CrossRef polite pool.
        cache_path: JSON cache file (title key -> DOI or null), or None.
        num_workers: Parallel lookups.
        lookup: Injectable lookup function (tests).

    Returns:
        tuple: ``(DataFrame, stats)`` with stats keys ``candidates``, ``recovered``,
        ``duplicates_removed``, ``cache_hits``.
    """
    stats = {"candidates": 0, "recovered": 0, "duplicates_removed": 0, "cache_hits": 0}
    if "DOI" not in df.columns or "title" not in df.columns:
        return df, stats

    df = df.copy()
    missing_positions = [
        position
        for position, doi in enumerate(df["DOI"])
        if normalize_doi(doi) is None and is_valid(df["title"].iloc[position])
    ]
    stats["candidates"] = len(missing_positions)
    if not missing_positions:
        return df, stats

    cache = _load_cache(cache_path)

    def resolve(position):
        row = df.iloc[position]
        title = str(row["title"])
        cache_key = normalize_title(title)
        if cache_key in cache:
            return position, cache[cache_key], True
        doi = lookup(
            title,
            first_author_family_name(row.get("authors")),
            extract_year(row.get("date")),
            min_similarity,
            mailto,
        )
        return position, doi, False

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(resolve, missing_positions))

    existing_dois = {normalize_doi(doi) for doi in df["DOI"]} - {None}
    drop_positions = []
    doi_column = df.columns.get_loc("DOI")
    for position, doi, from_cache in results:
        cache[normalize_title(df["title"].iloc[position])] = doi
        stats["cache_hits"] += int(from_cache)
        if not doi:
            continue
        if doi in existing_dois:
            drop_positions.append(position)
            continue
        df.iloc[position, doi_column] = doi
        existing_dois.add(doi)
        stats["recovered"] += 1

    _save_cache(cache_path, cache)
    if drop_positions:
        df = df.drop(df.index[drop_positions]).reset_index(drop=True)
        stats["duplicates_removed"] = len(drop_positions)

    logging.info(
        f"DOI recovery: {stats['recovered']}/{stats['candidates']} DOIs recovered, "
        f"{stats['duplicates_removed']} duplicates removed, "
        f"{stats['cache_hits']} cache hits"
    )
    return df, stats
