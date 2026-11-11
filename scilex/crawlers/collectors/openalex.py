import logging
from datetime import date

from .base import API_collector


class OpenAlex_collector(API_collector):
    """Class to collect publication data from the OpenAlex API."""

    def __init__(self, filter_param, data_path, api_key):
        """Initialize the OpenAlex collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            data_path (str): Path to save the collected data.
            api_key: API key from api.config.yml (free, get at openalex.org/settings/api).
                Without key: 100 credits/day. With key: 100,000 credits/day.
        """
        super().__init__(filter_param, data_path, api_key)
        self.max_by_page = 200  # Maximum number of results to retrieve per page
        self.api_name = "OpenAlex"
        self.api_url = "https://api.openalex.org/works"
        self.load_rate_limit_from_config()

    def parsePageResults(self, response, page):
        """Parse the results from a response for a specific page.

        Args:
            response (requests.Response): The API response object containing the results.
            page (int): The page number of results being processed.

        Returns:
            tuple: A (page_data dict, next_cursor str or None) pair.
                page_data contains metadata about the collected results.
                next_cursor is the cursor for the next page, or None if no more pages.
        """
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        page_with_results = response.json()

        meta = page_with_results.get("meta", {})
        total = meta.get("count", 0)
        page_data["total"] = int(total)
        next_cursor = meta.get("next_cursor")
        logging.debug(f"Total results found for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            for result in page_with_results.get("results", []):
                page_data["results"].append(result)

        return page_data, next_cursor

    def get_configurated_url(self):
        """Construct the API URL with search query and filters.

        Returns a base URL without pagination parameters — cursor pagination
        is appended by runCollect().

        Returns:
            str: The formatted API URL for the request.
        """
        keyword_filters = []

        for keyword_set in self.get_keywords():
            # Quoted phrase forces exact-phrase matching (not word-level relevance)
            keyword_filters.append(f'title_and_abstract.search:"{keyword_set}"')

        formatted_keyword_filters = ",".join(keyword_filters)

        years = self.get_year()
        year_filter = f"publication_year:{years}"
        start_date = self.get_query_start_date()
        if start_date:
            year_filter += f",from_publication_date:{start_date.isoformat()}"

        # Base URL without pagination — cursor is appended in runCollect()
        api_url = (
            f"{self.api_url}?filter={formatted_keyword_filters},{year_filter}"
            f"&per-page={self.max_by_page}"
        )

        # OpenAlex authenticates with api_key= (free key, own daily budget).
        # Without it, requests share a small per-IP budget and fail with 401
        # once it is spent. An email address is still accepted for old configs,
        # but OpenAlex no longer raises the limit for mailto=.
        if self.api_key:
            key_param = "mailto" if "@" in str(self.api_key) else "api_key"
            api_url += f"&{key_param}={self.api_key}"

        logging.debug(f"Configured URL: {self._sanitize_url(api_url)}")
        return api_url

    def runCollect(self):
        """Run collection using OpenAlex cursor-based pagination.

        Cursor pagination has no 10k result limit (unlike page-based pagination).
        See: https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/paging#cursor-paging

        The cursor is not persisted, so a partial run restarts from the first
        page (existing page files are overwritten). Buffered pages are always
        flushed, and the query is only marked complete when the cursor is
        exhausted or ``max_articles_per_query`` is reached.
        """
        state_data = self._state_snapshot()

        if self.state == 1:
            logging.info("Collection already completed.")
            return state_data

        if self.lastpage > 0:
            logging.info(
                f"OpenAlex Q{self.collectId}: cursor cannot be resumed, "
                f"restarting collection from the first page"
            )
            self.set_lastpage(0)
            self.nb_art_collected = 0
            state_data["last_page"] = 0
            state_data["coll_art"] = 0

        self._mark_incomplete()
        try:
            completed = self._collect_with_cursor(state_data)
        finally:
            self._flush_buffer()

        if completed:
            logging.debug("OpenAlex collection complete. Marking as done.")
            state_data["state"] = 1
            self._mark_complete()
        return state_data

    def _collect_with_cursor(self, state_data):
        """Follow the cursor until exhausted. Return True when fully collected."""
        base_url = self.get_configurated_url()
        cursor = "*"  # Initial cursor value for first request
        first_results_logged = False

        while cursor is not None:
            if self._cancelled():
                return False
            if self._max_articles_reached():
                logging.info(
                    f"Reached max_articles_per_query limit "
                    f"({self.filter_param.get_max_articles_per_query()}). "
                    f"Already collected {self.nb_art_collected} articles. Stopping."
                )
                return True

            page = self.get_lastpage() + 1
            url = f"{base_url}&cursor={cursor}"
            logging.debug(f"Fetching data from URL: {self._sanitize_url(url)}")

            try:
                response = self.api_call_decorator(url, headers=self.get_auth_headers())
                page_data, next_cursor = self.parsePageResults(response, page)
                self.log_api_usage(response, page, len(page_data.get("results", [])))
            except Exception as exc:
                throttle_code = self._throttle_status(exc)
                if throttle_code and self._try_vpn_rotation(throttle_code, page):
                    continue  # Same cursor, new IP
                logging.error(
                    f"Error processing results on page {page} from OpenAlex API: "
                    f"{self._sanitize_url(str(exc))}. The query stays incomplete "
                    f"and will be resumed on the next run."
                )
                return False

            nb_results = len(page_data["results"])
            if nb_results == 0:
                logging.debug("No more results returned. Collection complete.")
                return True

            self.nb_art_collected += nb_results
            if not first_results_logged:
                kw_str = " + ".join(f'"{k}"' for k in self.get_keywords())
                logging.info(
                    f"[OpenAlex] Q{self.collectId} ({kw_str}, {self.get_year()}): "
                    f"page {page} → {nb_results} results, {page_data['total']} total"
                )
                first_results_logged = True

            self.savePageResults(page_data, page)
            self.set_lastpage(page)

            state_data["last_page"] = page
            state_data["total_art"] = page_data["total"]
            state_data["coll_art"] = self.nb_art_collected
            logging.debug(
                f"Processed page {page}: {nb_results} results. "
                f"Total found: {page_data['total']}. "
                f"Collected so far: {self.nb_art_collected}"
            )
            cursor = next_cursor

        return True
