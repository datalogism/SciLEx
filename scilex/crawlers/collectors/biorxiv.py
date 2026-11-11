"""BioRxiv collector for SciLEx.

bioRxiv's API has no keyword search -- it only supports date-range queries.
This collector uses a two-phase cache+filter approach:

Phase 1 (Fetch): Download all papers for a given year and cache them locally.
Phase 2 (Filter): Read from cache, apply keyword matching, save filtered results.

The cache is stored in ``BioRxiv/_cache/{year}/`` with a ``_complete`` marker file.
This directory is automatically excluded from aggregation because
``discover_api_directories()`` only processes numeric directory names.

Subsequent queries for the same year skip the fetch phase entirely (instant).
"""

import json
import logging
import math
import os
import threading
from datetime import date

from scilex.crawlers.utils import sanitize_secrets

from .base import API_collector


class BioRxiv_collector(API_collector):
    """Collector for fetching preprints from the bioRxiv API.

    Uses the ``/details/`` endpoint which returns clean field names and
    up to 100 results per page. Since the API has no keyword search,
    we fetch all papers for a year, cache them, and filter client-side.
    """

    BASE_URL = "https://api.biorxiv.org/details/biorxiv"

    # Queries of the same year share one cache: serialise its download so that
    # parallel query threads do not fetch (and write) the same pages twice.
    _fetch_lock = threading.Lock()

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "BioRxiv"
        self.max_by_page = 100
        self.load_rate_limit_from_config()

    # ------------------------------------------------------------------
    # Methods required by API_collector interface (unused in our override)
    # ------------------------------------------------------------------

    def construct_search_query(self):
        """Not used -- bioRxiv API has no keyword search."""
        return ""

    def get_configurated_url(self):
        """Return the base URL template for the current year.

        The ``{}`` placeholder is filled with the cursor offset by
        ``_fetch_year_data``.
        """
        year = self.get_year()
        return f"{self.BASE_URL}/{year}-01-01/{year}-12-31/{{}}"

    def parsePageResults(self, response, page):
        """Parse a single page of bioRxiv /details/ JSON response.

        Args:
            response: requests.Response from the API.
            page: Current page number (1-indexed, for logging only).

        Returns:
            dict with keys ``total`` (int), ``results`` (list[dict]),
            plus standard metadata fields.
        """
        data = response.json()
        messages = data.get("messages", [{}])
        meta = messages[0] if messages else {}

        total = int(meta.get("total", 0))
        papers = data.get("collection", [])

        return {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": total,
            "results": papers,
        }

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_year_cache_dir(self, year):
        """Return the path ``<apiDir>/_cache/<year>/``."""
        return os.path.join(self.get_apiDir(), "_cache", str(year))

    def _year_cache_exists(self, cache_dir):
        """Check if the cache for a year is complete (``_complete`` marker)."""
        return os.path.isfile(os.path.join(cache_dir, "_complete"))

    def _fetch_year_data(self, year, cache_dir):
        """Paginate through the bioRxiv API and cache all pages for *year*.

        Each page is saved as ``page_<n>`` in *cache_dir*. A ``_complete``
        marker is written after the last page.
        """
        os.makedirs(cache_dir, exist_ok=True)

        cursor = 0
        page = 1
        total = None

        while True:
            if self._cancelled():
                # Caught by runCollect: the year cache stays without _complete.
                raise RuntimeError("collection cancelled")
            url = self.get_configurated_url().format(cursor)
            logging.debug(f"BioRxiv: Fetching year {year}, cursor {cursor}")

            response = self.api_call_decorator(url)
            page_data = self.parsePageResults(response, page)

            if total is None:
                total = page_data["total"]
                logging.info(
                    f"BioRxiv: Year {year} has {total} papers "
                    f"(~{math.ceil(total / self.max_by_page)} pages)"
                )

            # Save page to cache
            cache_file = os.path.join(cache_dir, f"page_{page}")
            temp_file = f"{cache_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(page_data, f)
            os.replace(temp_file, cache_file)

            self.log_api_usage(response, page, len(page_data["results"]))

            # Check if we have more pages
            if (
                len(page_data["results"]) < self.max_by_page
                or cursor + self.max_by_page >= total
            ):
                break

            cursor += self.max_by_page
            page += 1

        # Mark cache as complete
        with open(os.path.join(cache_dir, "_complete"), "w") as f:
            f.write(str(total))

        logging.info(f"BioRxiv: Cached {total} papers for year {year} in {page} pages")

    # ------------------------------------------------------------------
    # Keyword matching
    # ------------------------------------------------------------------

    @staticmethod
    def _keyword_matches(paper, keywords):
        """Check if *paper* matches ALL keywords (AND logic).

        Each keyword must appear in title OR abstract (case-insensitive
        substring match).

        Args:
            paper: dict from the bioRxiv API ``collection`` array.
            keywords: list of keyword strings (from the query).

        Returns:
            True if every keyword is found in the paper's title or abstract.
        """
        if not keywords:
            return True

        title = (paper.get("title") or "").lower()
        abstract = (paper.get("abstract") or "").lower()
        combined = f"{title} {abstract}"

        return all(kw.lower() in combined for kw in keywords)

    # ------------------------------------------------------------------
    # Main collection logic (overrides base class)
    # ------------------------------------------------------------------

    def _filter_and_save(self, cache_dir, keywords):
        """Read papers from cache, filter by keywords, save to query dir.

        Reads all ``page_*`` files from *cache_dir*, applies keyword
        filtering, and writes matching papers to the standard query
        directory (e.g. ``BioRxiv/0/``) as ``page_1``.

        Returns:
            dict with state data compatible with the base orchestrator.
        """
        matched = []

        page_files = sorted(
            [
                f
                for f in os.listdir(cache_dir)
                if f.startswith("page_") and not f.endswith(".tmp")
            ],
            key=lambda x: int(x.split("_")[1]),
        )

        for page_file in page_files:
            filepath = os.path.join(cache_dir, page_file)
            with open(filepath, encoding="utf-8") as f:
                page_data = json.load(f)

            for paper in page_data.get("results", []):
                if self._keyword_matches(paper, keywords):
                    matched.append(paper)

        logging.info(
            f"BioRxiv: Keyword filter matched {len(matched)} papers "
            f"from {len(page_files)} cached pages "
            f"(keywords: {keywords})"
        )

        self.createCollectDir()
        if matched:
            self.savePageResults(
                {
                    "date_search": str(date.today()),
                    "id_collect": self.get_collectId(),
                    "page": 1,
                    "total": len(matched),
                    "results": matched,
                },
                1,
            )
            self._flush_buffer()
            self.set_lastpage(1)
        self.nb_art_collected = len(matched)
        self._mark_complete()

        return {
            "state": 1,
            "last_page": 1 if matched else 0,
            "total_art": len(matched),
            "coll_art": len(matched),
            "update_date": str(date.today()),
            "id_collect": self.get_collectId(),
        }

    def runCollect(self):
        """Two-phase collection: cache year data, then filter by keywords.

        Phase 1: If the year cache doesn't exist, fetch all papers for
        the year from the API and store them in ``_cache/<year>/``.
        A failed download leaves no ``_complete`` marker and the query stays
        incomplete (``state`` = 0) so it is resumed on the next run.

        Phase 2: Read from cache, filter by keywords, save matching
        papers to the standard query directory.
        """
        if self.state == 1:
            logging.info("BioRxiv: Collection already completed.")
            return {
                "state": 1,
                "last_page": self.lastpage,
                "total_art": self.total_art,
                "coll_art": self.nb_art_collected,
                "update_date": str(date.today()),
                "id_collect": self.get_collectId(),
            }

        year = self.get_year()
        cache_dir = self._get_year_cache_dir(year)

        self._mark_incomplete()
        try:
            with self._fetch_lock:
                if not self._year_cache_exists(cache_dir):
                    logging.info(f"BioRxiv: Fetching all papers for year {year}...")
                    self._fetch_year_data(year, cache_dir)
                else:
                    logging.info(f"BioRxiv: Using cached data for year {year}")
        except Exception as fetch_exc:
            logging.error(
                f"BioRxiv: fetching year {year} failed: {sanitize_secrets(fetch_exc)}. "
                f"The query stays incomplete and will be resumed on the next run."
            )
            return {
                "state": 0,
                "last_page": self.lastpage,
                "total_art": self.total_art,
                "coll_art": self.nb_art_collected,
                "update_date": str(date.today()),
                "id_collect": self.get_collectId(),
            }

        return self._filter_and_save(cache_dir, self.get_keywords())
