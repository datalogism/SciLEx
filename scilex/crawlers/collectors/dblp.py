import logging
from datetime import date

from .base import API_collector


class DBLP_collector(API_collector):
    """Class to collect publication data from the DBLP API."""

    def __init__(self, filter_param, data_path, api_key):
        """Initializes the DBLP collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.max_by_page = 1000  # Maximum number of results to retrieve per page
        self.api_name = "DBLP"
        self.api_url = "https://dblp.org/search/publ/api"
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

        # Extract the total number of hits from the results
        results = page_with_results["result"]
        total = results["hits"]["@total"]
        page_data["total"] = int(total)
        logging.debug(f"Total results found for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            # Loop through the hits and append them to the results list

            for result in results["hits"]["hit"]:
                page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """Constructs the configured API URL based on keywords and years.

        Returns:
            str: The formatted API URL with the constructed query parameters.
        """
        # Process keywords: Use hyphens for multi-word phrases, '+' for AND between keywords
        # DBLP uses hyphen (-) to enforce adjacency for phrase matching
        keywords = self.get_keywords()
        keywords_list = []
        for keyword in keywords:
            # Replace spaces with hyphens to keep multi-word phrases together
            # e.g., "knowledge graph" becomes "knowledge-graph"
            phrase = keyword.replace(" ", "-")
            keywords_list.append(phrase)

        # Join with '+' for AND logic (no leading '+')
        keywords_query = "+".join(keywords_list)

        #### OR CONFIG (deprecated)
        # keywords_query ='|'.join(self.get_keywords())

        years_query = str(self.get_year())
        # Combine keywords and years into the query string (fixed trailing colon)
        query = f"{keywords_query} year:{years_query}"
        logging.debug(f"Constructed query for API: {query}")

        # Return the final API URL
        return f"{self.api_url}?q={query}&format=json&h={self.max_by_page}&f={{}}"
