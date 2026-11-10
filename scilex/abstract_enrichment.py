"""
Abstract enrichment for API results that omit abstract text.

Some APIs (Elsevier Scopus search, ORKG) return metadata without abstracts.
This module scans collection files, identifies such records, fetches abstracts
from Semantic Scholar (primary) and OpenAlex (fallback) using DOIs, then
writes the abstracts back into the source JSON files so future aggregations
find them without re-fetching.

Cache: DOI → abstract text is persisted in an SQLite database
(abstract_cache.db).  A one-time migration from the old abstract_cache.json
is performed automatically on first run.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

import requests
from tqdm import tqdm

from scilex.constants import QUERY_MARKER_FILES, normalize_doi

# ---------------------------------------------------------------------------
# Persistent DOI → abstract cache  (SQLite backend)
# ---------------------------------------------------------------------------

_DB_FILENAME = "abstract_cache.db"
_LEGACY_JSON_FILENAME = "abstract_cache.json"
_cache_lock = threading.Lock()


def _resolve_dir(dir_collect: str) -> Path:
    """
    Return a usable Path for dir_collect, handling Windows-style paths on Linux.

    When the aggregate script is run on WSL but config_used.yml was written on
    Windows, output_dir is 'C:\\Users\\...'.  On Linux, Path('C:\\...') is
    treated as a relative path (backslash is not a separator), so any file
    written there is silently dropped into a weird relative location.

    This function detects that pattern and converts the Windows path to its
    WSL mount-point equivalent (/mnt/c/...).  On Windows, the path is used
    unchanged.
    """
    p = Path(dir_collect)
    if p.is_absolute():
        return p

    raw = str(dir_collect)
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in ("/", "\\") and os.name != "nt":
        drive = raw[0].lower()
        rest = raw[3:].replace("\\", "/")
        converted = Path(f"/mnt/{drive}/{rest}")
        logging.debug(f"Abstract cache: converted Windows path → {converted}")
        return converted

    return p


def _db_path(dir_collect: str) -> Path:
    return _resolve_dir(dir_collect) / _DB_FILENAME


@contextmanager
def _open_db(dir_collect: str):
    """Open (and initialise if new) the SQLite abstract cache."""
    conn = sqlite3.connect(str(_db_path(dir_collect)), check_same_thread=False)
    # WAL mode: concurrent readers don't block writers
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS abstract_cache (
            doi      TEXT PRIMARY KEY,
            abstract TEXT   -- NULL = previously attempted, not found
        )
    """)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def _migrate_json_to_sqlite(dir_collect: str) -> int:
    """
    One-time migration: import abstract_cache.json into abstract_cache.db.

    The old JSON file is renamed to abstract_cache.json.migrated after a
    successful migration so the step is never repeated.
    """
    json_path = _resolve_dir(dir_collect) / _LEGACY_JSON_FILENAME
    if not json_path.exists():
        return 0

    logging.info(f"Abstract cache: migrating {json_path} → SQLite …")
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.warning(f"Abstract cache: could not read JSON for migration: {e}")
        return 0

    if not data:
        json_path.rename(json_path.with_suffix(".json.migrated"))
        return 0

    with _open_db(dir_collect) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO abstract_cache (doi, abstract) VALUES (?, ?)",
            data.items(),
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM abstract_cache").fetchone()[0]

    json_path.rename(json_path.with_suffix(".json.migrated"))
    logging.info(
        f"Abstract cache: migrated {count:,} entries; old file renamed to .json.migrated"
    )
    return count


def _query_cache(dir_collect: str, dois: list[str]) -> dict[str, str | None]:
    """
    Return cache entries only for the requested DOIs.

    Absent DOIs are not included in the result (caller treats absence as
    "never attempted").  DOIs mapped to None were attempted but not found.
    """
    if not dois:
        return {}
    # SQLite caps bind variables at 999; chunk to stay under that limit.
    _CHUNK = 900
    result: dict[str, str | None] = {}
    with _open_db(dir_collect) as conn:
        for i in range(0, len(dois), _CHUNK):
            chunk = dois[i : i + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT doi, abstract FROM abstract_cache WHERE doi IN ({placeholders})",
                chunk,
            ).fetchall()
            result.update(rows)
    return result


def _save_cache_entries(dir_collect: str, entries: dict[str, str | None]) -> None:
    """Incrementally persist new cache entries (INSERT OR REPLACE, no full rewrite)."""
    if not entries:
        return
    with _open_db(dir_collect) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO abstract_cache (doi, abstract) VALUES (?, ?)",
            entries.items(),
        )
        conn.commit()


