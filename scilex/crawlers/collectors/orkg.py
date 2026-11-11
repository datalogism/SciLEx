import logging
import urllib.parse
from datetime import date

from .base import API_collector


class ORKG_collector(API_collector):
    """Collector for the Open Research Knowledge Graph (ORKG) API.

    ORKG provides ~55K structured research papers with rich metadata about
    research contributions, methods, and comparisons. No API key required.

    API documentation: https://orkg.org/api/
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 5.0
        self.max_by_page = 25
        self.api_name = "ORKG"
        self.api_url = "https://orkg.org/api/papers"
        self.load_rate_limit_from_config()

    def get_configurated_url(self):
        """Construct ORKG search URL with keyword query.

        Note: ORKG does not support year filtering in the API — year
        filtering is applied downstream by the aggregation quality filters.

        Returns:
            str: URL template with {} placeholder for 0-based page index.
        """
        # Flatten all keyword groups into a single space-joined query
        all_keywords = []
        for keyword_group in self.get_keywords():
            if isinstance(keyword_group, list):
                all_keywords.extend(keyword_group)
            else:
                all_keywords.append(keyword_group)

        keywords_str = " ".join(all_keywords)
        encoded_keywords = urllib.parse.quote(keywords_str, safe="")

        # ORKG ignores ``q`` (it returns the whole catalogue); ``title`` filters.
        url = (
            f"{self.api_url}?title={encoded_keywords}&size={self.max_by_page}&page={{}}"
        )

        logging.debug(f"ORKG configured URL: {url}")
        return url

    def get_offset(self, page):
        """Return the 0-based page index (ORKG uses 0-indexed pagination).

        Args:
            page: The current page number (1-indexed internally).

        Returns:
            int: 0-based page index for the ORKG API.
        """
        return page - 1

    def parsePageResults(self, response, page):
        """Parse a single page of ORKG API results.

        Args:
            response: requests.Response object from the API call.
            page: Current page number.

        Returns:
            dict: Standard page data dict with keys:
                  date_search, id_collect, page, total, results.
        """
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        data = response.json()

        # Extract total from pageable metadata
        try:
            page_data["total"] = int(data["page"]["total_elements"])
        except (KeyError, TypeError, ValueError) as e:
            logging.warning(f"ORKG: Could not extract total count: {e}")
            page_data["total"] = 0

        logging.debug(f"ORKG: Total results for page {page}: {page_data['total']}")

        # Extract results list
        try:
            page_data["results"] = data.get("content", [])
        except (AttributeError, TypeError) as e:
            logging.warning(f"ORKG: Could not extract results: {e}")
            page_data["results"] = []

        return page_data
