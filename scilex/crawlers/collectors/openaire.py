import logging
import urllib.parse
from datetime import date

from .base import API_collector


class OpenAIRE_collector(API_collector):
    """Collector for the OpenAIRE Research Graph API.

    OpenAIRE provides 200M+ open-access publications from European and global
    research infrastructure. No API key required.

    API documentation: https://api.openaire.eu/
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 5.0
        self.max_by_page = 100
        self.api_name = "OpenAIRE"
        self.api_url = "https://api.openaire.eu/search/publications"
        self.load_rate_limit_from_config()

    def get_configurated_url(self):
        """Construct OpenAIRE search URL with keyword and year filters.

        Returns:
            str: URL template with {} placeholder for page number.
        """
        # Each keyword is quoted for exact-phrase matching. Terms are joined by a
        # space (implicit AND): the API now answers HTTP 409 to an explicit "AND".
        all_keywords = []
        for keyword_group in self.get_keywords():
            if isinstance(keyword_group, list):
                all_keywords.extend(keyword_group)
            else:
                all_keywords.append(keyword_group)

        keywords_str = " ".join(f'"{kw}"' for kw in all_keywords)
        encoded_keywords = urllib.parse.quote(keywords_str, safe="")

        year = self.get_year()
        from_date = f"{year}-01-01"
        to_date = f"{year}-12-31"

        url = (
            f"{self.api_url}"
            f"?keywords={encoded_keywords}"
            f"&fromDateAccepted={from_date}"
            f"&toDateAccepted={to_date}"
            f"&format=json"
            f"&size={self.max_by_page}"
            f"&page={{}}"
        )

        logging.debug(f"OpenAIRE configured URL: {url}")
        return url

    def get_auth_headers(self):
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return None

    def get_offset(self, page):
        """Return the page number (OpenAIRE uses 1-based page numbers).

        Args:
            page: The current page number (1-indexed).

        Returns:
            int: Same page number (OpenAIRE uses page-based pagination).
        """
        return page

    def parsePageResults(self, response, page):
        """Parse a single page of OpenAIRE API results.

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

        # Extract total count from deeply nested response header
        try:
            total_raw = data["response"]["header"]["total"]["$"]
            page_data["total"] = int(total_raw)
        except (KeyError, TypeError, ValueError) as e:
            logging.warning(f"OpenAIRE: Could not extract total count: {e}")
            page_data["total"] = 0

        logging.debug(f"OpenAIRE: Total results for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            try:
                results_raw = data["response"]["results"]["result"]
                # Normalise to list: single result comes back as a dict
                if isinstance(results_raw, dict):
                    results_raw = [results_raw]
                page_data["results"] = results_raw
            except (KeyError, TypeError) as e:
                logging.warning(f"OpenAIRE: Could not extract results: {e}")
                page_data["results"] = []

        return page_data