def load_all_cached_abstracts(dir_collect: str) -> dict[str, str]:
    """Return all non-None DOI → abstract entries from the SQLite cache.

    Used by the aggregation pipeline to inject cached abstracts into records
    during batch processing, without rescanning source JSON files.
    """
    _migrate_json_to_sqlite(dir_collect)
    with _open_db(dir_collect) as conn:
        rows = conn.execute(
            "SELECT doi, abstract FROM abstract_cache WHERE abstract IS NOT NULL"
        ).fetchall()
    return dict(rows)


# APIs whose search results are known to omit abstract text
ABSTRACT_ABSENT_APIS = {"Elsevier", "ORKG"}

# Sentinel values that indicate a missing abstract
_MISSING_MARKERS = {None, "", "NA", "N/A", "MISSING"}


def _is_abstract_missing(value) -> bool:
    return value is None or str(value).strip() in _MISSING_MARKERS


def _extract_doi(record: dict, api_name: str) -> str | None:
    """Extract raw DOI string from an API-format record."""
    if api_name == "Elsevier":
        doi = record.get("prism:doi")
    elif api_name == "ORKG":
        try:
            doi_list = record["identifiers"]["doi"]
            doi = doi_list[0] if doi_list else None
        except (KeyError, TypeError, IndexError):
            doi = None
    else:
        doi = record.get("doi") or record.get("DOI") or record.get("prism:doi")

    return normalize_doi(doi)


def _abstract_field(api_name: str) -> str:
    """Return the field name where abstracts are stored for a given API."""
    return "dc:description" if api_name == "Elsevier" else "abstract"


