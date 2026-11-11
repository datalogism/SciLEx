"""SQLite-based citation caching system.

Provides persistent caching for citation data to avoid redundant API calls.
Features:
- DOI-based lookups
- 30-day TTL (Time To Live)
- Thread-safe operations
- Automatic cache cleanup
"""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from scilex.constants import normalize_doi

# Open connections keyed by (thread id, resolved path); guarded by a lock so
# close_connections() can close every connection opened by any thread.
_connections: dict[tuple[int, str], sqlite3.Connection] = {}
_connections_lock = threading.Lock()

# Default cache TTL: 30 days
DEFAULT_TTL_DAYS = 30


def get_cache_path(output_dir: str = "output") -> Path:
    """Get the path to the citation cache database.

    Args:
        output_dir: Base output directory

    Returns:
        Path to citation_cache.db file
    """
    cache_dir = Path(output_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "citation_cache.db"


def _get_connection(cache_path: Path) -> sqlite3.Connection:
    """Get the database connection for the current thread and given path.

    Each (thread, path) pair gets its own connection, so using a different
    cache_path never silently reuses a connection to another database.

    Args:
        cache_path: Path to SQLite database

    Returns:
        sqlite3.Connection for current thread and path
    """
    key = (threading.get_ident(), str(cache_path))
    with _connections_lock:
        conn = _connections.get(key)
        if conn is None:
            conn = sqlite3.connect(
                str(cache_path),
                check_same_thread=False,  # close_connections() may run elsewhere
                timeout=30.0,  # 30 second timeout for locks
            )
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _connections[key] = conn
    return conn


def should_cache_result(result: dict) -> bool:
    """Tell whether a citation result is complete enough to be cached.

    Only results where both the citations and references lookups succeeded
    are cacheable; partial or failed results would poison the cache for 30 days.

    Args:
        result: Dict with an ``api_stats`` mapping (``cit_status``/``ref_status``)

    Returns:
        True only if both statuses equal "success".
    """
    api_stats = (result or {}).get("api_stats") or {}
    return (
        api_stats.get("cit_status") == "success"
        and api_stats.get("ref_status") == "success"
    )


def initialize_cache(cache_path: Path | None = None) -> Path:
    """Initialize citation cache database with schema.

    Args:
        cache_path: Optional path to cache database (default: output/citation_cache.db)

    Returns:
        Path to initialized cache database
    """
    if cache_path is None:
        cache_path = get_cache_path()

    conn = _get_connection(cache_path)
    cursor = conn.cursor()

    # Create citations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS citations (
            doi TEXT PRIMARY KEY,
            citations_json TEXT NOT NULL,
            nb_cited INTEGER,
            nb_citations INTEGER,
            cit_status TEXT,
            ref_status TEXT,
            cached_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )
    """)

    # Create index on expiration time for fast cleanup
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_expires_at ON citations(expires_at)
    """)

    conn.commit()
    logging.debug(f"Citation cache initialized at {cache_path}")

    return cache_path


