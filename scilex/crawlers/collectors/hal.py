import logging
import urllib.parse
from datetime import date

from .base import API_collector


class HAL_collector(API_collector):
    """Collector for fetching publication metadata from the HAL API."""

    def __init__(self, filter_param, data_path, api_key):
        """Initializes the HAL collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.max_by_page = 500  # Maximum number of results to retrieve per page
        self.api_name = "HAL"
        self.api_url = "http://api.archives-ouvertes.fr/search/"
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
        results = page_with_results["response"]
        total = results["numFound"]
        page_data["total"] = int(total)
        logging.debug(f"Total results found for page {page}: {page_data['total']}")

        if total > 0:
            # Loop through the documents and append them to the results list
            for result in results["docs"]:
                page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """Constructs the API URL with the search query and filters based on the year and pagination.

        Returns:
            str: The formatted API URL for the request.
        """
        # HAL is Solr: the year goes in a filter query (``fq``); a bare
        # ``&submittedDateY_i:[...]`` parameter is silently ignored.
        year_filter = f"fq=submittedDateY_i:{self.get_year()}"

        flat_keywords = [
            keyword
            for sublist in self.get_keywords()
            for keyword in (sublist if isinstance(sublist, list) else [sublist])
        ]
        # Quote each keyword so multi-word terms match as phrases, AND between them.
        keyword_query = " AND ".join(f'"{keyword}"' for keyword in flat_keywords)
        keyword_query = urllib.parse.quote(f"({keyword_query})", safe="")

        # Construct the final URL with all available fields
        # Added: volume_s, issue_s, page_s, publisher_s, language_s for better metadata extraction
        fields = (
            "title_s,abstract_s,label_s,arxivId_s,audience_s,authFullNameIdHal_fs,"
            "bookTitle_s,classification_s,conferenceTitle_s,docType_s,doiId_id,"
            "files_s,halId_s,jel_t,journalDoiRoot_s,journalTitle_t,keyword_s,"
            "type_s,submittedDateY_i,volume_s,issue_s,page_s,publisher_s,language_s"
        )
        configured_url = (
            f"{self.api_url}?q={keyword_query}&fl={fields}&"
            f"{year_filter}&wt=json&rows={self.max_by_page}&start={{}}"
        )

        logging.debug(f"Configured URL: {configured_url}")
        return configured_url
