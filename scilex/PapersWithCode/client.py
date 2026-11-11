"""Papers with Code API client (https://paperswithcode.co/api/v1) with caching.

The API is anonymous and read-only. Two lookups are used:

- ``search_papers(title)``: title search, returns light candidates
  (``id``, ``arxiv_id``, ``title``) for fuzzy matching;
- ``get_paper(paper_id)`` / ``get_paper_by_arxiv(arxiv_id)``: the full record,
  reduced by ``summarize_paper`` to the fields the enrichment uses.

Only these reduced results are cached (SQLite, TTL in days): a full record can
list hundreds of repositories. Rate limiting only applies to network calls.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from ratelimit import limits, sleep_and_retry

BASE_URL = "https://paperswithcode.co/api/v1"
PAPER_PAGE_URL = "https://paperswithcode.co/paper/{}"
MAX_RETRIES = 3
# Cached marker for "the API has no such paper" (distinct from a cache miss).
NOT_FOUND = "__none__"


class PWCCache:
    """SQLite cache of Papers with Code results (WAL mode, thread safe)."""

    TABLES = ("pwc_search", "pwc_papers")

    def __init__(self, cache_path: str = "output/pwc_cache.db"):
        """Create the database and its tables if needed.

        Args:
            cache_path: Path to the SQLite cache database.
        """
        self.cache_path = cache_path
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            for table in self.TABLES:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        cache_key TEXT PRIMARY KEY,
                        result_json TEXT NOT NULL,
                        expires_at TIMESTAMP NOT NULL
                    )
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Open a connection that waits for concurrent writers."""
        return sqlite3.connect(self.cache_path, timeout=30)

    def get(self, table: str, key: str):
        """Return the cached value, or None when absent or expired.

        A cached "not found" is stored as JSON ``null`` and returned as
        ``NOT_FOUND`` so callers can tell it from a cache miss.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT result_json, expires_at FROM {table} WHERE cache_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        if not row or datetime.now() >= datetime.fromisoformat(row[1]):
            return None
        value = json.loads(row[0])
        return NOT_FOUND if value is None else value

    def set(self, table: str, key: str, value, ttl_days: int) -> None:
        """Store a value (None means "not found") under key for ttl_days."""
        expires_at = datetime.now() + timedelta(days=ttl_days)
        conn = self._connect()
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (cache_key, result_json, expires_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), expires_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()


@sleep_and_retry
@limits(calls=5, period=1)
def _throttle() -> None:
    """Block until a network call is allowed (cache hits never call this)."""


def _normalize_key(text: str) -> str:
    """Lowercase and collapse whitespace so equivalent queries share a key."""
    return " ".join(text.lower().split())


def _pick_repository(repositories: list[dict]) -> dict | None:
    """Return the official repository, else the most starred one."""
    if not repositories:
        return None
    official = [repo for repo in repositories if repo.get("is_official")]
    candidates = official or repositories
    return max(candidates, key=lambda repo: repo.get("num_stars") or 0)


def summarize_paper(record: dict) -> dict:
    """Reduce a full Papers with Code record to the fields the enrichment uses.

    Args:
        record: JSON of ``GET /papers/{id}?include_resources=true``.

    Returns:
        Dict with ``id``, ``arxiv_id``, ``title``, ``url``, ``tasks``,
        ``methods``, ``benchmarks``, ``frameworks``, ``github_repo`` and
        ``github_stars`` (lists of names, None when absent).
    """
    repository = _pick_repository(record.get("repositories") or [])
    page_id = record.get("arxiv_id") or record.get("id")
    return {
        "id": record.get("id"),
        "arxiv_id": record.get("arxiv_id"),
        "title": record.get("title") or "",
        "url": PAPER_PAGE_URL.format(page_id) if page_id else None,
        "tasks": [t["name"] for t in record.get("tasks") or [] if t.get("name")],
        "methods": [m["name"] for m in record.get("methods") or [] if m.get("name")],
        "benchmarks": [b for b in record.get("evaluated_benchmarks") or [] if b],
        "frameworks": _names(record.get("introduced_frameworks")),
        "github_repo": repository.get("url") if repository else None,
        "github_stars": repository.get("num_stars") if repository else None,
    }


def _names(values) -> list[str]:
    """Names from a list of strings or ``{"name": ...}`` dicts."""
    names = []
    for value in values or []:
        name = value.get("name") if isinstance(value, dict) else value
        if name:
            names.append(str(name))
    return names


class PWCClient:
    """Client for the Papers with Code API with a persistent cache."""

    def __init__(
        self,
        cache_path: str = "output/pwc_cache.db",
        cache_ttl_days: int = 30,
        session: requests.Session | None = None,
    ):
        """Initialize the client.

        Args:
            cache_path: Path to the SQLite cache database.
            cache_ttl_days: Cache expiration in days.
            session: Optional requests session (tests inject a mock).
        """
        self.cache = PWCCache(cache_path)
        self.cache_ttl_days = cache_ttl_days
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Rate-limited GET; returns JSON, or None on 404.

        Retries on 429/503, honouring ``Retry-After``.

        Raises:
            requests.exceptions.RequestException: On other network/HTTP errors.
        """
        for attempt in range(MAX_RETRIES):
            _throttle()
            response = self.session.get(f"{BASE_URL}/{path}", params=params, timeout=30)
            if response.status_code == 404:
                return None
            if response.status_code in (429, 503) and attempt < MAX_RETRIES - 1:
                time.sleep(_retry_after(response, attempt))
                continue
            response.raise_for_status()
            return response.json()
        return None  # unreachable: the last attempt raises or returns

    def search_papers(self, title: str, limit: int = 10) -> list[dict]:
        """Search papers by title; returns ``[{id, arxiv_id, title}, ...]``.

        Errors are logged and return an empty list (nothing is cached).
        """
        key = f"{_normalize_key(title)}|{limit}"
        cached = self.cache.get("pwc_search", key)
        if cached is not None:
            return [] if cached == NOT_FOUND else cached
        try:
            data = self._get("papers/search", {"q": title, "page_size": limit})
        except requests.exceptions.RequestException as error:
            logging.error(f"Papers with Code search failed: {error}")
            return []
        results = [
            {
                "id": paper.get("id"),
                "arxiv_id": paper.get("arxiv_id"),
                "title": paper.get("title") or "",
            }
            for paper in (data or {}).get("results", [])[:limit]
        ]
        self.cache.set("pwc_search", key, results, self.cache_ttl_days)
        return results

    def get_paper(self, paper_id: str) -> dict | None:
        """Full record (summarized) by catalog ID or arXiv ID, or None."""
        return self._get_summary(f"papers/{paper_id}", f"id:{paper_id}")

    def get_paper_by_arxiv(self, arxiv_id: str) -> dict | None:
        """Full record (summarized) by arXiv ID, or None when not in the catalog."""
        return self._get_summary(f"papers/arxiv/{arxiv_id}", f"arxiv:{arxiv_id}")

    def _get_summary(self, path: str, key: str) -> dict | None:
        """Fetch a record, summarize and cache it (a 404 is cached too)."""
        cached = self.cache.get("pwc_papers", key)
        if cached is not None:
            return None if cached == NOT_FOUND else cached
        try:
            record = self._get(path, {"include_resources": "true"})
        except requests.exceptions.RequestException as error:
            logging.warning(f"Papers with Code lookup failed for {key}: {error}")
            return None
        summary = summarize_paper(record) if record else None
        self.cache.set("pwc_papers", key, summary, self.cache_ttl_days)
        return summary


def _retry_after(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before a retry: ``Retry-After`` or exponential backoff."""
    try:
        return min(float(response.headers.get("Retry-After", "")), 60.0)
    except ValueError:
        return float(2**attempt)
