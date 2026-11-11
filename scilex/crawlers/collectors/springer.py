import logging
from datetime import date

from .base import API_collector


class Springer_collector(API_collector):
    """Store file metadata from Springer API."""

    def __init__(self, filter_param, data_path, api_key):
        """
        Initialize the Springer Collector.

        Args:
            filter_param (dict): The filter parameters for the search query.
            data_path (str): Path to save the data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "Springer"
        self.max_by_page = 100
        #     self.api_key = springer_api
        ## manage both meta and openaccess endpoints
        if isinstance(self.api_key, dict):
            self.meta_api_key = self.api_key.get("meta_api_key")
            self.openaccess_api_key = self.api_key.get("openaccess_api_key")
        else:
            self.meta_api_key = self.api_key
            self.openaccess_api_key = self.api_key

        # Define both API URLs
        self.meta_url = "http://api.springernature.com/meta/v2/json"
        self.openaccess_url = "http://api.springernature.com/openaccess/json"

        # Load rate limit from config (defaults to 1.5 req/sec for Basic tier)
        self.load_rate_limit_from_config()

    def parsePageResults(self, response, page):
        """
        Parses the JSON response from the API for a specific page of results.

        Args:
            response (requests.Response): The response object from the API call.
            page (int): The current page number being processed.

        Returns:
            dict: A dictionary containing metadata about the search, including
                the date of search, collection ID, current page, total results,
                and the parsed results.
        """
        # Initialize the dictionary to hold the parsed page data
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        try:
            # Parse the JSON response from the API
            page_with_results = response.json()

            # Extract the 'records' list and the 'result' which contains metadata
            records = page_with_results.get("records", [])
            result_info = page_with_results.get("result", [])

            # Handle 'result' being a list and extract the first entry's 'total' if available
            if isinstance(result_info, list) and len(result_info) > 0:
                total = result_info[0].get("total", 0)
            else:
                total = 0

            page_data["total"] = int(total)

            # Process the 'records' if they exist and are in the correct format
            if isinstance(records, list) and len(records) > 0:
                for result in records:
                    page_data["results"].append(result)
            else:
                logging.warning(
                    f"No valid records found on page {page}. Records type: {type(records)}. Response: {page_with_results}"
                )

        except Exception as e:
            # Log detailed error information
            logging.error(
                f"Error parsing page {page}. Response content: {response.text}. Error: {str(e)}"
            )
            raise

        return page_data

    def construct_search_query(self):
        """
        Constructs a search query for the Springer API from the keyword sets.
        The format will be:
        (title:"keyword1" OR title:"keyword2") AND (title:"keyword3" OR title:"keyword4")
        """
        # formatted_keyword_groups = []

        # Iterate through each set of keywords
        # for keyword_set in self.get_keywords():
        # Join keywords within the same set with ' OR ' and format for title
        #   group_keywords = ' OR '.join([f'"{keyword}"' for keyword in keyword_set])
        #  formatted_keyword_groups.append(f"({group_keywords})")

        # Join all formatted keyword groups with ' AND '
        search_query = " AND ".join([f'"{keyword}"' for keyword in self.get_keywords()])
        return search_query

    def _build_url(self, base_url, api_key):
        """Search URL for one endpoint; ``{}`` is the 1-based record start (``s``)."""
        keywords_query = self.construct_search_query()
        return f"{base_url}?q={keywords_query}&api_key={api_key}&p={self.max_by_page}&s={{}}"

    def get_configurated_url(self):
        """URL template of the meta endpoint (see ``_get_api_endpoints`` for both)."""
        return self._build_url(self.meta_url, self.meta_api_key)

    def _get_api_endpoints(self):
        """Both Springer endpoints: metadata and open access."""
        urls = [
            self.get_configurated_url(),
            self._build_url(self.openaccess_url, self.openaccess_api_key),
        ]
        logging.debug(
            f"Springer endpoints: {[self._sanitize_url(url) for url in urls]}"
        )
        return urls

    def get_offset(self, page):
        """Springer's ``s`` parameter is a 1-based record position."""
        return (page - 1) * self.max_by_page + 1

    def auth_failure_hints(self):
        return [
            "3. Springer-specific: Check your subscription tier and rate limits",
        ]