def _extract_year(record: dict, api_name: str) -> int | None:
    """Extract publication year from a raw API record, mirroring the same
    fields the Zotero format converters read (prism:coverDate / published_year).

    Returns None when the year is missing or unparseable — callers must treat
    that as "keep" (conservative), same convention as the aggregation pipeline's
    own year pre-filter.
    """
    try:
        if api_name == "Elsevier":
            cover_date = record.get("prism:coverDate")
            if cover_date:
                return int(str(cover_date)[:4])
        elif api_name == "ORKG":
            year = record.get("publication_info", {}).get("published_year")
            if year is not None:
                return int(year)
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _fetch_ss(doi: str, session: requests.Session, api_key: str | None) -> str | None:
    """Fetch abstract from Semantic Scholar."""
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        resp = session.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "abstract"},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("abstract") or None
        if resp.status_code == 429:
            logging.debug(f"SS rate-limited for DOI {doi}")
    except Exception as e:
        logging.debug(f"SS fetch error for {doi}: {e}")
    return None


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    """Reconstruct plain text from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    max_pos = max(pos for positions in inverted_index.values() for pos in positions) + 1
    words = [""] * max_pos
    for word, positions in inverted_index.items():
        for pos in positions:
            if pos < max_pos:
                words[pos] = word
    return " ".join(w for w in words if w)


def _fetch_openalex(doi: str, session: requests.Session) -> str | None:
    """Fetch abstract from OpenAlex (fallback)."""
    try:
        resp = session.get(
            f"https://api.openalex.org/works/doi:{doi}",
            params={"select": "abstract_inverted_index"},
            timeout=10,
        )
        if resp.status_code == 200:
            inv = resp.json().get("abstract_inverted_index")
            if inv:
                return _reconstruct_openalex_abstract(inv) or None
    except Exception as e:
        logging.debug(f"OpenAlex fetch error for {doi}: {e}")
    return None


def fetch_abstract_for_doi(
    doi: str,
    session: requests.Session,
    ss_api_key: str | None = None,
    inter_request_delay: float = 0.1,
) -> str | None:
    """Try Semantic Scholar then OpenAlex."""
    abstract = _fetch_ss(doi, session, ss_api_key)
    if abstract:
        return abstract
    time.sleep(inter_request_delay)
    return _fetch_openalex(doi, session)


# ---------------------------------------------------------------------------
# Collection scanning  (single-pass: collect + apply cached abstracts together)
# ---------------------------------------------------------------------------


def _iter_page_files(dir_collect: str):
    """Yield (file_path, api_name) for every page file in the collection."""
    dir_collect = str(_resolve_dir(dir_collect))
    for api_name in os.listdir(dir_collect):
        api_path = os.path.join(dir_collect, api_name)
        if not os.path.isdir(api_path):
            continue
        for query_idx in os.listdir(api_path):
            query_path = os.path.join(api_path, query_idx)
            if not os.path.isdir(query_path):
                continue
            try:
                int(query_idx)
            except ValueError:
                continue
            for filename in os.listdir(query_path):
                if filename in QUERY_MARKER_FILES:
                    continue
                fp = os.path.join(query_path, filename)
                if os.path.isfile(fp):
                    yield fp, api_name


def _single_pass_scan(
    dir_collect: str,
    year_range: set[int] | None = None,
) -> tuple[list[str], dict[str, tuple[list, str, str]]]:
    """
    Read every ABSTRACT_ABSENT_APIS page file exactly once.

    Args:
        year_range: If given, records whose extracted year is known and falls
                    outside this set are skipped entirely — they'll be dropped
                    by the aggregation pipeline's own year filter anyway, so
                    fetching their abstract is wasted work. Records with an
                    unknown/unparseable year are kept (same conservative
                    convention as the aggregation pre-filter).

    Returns:
        all_dois      : deduplicated list of DOIs that are missing abstracts
        file_map      : doi → (results_list_ref, abs_field, file_path)
                        — the live Python list inside the parsed JSON dict,
                        so patching is done without re-reading the file.
        file_data_map : file_path → (data_dict, api_name, abs_field)
                        — holds parsed JSON so we can rewrite only changed files.
    """
    doi_to_indices: dict[
        str, list[tuple]
    ] = {}  # doi → [(list_ref, record_idx, abs_field)]
    file_data: dict[str, tuple] = {}  # file_path → (data, api_name, abs_field)
    skipped_out_of_range = 0

    for file_path, api_name in _iter_page_files(dir_collect):
        if api_name not in ABSTRACT_ABSENT_APIS:
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        abs_field = _abstract_field(api_name)
        results = data.get("results", [])
        file_needs_tracking = False

        for idx, record in enumerate(results):
            if not _is_abstract_missing(record.get(abs_field)):
                continue

            if year_range:
                year = _extract_year(record, api_name)
                if year is not None and year not in year_range:
                    skipped_out_of_range += 1
                    continue

            doi = _extract_doi(record, api_name)
            if not doi:
                continue
            doi_to_indices.setdefault(doi, []).append(
                (results, idx, abs_field, file_path)
            )
            file_needs_tracking = True

        if file_needs_tracking:
            file_data[file_path] = (data, api_name, abs_field)

    if skipped_out_of_range:
        logging.info(
            f"Abstract enrichment: skipped {skipped_out_of_range} records outside "
            f"configured year range (would be dropped by aggregation anyway)"
        )

    all_dois = list(doi_to_indices.keys())
    return all_dois, doi_to_indices, file_data


def _apply_abstracts_and_flush(
    doi_to_abstract: dict[str, str],
    doi_to_indices: dict[str, list[tuple]],
    file_data: dict[str, tuple],
) -> int:
    """
    Patch in-memory records and rewrite only modified files.

    Args:
        doi_to_abstract : doi → abstract text (already resolved from cache or fetch)
        doi_to_indices  : doi → [(results_list, record_idx, abs_field, file_path)]
        file_data       : file_path → (data_dict, api_name, abs_field)

    Returns:
        Number of individual records patched.
    """
    if not doi_to_abstract:
        return 0

    modified_files: set[str] = set()
    patched = 0

    for doi, abstract in doi_to_abstract.items():
        for results, idx, abs_field, file_path in doi_to_indices.get(doi, []):
            results[idx][abs_field] = abstract
            modified_files.add(file_path)
            patched += 1

    for file_path in modified_files:
        data, *_ = file_data[file_path]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logging.warning(f"Could not write patched file {file_path}: {e}")

    return patched


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def enrich_collection_abstracts(
    dir_collect: str,
    ss_api_key: str | None = None,
    num_workers: int = 4,
    inter_request_delay: float = 0.35,
    cache_only: bool = False,
    year_range: set[int] | None = None,
) -> dict:
    """
    Enrich missing abstracts in a collection directory.

    1. Migrates old abstract_cache.json → abstract_cache.db (once, on first run).
    2. Single-pass scan over ABSTRACT_ABSENT_APIS files — reads each file exactly
       once and keeps parsed data in memory.
    3. Batched SQLite lookup for all DOIs found in step 2.
    4. Patches records with cached abstracts and writes changed files.
    5. If cache_only=False: fetches remaining uncached DOIs (SS → OpenAlex) in
       parallel, saves new entries to SQLite, patches source files.
       If cache_only=True: steps 5-7 are skipped entirely (no network calls).

    Args:
        dir_collect: Path to the collection directory.
        ss_api_key: Optional Semantic Scholar API key (raises rate limit).
        num_workers: Concurrent fetch threads.
        inter_request_delay: Seconds between SS and OA calls for the same DOI.
        cache_only: If True, only apply already-cached abstracts — skip all
                    network fetching.  Useful for fast re-aggregations when
                    the cache is already warm.
        year_range: If given, records with a known year outside this set are
                    skipped before fetching — they'd be dropped by the
                    aggregation pipeline's own year filter anyway (matters most
                    for APIs like ORKG that don't support server-side year
                    filtering, so out-of-range records get collected regardless
                    of the configured `years` list).

    Returns:
        Stats dict: dois_found, enriched, failed, patched_records.
    """
    # Step 0: one-time migration from legacy JSON cache
    _migrate_json_to_sqlite(dir_collect)

    if cache_only:
        # Cache-only mode: abstracts are injected directly during batch processing
        # (see parallel_process_papers).  No file scan or network fetch needed.
        logging.info(
            "Abstract enrichment: cache-only mode — skipping file scan, "
            "cached abstracts will be injected during aggregation"
        )
        return {
            "dois_found": 0,
            "enriched": 0,
            "cache_hits": 0,
            "newly_fetched": 0,
            "failed": 0,
            "patched_records": 0,
        }

    logging.info("Abstract enrichment: scanning collection for missing abstracts…")

    # Single-pass: read every Elsevier/ORKG file once, keep data in memory
    all_dois, doi_to_indices, file_data = _single_pass_scan(
        dir_collect, year_range=year_range
    )

    if not all_dois:
        logging.info(
            "Abstract enrichment: nothing to enrich (all records have abstracts)."
        )
        return {"dois_found": 0, "enriched": 0, "failed": 0, "patched_records": 0}

    # Batched SQLite lookup — targeted query for only the DOIs we need
    cached = _query_cache(dir_collect, all_dois)
    cached_abstracts = {doi: abstract for doi, abstract in cached.items() if abstract}
    cache_hits = len(cached_abstracts)
    cache_misses = sum(1 for doi in cached if cached[doi] is None)
    dois_never_attempted = [doi for doi in all_dois if doi not in cached]

    logging.info(
        f"Abstract enrichment: {len(all_dois)} DOIs need abstracts — "
        f"{cache_hits} cached, {cache_misses} previously failed, "
        f"{len(dois_never_attempted)} to fetch"
    )

    # Patch records already in cache (in-memory; only modified files are rewritten)
    patched_from_cache = _apply_abstracts_and_flush(
        cached_abstracts, doi_to_indices, file_data
    )
    if patched_from_cache:
        logging.info(
            f"Abstract enrichment: patched {patched_from_cache} records from cache"
        )

    # Fetch DOIs that were never attempted (skip previously-failed ones)
    dois_to_fetch = [d for d in dois_never_attempted if d in doi_to_indices]
    failed = 0
    newly_fetched: dict[str, str] = {}

    if dois_to_fetch:
        session = requests.Session()
        session.headers["User-Agent"] = (
            "SciLEx/1.0 (abstract enrichment; mailto:contact@scil.ex)"
        )

        def _fetch(doi: str) -> tuple[str, str | None]:
            abstract = fetch_abstract_for_doi(
                doi,
                session,
                ss_api_key=ss_api_key,
                inter_request_delay=inter_request_delay,
            )
            return doi, abstract

        # Flush to SQLite every FLUSH_EVERY completions instead of waiting for the
        # whole batch — otherwise an interrupted run (Ctrl-C, crash, sleep) loses
        # every abstract fetched so far, since nothing was persisted yet.
        FLUSH_EVERY = 200
        new_entries: dict[str, str | None] = {}
        pending: dict[str, str | None] = {}
        n_ok_total = 0
        n_fail_total = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(_fetch, doi): doi for doi in dois_to_fetch}
            for future in tqdm(
                as_completed(futures),
                total=len(dois_to_fetch),
                desc="Fetching abstracts",
                unit="DOI",
            ):
                doi, abstract = future.result()
                new_entries[doi] = abstract
                pending[doi] = abstract
                if abstract:
                    newly_fetched[doi] = abstract
                else:
                    failed += 1

                if len(pending) >= FLUSH_EVERY:
                    _save_cache_entries(dir_collect, pending)
                    n_ok_total += sum(1 for v in pending.values() if v)
                    n_fail_total += sum(1 for v in pending.values() if not v)
                    pending = {}

        if pending:
            _save_cache_entries(dir_collect, pending)
            n_ok_total += sum(1 for v in pending.values() if v)
            n_fail_total += sum(1 for v in pending.values() if not v)

        logging.info(
            f"Abstract cache: saved {n_ok_total} new abstracts + {n_fail_total} failed DOIs to SQLite"
        )

    # Patch source files for newly fetched abstracts
    # Reuses in-memory file data from the scan — no second read of any file
    patched_new = _apply_abstracts_and_flush(newly_fetched, doi_to_indices, file_data)

    total_patched = patched_from_cache + patched_new
    enriched = cache_hits + len(newly_fetched)

    logging.info(
        f"Abstract enrichment: {enriched}/{len(all_dois)} abstracts available "
        f"({cache_hits} from cache, {len(newly_fetched)} newly fetched, "
        f"{failed + cache_misses} not found)"
    )
    logging.info(
        f"Abstract enrichment: patched {total_patched} records in collection files"
    )

    return {
        "dois_found": len(all_dois),
        "enriched": enriched,
        "cache_hits": cache_hits,
        "newly_fetched": len(newly_fetched),
        "failed": failed,
        "patched_records": total_patched,
    }
