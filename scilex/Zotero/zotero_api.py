"""
Zotero API client for managing collections and items.

This module provides a clean interface to interact with the Zotero API,
handling authentication, collection management, and item creation.
"""

import json
import logging
import math
import random
import string
import time
from typing import Any

import pandas as pd
import requests

from scilex.constants import (
    MISSING_VALUE,
    ZoteroConstants,
    doi_to_url,
    is_valid,
    split_semicolon_field,
)

ZOTERO_TEMPLATE_URL = "https://api.zotero.org/items/new"
MAX_RATE_LIMIT_WAIT_SECONDS = 60
MAX_RATE_LIMIT_ATTEMPTS = 3
PAGE_SIZE = 100


def fetch_item_template(item_type: str) -> dict | None:
    """
    Fetch the Zotero template for an item type from the public API.

    The endpoint needs no authentication, so no ZoteroAPI instance is required.

    Args:
        item_type: The Zotero item type (e.g., "journalArticle")

    Returns:
        Template dictionary if successful, None otherwise
    """
    try:
        response = requests.get(
            ZOTERO_TEMPLATE_URL, params={"itemType": item_type}, timeout=30
        )
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logging.error(f"Failed to fetch template for {item_type}: {e}")
    return None


def _wait_seconds_from_headers(headers: Any) -> float:
    """Return the Retry-After / Backoff delay (capped) found in response headers."""
    for name in ("Retry-After", "Backoff"):
        try:
            return min(float(headers.get(name)), MAX_RATE_LIMIT_WAIT_SECONDS)
        except (TypeError, ValueError, AttributeError):
            continue
    return 0.0