def get_cached_citations_batch(dois: list[str], cache_path: Path | None = None) -> dict:
    """Retrieve cached citations for multiple DOIs in one SQL query.

    Uses WHERE doi IN (...) with chunking to stay within SQLite's parameter
    limit (~999). Much faster than N individual queries for large DOI lists.

    Args:
        dois: List of DOI strings to look up.
        cache_path: Optional path to cache database.

    Returns:
        dict: {doi as passed in: {"citations": ..., "nb_cited": ..., "nb_citations": ...,
               "api_stats": {...}}} for found DOIs. DOIs not in cache (or
               expired) are omitted.
    """
    # Map normalized DOI -> original spellings so callers get their own keys back
    originals: dict[str, list[str]] = {}
    for doi in dois or []:
        normalized_doi = normalize_doi(doi)
        if normalized_doi is not None:
            originals.setdefault(normalized_doi, []).append(doi)
    if not originals:
        return {}
    normalized_dois = list(originals)

    if cache_path is None:
        cache_path = get_cache_path()

    conn = _get_connection(cache_path)
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    results = {}
    chunk_size = 500  # SQLite parameter limit safety margin

    for i in range(0, len(normalized_dois), chunk_size):
        chunk = normalized_dois[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(
            f"""
            SELECT doi, citations_json, nb_cited, nb_citations, cit_status, ref_status
            FROM citations
            WHERE doi IN ({placeholders}) AND expires_at > ?
            """,
            (*chunk, now),
        )
        for row in cursor.fetchall():
            entry = {
                "citations": row[1],
                "nb_cited": row[2],
                "nb_citations": row[3],
                "api_stats": {"cit_status": row[4], "ref_status": row[5]},
            }
            for original_doi in originals[row[0]]:
                results[original_doi] = entry

    logging.debug(f"Batch cache lookup: {len(results)}/{len(normalized_dois)} hits")
    return results


def cache_citations_batch(
    entries: list[dict],
    cache_path: Path | None = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> None:
    """Store multiple citation results in one transaction.

    Uses executemany() with INSERT OR REPLACE for efficient bulk writes.

    Args:
        entries: List of dicts, each with keys:
            doi, citations_json, nb_cited, nb_citations, api_stats
        cache_path: Optional path to cache database.
        ttl_days: Time to live in days (default: 30).
    """
    entries = [
        {**entry, "doi": normalize_doi(entry["doi"])}
        for entry in entries or []
        if normalize_doi(entry["doi"]) is not None
    ]
    if not entries:
        return

    if cache_path is None:
        cache_path = get_cache_path()

    conn = _get_connection(cache_path)
    cursor = conn.cursor()

    now = datetime.now()
    expires_at = (now + timedelta(days=ttl_days)).isoformat()
    now_iso = now.isoformat()

    rows = [
        (
            e["doi"],
            e["citations_json"],
            e["nb_cited"],
            e["nb_citations"],
            e["api_stats"].get("cit_status", "unknown"),
            e["api_stats"].get("ref_status", "unknown"),
            now_iso,
            expires_at,
        )
        for e in entries
    ]

    cursor.executemany(
        """
        INSERT OR REPLACE INTO citations
        (doi, citations_json, nb_cited, nb_citations, cit_status, ref_status, cached_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    logging.debug(f"Batch cached {len(entries)} citation entries")


def cleanup_expired_cache(cache_path: Path | None = None) -> int:
    """Remove expired entries from cache.

    Args:
        cache_path: Optional path to cache database

    Returns:
        Number of entries removed
    """
    if cache_path is None:
        cache_path = get_cache_path()

    conn = _get_connection(cache_path)
    cursor = conn.cursor()

    # Delete expired entries
    cursor.execute(
        """
        DELETE FROM citations WHERE expires_at <= ?
    """,
        (datetime.now().isoformat(),),
    )

    removed_count = cursor.rowcount
    conn.commit()

    if removed_count > 0:
        logging.info(f"Cleaned up {removed_count} expired cache entries")

    return removed_count


def get_cache_stats(cache_path: Path | None = None) -> dict:
    """Get cache statistics.

    Args:
        cache_path: Optional path to cache database

    Returns:
        Dict with cache statistics
    """
    if cache_path is None:
        cache_path = get_cache_path()

    conn = _get_connection(cache_path)
    cursor = conn.cursor()

    # Total entries
    cursor.execute("SELECT COUNT(*) FROM citations")
    total = cursor.fetchone()[0]

    # Active (non-expired) entries
    cursor.execute(
        """
        SELECT COUNT(*) FROM citations WHERE expires_at > ?
    """,
        (datetime.now().isoformat(),),
    )
    active = cursor.fetchone()[0]

    # Expired entries
    expired = total - active

    return {
        "total_entries": total,
        "active_entries": active,
        "expired_entries": expired,
        "cache_path": str(cache_path),
    }


def close_connections() -> None:
    """Close every database connection opened by any thread."""
    with _connections_lock:
        for conn in _connections.values():
            try:
                conn.close()
            except sqlite3.Error as error:
                logging.debug(f"Error closing cache connection: {error}")
        _connections.clear()
