import logging
from datetime import date

from .base import API_collector


class Istex_collector(API_collector):
    """Collector for fetching publication metadata from the Istex API."""

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.max_by_page = 500  # Maximum number of results to retrieve per page
        self.api_name = "Istex"
        self.api_url = "https://api.istex.fr/document/"
        self.load_rate_limit_from_config()

    def parsePageResults(self, response, page):
        """Parses the results from a response for a specific page.

        Args:
            response (requests.Response): The API response object containing the results.
            page (int): The page number of results being processed.

        Returns:
            dict: A dictionary containing metadata about the collected results, including the total count and the results themselves.
        """
        page_data = {
            "date_search": str(date.today()),  # Date of the search
            "id_collect": self.get_collectId(),  # Unique identifier for this collection
            "page": page,  # Current page number
            "total": 0,  # Total number of results found
            "results": [],  # List to hold the collected results
        }

        # Parse the JSON response
        page_with_results = response.json()

        # Extract total number of hits
        total = page_with_results.get("total", 0)
        page_data["total"] = int(total)
        logging.debug(f"Total results found for page {page}: {page_data['total']}")

        # Loop through the hits and append them to the results list
        for result in page_with_results.get("hits", []):
            page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """Constructs the API URL with the search query and filters.

        Returns:
            str: The formatted API URL with {} placeholder for pagination offset.
        """
        import urllib.parse

        # Get year range and construct ISTEX date filter
        years = self.get_year()
        if isinstance(years, int):
            # Single year for this query
            year_filter = str(years)
        elif isinstance(years, list) and len(years) > 0:
            # Year range
            year_min = min(years)
            year_max = max(years)
            year_filter = f"[{year_min} TO {year_max}]"
        else:
            # No year filter
            year_filter = "*"

        # Get keywords and flatten nested lists
        keywords = self.get_keywords()
        flat_keywords = [
            keyword
            for sublist in keywords
            for keyword in (sublist if isinstance(sublist, list) else [sublist])
        ]

        # Quote keywords for phrase matching and join with OR
        quoted_keywords = [f'"{kw}"' for kw in flat_keywords]
        keyword_query = " OR ".join(quoted_keywords)

        # Construct Lucene query
        query = (
            f"publicationDate:{year_filter} AND "
            f"(title:({keyword_query}) OR abstract:({keyword_query}))"
        )

        # URL-encode the query while preserving Lucene syntax characters
        encoded_query = urllib.parse.quote(query, safe=':[]() "')

        # Construct final URL
        configured_url = f"{self.api_url}?q={encoded_query}&output=*&size={self.max_by_page}&from={{}}"

        logging.debug(f"ISTEX query: {query}")
        logging.debug(f"ISTEX URL: {configured_url}")

        return configured_url