class ZoteroAPI:
    """
    Client for interacting with the Zotero API.

    This class encapsulates all Zotero API operations including:
    - Authentication and authorization
    - Collection retrieval and creation
    - Item management
    - Bulk operations with error handling

    Attributes:
        user_id: The Zotero user or group ID
        user_role: Either "user" or "group"
        api_key: The Zotero API key for authentication
        base_endpoint: The API endpoint based on user role
    """

    def __init__(self, user_id: str, user_role: str, api_key: str):
        """
        Initialize the Zotero API client.

        Args:
            user_id: Zotero user or group ID
            user_role: Either "user" or "group"
            api_key: Zotero API key for authentication

        Raises:
            ValueError: If user_role is not "user" or "group"
        """
        if user_role not in ["user", "group"]:
            raise ValueError(
                f"Invalid user_role: {user_role}. Must be 'user' or 'group'"
            )

        self.user_id = user_id
        self.user_role = user_role
        self.api_key = api_key
        self.base_endpoint = (
            f"/groups/{user_id}" if user_role == "group" else f"/users/{user_id}"
        )
        self.headers = {"Zotero-API-Key": self.api_key}

    def _get_write_token(self) -> str:
        """
        Generate a random write token for Zotero API.

        Returns:
            A 32-character random token
        """
        return "".join(
            random.choices(
                string.ascii_uppercase + string.ascii_lowercase,
                k=ZoteroConstants.WRITE_TOKEN_LENGTH,
            )
        )

    def _get(self, path: str, params: dict | None = None) -> requests.Response | None:
        """
        Perform a GET request to the Zotero API.

        Args:
            path: API path (e.g., "/collections")
            params: Optional query parameters

        Returns:
            Response object if successful, None otherwise
        """
        url = f"{ZoteroConstants.API_BASE_URL}{self.base_endpoint}{path}"
        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=30
            )
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            logging.error(f"Timeout while accessing {url}")
        except requests.exceptions.RequestException as e:
            logging.error(f"GET request failed for {url}: {e}")
        return None

    def _post(
        self,
        path: str,
        data: Any,
        timeout: int = 120,
        write_token: str | None = None,
    ) -> requests.Response | None:
        """
        Perform a POST request to the Zotero API.

        Rate limiting (HTTP 429) is retried a few times honouring Retry-After;
        every attempt reuses the same write token so Zotero can deduplicate.

        Args:
            path: API path (e.g., "/items")
            data: Data to send (will be JSON-encoded)
            timeout: Request timeout in seconds (default: 120 for bulk uploads)
            write_token: Idempotency token; generated when omitted. Pass the same
                token when re-sending the same payload.

        Returns:
            Response object if successful, None otherwise
        """
        url = f"{ZoteroConstants.API_BASE_URL}{self.base_endpoint}{path}"
        post_headers = self.headers.copy()
        post_headers.update(
            {
                "Zotero-Write-Token": write_token or self._get_write_token(),
                "Content-Type": "application/json",
            }
        )

        for attempt in range(1, MAX_RATE_LIMIT_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url, headers=post_headers, data=json.dumps(data), timeout=timeout
                )
                if response.status_code == 429 and attempt < MAX_RATE_LIMIT_ATTEMPTS:
                    wait = _wait_seconds_from_headers(response.headers) or 5.0
                    logging.warning(f"Rate limited by Zotero, retrying in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                time.sleep(_wait_seconds_from_headers(response.headers))
                return response
            except requests.exceptions.Timeout:
                logging.error(f"Timeout after {timeout}s while posting to {url}")
            except requests.exceptions.RequestException as e:
                logging.error(f"POST request failed for {url}: {e}")
            return None
        return None

    def _get_paginated(self, path: str, limit: int = PAGE_SIZE) -> list[dict] | None:
        """
        Fetch every page of a list endpoint.

        Args:
            path: API path (e.g., "/collections")
            limit: Page size

        Returns:
            All results concatenated, or None if any page request failed
        """
        results: list[dict] = []
        start = 0
        while True:
            response = self._get(path, params={"limit": limit, "start": start})
            if not response:
                return None
            try:
                page = response.json()
            except ValueError as e:
                logging.error(f"Failed to parse JSON from {path}: {e}")
                return None
            if not page:
                break
            results.extend(page)
            try:
                total = int(response.headers.get("Total-Results"))
            except (TypeError, ValueError):
                total = None
            if len(page) < limit or (total is not None and start + limit >= total):
                break
            start += limit
        return results

    def get_collections(self, limit: int = PAGE_SIZE) -> list[dict] | None:
        """
        Retrieve all collections for the user/group (all pages).

        Args:
            limit: Page size

        Returns:
            List of collection dictionaries, or None if a request failed
        """
        return self._get_paginated("/collections", limit=limit)

    def find_collection_by_name(self, name: str) -> dict | None:
        """
        Find a collection by its name.

        Args:
            name: The collection name to search for

        Returns:
            Collection dictionary if found, None otherwise
        """
        collections = self.get_collections()
        if not collections:
            return None

        for collection in collections:
            if collection.get("data", {}).get("name") == name:
                logging.info(f"Found existing collection: '{name}'")
                return collection

        return None

    def create_collection(self, name: str) -> dict | None:
        """
        Create a new collection.

        Args:
            name: Name for the new collection

        Returns:
            Created collection dictionary if successful, None otherwise
        """
        logging.info(f"Creating collection: '{name}'")
        response = self._post("/collections", data=[{"name": name}])

        if response and response.status_code in [200, 201]:
            logging.info(f"Successfully created collection '{name}'")
            try:
                created = response.json()["successful"]["0"]
                if created.get("key"):
                    created.setdefault("data", {"key": created["key"], "name": name})
                    return created
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            # Response body unusable: fall back to looking it up by name
            return self.find_collection_by_name(name)
        return None

    def get_or_create_collection(self, name: str) -> dict | None:
        """
        Get an existing collection or create it if it doesn't exist.

        Args:
            name: Collection name to find or create

        Returns:
            Collection dictionary if successful, None otherwise
        """
        # Try to find existing collection
        collection = self.find_collection_by_name(name)
        if collection:
            return collection

        # Create if not found
        return self.create_collection(name)

    def get_collection_items(
        self, collection_key: str, limit: int = PAGE_SIZE
    ) -> list[dict]:
        """
        Get all items in a collection (all pages).

        Args:
            collection_key: The collection's key
            limit: Items per page

        Returns:
            List of item dictionaries (empty if the request failed)
        """
        items = self._get_paginated(f"/collections/{collection_key}/items", limit=limit)
        if items is None:
            logging.error(f"Could not list items of collection {collection_key}")
            items = []
        logging.info(f"Found {len(items)} items in collection")
        return items

    def get_top_items(self, collection_key: str | None = None) -> list[dict] | None:
        """
        Get the top-level items (papers, not attachments or notes), all pages.

        Args:
            collection_key: A collection's key, or None for the whole library.

        Returns:
            List of item dictionaries, or None if a request failed
        """
        path = (
            f"/collections/{collection_key}/items/top"
            if collection_key
            else "/items/top"
        )
        return self._get_paginated(path)

    def get_groups(self) -> list[dict] | None:
        """Return the groups the key's user belongs to (only for a user library client).

        Returns:
            Group dictionaries (``data.id``, ``data.name``), or None if the request failed.
        """
        if self.user_role != "user":
            return []
        return self._get_paginated("/groups")

    def export_top_items(
        self,
        collection_key: str | None,
        export_format: str = "biblatex",
        limit: int = PAGE_SIZE,
    ) -> str | None:
        """Export top-level items in a Zotero export format.

        Zotero's own translator does the conversion (e.g. ``biblatex``: tags in
        ``keywords``, Extra in ``note``), page by page.

        Args:
            collection_key: The collection's key, or None for the whole library.
            export_format: A Zotero export format (``biblatex``, ``bibtex``, ``ris``...).
            limit: Items per page.

        Returns:
            The concatenated export, or None if a page request failed.
        """
        path = (
            f"/collections/{collection_key}/items/top" if collection_key else "/items/top"
        )
        chunks: list[str] = []
        start = 0
        while True:
            response = self._get(
                path, params={"format": export_format, "limit": limit, "start": start}
            )
            if not response:
                return None
            response.encoding = "utf-8"
            chunks.append(response.text)
            try:
                total = int(response.headers.get("Total-Results"))
            except (TypeError, ValueError):
                total = None
            start += limit
            if total is None or start >= total:
                break
        return "\n".join(chunks)

    def update_item_tags(
        self, updates: dict[str, tuple[int, list[str]]], batch_size: int = 50
    ) -> dict[str, int]:
        """
        Replace the tags of existing items, ``batch_size`` items per request.

        Each item is sent with the version it was read at: Zotero rejects the
        change (counted as failed) if someone edited the item in between.

        Args:
            updates: ``{item key: (item version, new tag list)}``.
            batch_size: Items per request (Zotero accepts at most 50).

        Returns:
            ``{"success": n, "failed": m}``
        """
        payload = [
            {"key": key, "version": version, "tags": [{"tag": tag} for tag in tags]}
            for key, (version, tags) in updates.items()
        ]
        totals = {"success": 0, "failed": 0}
        for start in range(0, len(payload), batch_size):
            batch = payload[start : start + batch_size]
            response = self._post("/items", batch)
            if response is None:
                totals["failed"] += len(batch)
                continue
            outcome = self._count_outcome(response, batch)
            totals["success"] += outcome["success"]
            totals["failed"] += outcome["failed"]
        return totals

    def get_existing_item_urls(self, collection_key: str) -> set:
        """
        Get URLs of all existing items in a collection.

        This is useful for checking duplicates before adding new items.
        Returns a set for O(1) lookup performance.

        Args:
            collection_key: The collection's key

        Returns:
            Set of URLs from existing items
        """
        items = self.get_collection_items(collection_key)
        urls = set()

        for item in items:
            url = item.get("data", {}).get("url")
            if url:
                urls.add(url)

        logging.info(f"Found {len(urls)} existing URLs in collection")
        return urls

    @staticmethod
    def _count_outcome(response: Any, batch: list[dict]) -> dict[str, int]:
        """
        Count per-item outcomes from a successful (HTTP 2xx) write response.

        Zotero answers 200 even when some items were rejected; the body holds
        {"successful", "unchanged", "failed"}. If the body is not in that shape,
        the whole batch is counted as successful.
        """
        try:
            body = response.json()
        except (ValueError, AttributeError):
            body = None
        if not isinstance(body, dict) or not any(
            key in body for key in ("successful", "unchanged", "failed")
        ):
            return {"success": len(batch), "failed": 0}

        failed = body.get("failed") or {}
        for index, error in failed.items():
            message = error.get("message") if isinstance(error, dict) else error
            logging.warning(f"Zotero rejected item {index}: {message}")
        success = len(body.get("successful") or {}) + len(body.get("unchanged") or {})
        return {"success": success, "failed": len(failed)}

    def post_items_bulk(
        self, items: list[dict], batch_size: int = 50
    ) -> dict[str, int]:
        """
        Post multiple items to Zotero using true bulk API calls.

        Zotero API supports up to 50 items per POST request. Each batch gets one
        write token reused when the same batch is re-sent after a timeout; if it
        still fails, the batch is split into smaller ones (25, then 10).
        Per-item failures reported in a 200 response are counted as failed.

        Args:
            items: List of item data dictionaries
            batch_size: Number of items per batch (max 50 per Zotero API)

        Returns:
            Dictionary with counts: {"success": n, "failed": m}
        """
        results = {"success": 0, "failed": 0}

        # Validate batch size
        if batch_size > 50:
            logging.warning(
                f"Batch size {batch_size} exceeds Zotero API limit of 50. Using 50."
            )
            batch_size = 50

        # Process items in batches
        total_batches = (len(items) + batch_size - 1) // batch_size
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            batch_num = (i // batch_size) + 1

            logging.debug(
                f"Posting batch {batch_num}/{total_batches} ({len(batch)} items)"
            )

            write_token = self._get_write_token()
            response = self._post("/items", data=batch, write_token=write_token)
            if response is None:
                # Possible timeout: the server may have processed it. Re-send the
                # identical payload with the same token (idempotent).
                response = self._post("/items", data=batch, write_token=write_token)

            if response and response.status_code in [200, 201]:
                outcome = self._count_outcome(response, batch)
                results["success"] += outcome["success"]
                results["failed"] += outcome["failed"]
                logging.debug(f"Batch {batch_num} posted: {outcome}")
            elif response is None and len(batch) > 10:
                logging.warning(
                    f"Batch {batch_num} failed (likely timeout). Retrying with smaller batches..."
                )
                retry_results = self._retry_with_smaller_batches(batch)
                results["success"] += retry_results["success"]
                results["failed"] += retry_results["failed"]
            else:
                results["failed"] += len(batch)
                logging.warning(
                    f"Batch {batch_num} failed - {len(batch)} items not posted"
                )

        logging.info(
            f"Bulk post complete: {results['success']} succeeded, "
            f"{results['failed']} failed across {total_batches} batches"
        )
        return results

    def _retry_with_smaller_batches(self, items: list[dict]) -> dict[str, int]:
        """
        Retry posting items with progressively smaller batch sizes.

        Args:
            items: List of items that failed in a larger batch

        Returns:
            Dictionary with counts: {"success": n, "failed": m}
        """
        results = {"success": 0, "failed": 0}
        remaining_items = items.copy()

        # Try with half the original size first, then smaller
        for retry_size in [25, 10]:
            if not remaining_items:
                break

            # Skip if batch size is too large for remaining items
            if len(remaining_items) <= retry_size:
                retry_size = len(remaining_items)

            logging.info(
                f"Retrying {len(remaining_items)} items with batch size {retry_size}"
            )

            failed_in_this_round = []
            for i in range(0, len(remaining_items), retry_size):
                sub_batch = remaining_items[i : i + retry_size]
                response = self._post("/items", data=sub_batch)

                if response and response.status_code in [200, 201]:
                    outcome = self._count_outcome(response, sub_batch)
                    results["success"] += outcome["success"]
                    results["failed"] += outcome["failed"]
                else:
                    results["failed"] += len(sub_batch)
                    failed_in_this_round.extend(sub_batch)

            # Update remaining items for next retry
            remaining_items = failed_in_this_round

            # If all succeeded with this batch size, stop retrying
            if not remaining_items:
                break

        return results


def _log10_bucket(value) -> int | None:
    """Return 10^floor(log10(value)), e.g. 47 → 10, 5 → 1, 200 → 100. None if <= 0."""
    try:
        n = float(value)
        if n <= 0 or (isinstance(value, float) and math.isnan(n)):
            return None
        return int(10 ** math.floor(math.log10(n)))
    except (ValueError, TypeError):
        return None


def prepare_zotero_item(
    row: pd.Series,
    collection_key: str,
    templates_cache: dict[str, dict],
) -> dict | None:
    """
    Prepare a Zotero item from a DataFrame row.

    Args:
        row: DataFrame row containing paper metadata (Series or named tuple from itertuples)
        collection_key: Key of the target collection
        templates_cache: Dictionary to cache item templates by type

    Returns:
        Prepared item dictionary, or None if item_type is invalid
    """

    def get_value(row, field: str, default=MISSING_VALUE):
        if hasattr(row, "get"):  # pd.Series
            return row.get(field, default)
        return getattr(row, field, default)  # named tuple from itertuples

    item_type = get_value(row, "itemType")

    # Handle bookSection -> journalArticle conversion
    if item_type == "bookSection":
        item_type = "journalArticle"

    if not is_valid(item_type):
        return None

    # Get or fetch template
    if item_type not in templates_cache:
        template = fetch_item_template(item_type)
        if not template:
            return None
        templates_cache[item_type] = template

    item = templates_cache[item_type].copy()
    item["collections"] = [collection_key]

    # --- Direct field mappings ---
    common_fields = [
        "publisher",
        "title",
        "date",
        "DOI",
        "archive",
        "url",
        "rights",
        "pages",
        "journalAbbreviation",
        "conferenceName",
        "volume",
        "issue",
        "language",
    ]
    for field in common_fields:
        val = get_value(row, field)
        if field in item and is_valid(val):
            item[field] = str(val)

    if "series" in item:
        serie = get_value(row, "serie")
        if is_valid(serie):
            item["series"] = str(serie)

    if "abstractNote" in item:
        item["abstractNote"] = str(get_value(row, "abstract", ""))

    # --- Authors ---
    authors_str = get_value(row, "authors")
    if is_valid(authors_str):
        authors = str(authors_str).split(";")
        if item.get("creators"):
            template_author = item["creators"][0].copy()
            item["creators"] = [
                dict(template_author, firstName=auth.strip()) for auth in authors
            ]

    # --- URL fallback to DOI ---
    if not is_valid(item.get("url")):
        doi = item.get("DOI")
        item["url"] = doi_to_url(doi)

    # --- Resolve github_repo / archiveID for archiveLocation + extra ---
    github_repo = get_value(row, "github_repo", MISSING_VALUE)
    archive_id = get_value(row, "archiveID", MISSING_VALUE)
    github_valid = is_valid(github_repo) and github_repo != MISSING_VALUE
    archive_id_valid = is_valid(archive_id)

    extra_lines = []

    # Existing free-text extra column
    existing_extra = get_value(row, "extra", MISSING_VALUE)
    if is_valid(existing_extra) and existing_extra != MISSING_VALUE:
        extra_lines.append(str(existing_extra))

    if "archiveLocation" in item:
        if github_valid:
            item["archiveLocation"] = str(github_repo)
            if archive_id_valid:  # archiveID bumped to extra
                extra_lines.append(f"Archive ID: {archive_id}")
        elif archive_id_valid:
            item["archiveLocation"] = str(archive_id)

    # URLs in extra
    pdf_url = get_value(row, "pdf_url", MISSING_VALUE)
    pdf_valid = is_valid(pdf_url) and pdf_url != MISSING_VALUE
    if pdf_valid:
        extra_lines.append(f"PDF URL: {pdf_url}")

    pwc_url = get_value(row, "pwc_url", MISSING_VALUE)
    if not (is_valid(pwc_url) and pwc_url != MISSING_VALUE):
        pwc_url = get_value(row, "hf_url", MISSING_VALUE)
    pwc_valid = is_valid(pwc_url) and pwc_url != MISSING_VALUE
    if pwc_valid:
        extra_lines.append(f"Papers with Code: {pwc_url}")

    if extra_lines and "extra" in item:
        item["extra"] = "\n".join(extra_lines)

    # --- Tags ---
    all_tags = []

    # Enrichment tags + bonus keyword tags + collect keywords
    all_tags.extend(split_semicolon_field(get_value(row, "tags", MISSING_VALUE)))
    all_tags.extend(
        split_semicolon_field(get_value(row, "bonus_keyword_tags", MISSING_VALUE))
    )
    all_tags.extend(
        split_semicolon_field(get_value(row, "collect_keywords", MISSING_VALUE))
    )

    # Presence tags
    if pdf_valid:
        all_tags.append("HavePDF")
    if pwc_valid:
        all_tags.append("HavePWC")
    if github_valid:
        all_tags.append("HaveGithub")

    # Citation score: average of OA + SS, bucketed by power of 10
    oa = get_value(row, "oa_citation_count", MISSING_VALUE)
    ss = get_value(row, "ss_citation_count", MISSING_VALUE)
    try:
        vals = []
        if is_valid(oa):
            vals.append(float(oa))
        if is_valid(ss):
            vals.append(float(ss))
        if vals:
            avg_cit = sum(vals) / len(vals)
            bucket = _log10_bucket(avg_cit)
            if bucket is not None:
                all_tags.append(f"CITAT:{bucket}")
    except (ValueError, TypeError):
        pass

    # Quality score: raw 0-100 → normalized 0-10
    quality = get_value(row, "quality_score", MISSING_VALUE)
    if is_valid(quality):
        try:
            q = max(0, min(10, round(float(quality) / 10)))
            all_tags.append(f"QUALI_SCORE:{q}")
        except (ValueError, TypeError):
            pass

    # Relevance score: already ~0-10 scale → round to int
    relevance = get_value(row, "relevance_score", MISSING_VALUE)
    if is_valid(relevance):
        try:
            r = max(0, min(10, round(float(relevance))))
            all_tags.append(f"REL_SCORE:{r}")
        except (ValueError, TypeError):
            pass

    if all_tags:
        item["tags"] = [{"tag": t} for t in all_tags]

    return item if item.get("url") else None
