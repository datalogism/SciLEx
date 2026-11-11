import logging
import urllib
from datetime import date

from .base import API_collector


class SemanticScholar_collector(API_collector):
    """
    Collector for fetching publication metadata from the Semantic Scholar API.
    """

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the Semantic Scholar collector with the given parameters.

        Args:
            filter_param (dict): Parameters for filtering results (years, keywords, mode, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "SemanticScholar"
        self.api_url = "https://api.semanticscholar.org/graph/v1/paper/search"

        # Read semantic_scholar_mode from config (default: regular)
        # Options: "regular" (standard endpoint) or "bulk" (bulk endpoint, requires higher-tier access)
        mode = filter_param.get("semantic_scholar_mode", "regular")
        self.use_bulk_api = mode == "bulk"

        # Set max results per page based on endpoint type
        # Bulk endpoint supports up to 1000 results per page (10x more than regular)
        # Regular endpoint limited to 100 results per page
        if self.use_bulk_api:
            self.max_by_page = 1000  # Bulk endpoint: 1000 results per page
            logging.debug(
                "Semantic Scholar BULK mode: Using 1000 results/page (10x faster than regular)"
            )
        else:
            self.max_by_page = 100  # Regular endpoint: 100 results per page
            logging.debug("Semantic Scholar REGULAR mode: Using 100 results/page")

        # Load rate limit from config (defaults to 1 req/sec with API key)
        self.load_rate_limit_from_config()

    def get_auth_headers(self):
        """Semantic Scholar takes the API key in the ``x-api-key`` header (optional)."""
        return {"x-api-key": self.get_apikey()} if self.get_apikey() else None

    def parsePageResults(self, response, page):
        """
        Parses the results from a response for a specific page.

        Args:
            response (requests.Response): The API response object containing the results.
            page (int): The page number of results being processed.

        Returns:
            dict: A dictionary containing metadata about the collected results, including the total count and the results themselves.
        """

        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        try:
            page_with_results = response.json()

            page_data["total"] = int(page_with_results.get("total", 0))

            if page_data["total"] > 0:
                for result in page_with_results.get("data", []):
                    parsed_result = {
                        "title": result.get("title", ""),
                        "abstract": result.get("abstract", ""),
                        "url": result.get("url", ""),
                        "venue": result.get("venue", ""),
                        "publicationVenue": result.get(
                            "publicationVenue", None
                        ),  # FIX: Extract publicationVenue
                        "publicationTypes": result.get(
                            "publicationTypes", []
                        ),  # FIX: Extract publicationTypes
                        "journal": result.get(
                            "journal", None
                        ),  # FIX: Extract journal metadata
                        "citationCount": result.get("citationCount", 0),
                        "referenceCount": result.get("referenceCount", 0),
                        "authors": [
                            {
                                "name": author.get("name", ""),
                                "affiliation": author.get("affiliation", ""),
                            }
                            for author in result.get("authors", [])
                        ],
                        "fields_of_study": result.get("fieldsOfStudy", []),
                        "publication_date": result.get("publicationDate", ""),
                        "open_access_pdf": result.get("openAccessPdf", {}).get(
                            "url", ""
                        ),
                        "DOI": result.get("externalIds", {}).get("DOI", ""),
                        "paper_id": result.get(
                            "paperId", ""
                        ),  # FIX: Extract paperId for archiveID
                    }
                    page_data["results"].append(parsed_result)

            logging.debug(
                f"Page {page} parsed successfully with {len(page_data['results'])} results."
            )
        except Exception as e:
            logging.error(
                f"Error parsing page {page}: {str(e)}. Response content: {response.text}"
            )

        return page_data

    def _date_param(self):
        """Year filter, narrowed to ``since`` (publicationDateOrYear) when set."""
        year = self.get_year()
        start_date = self.get_query_start_date()
        if start_date:
            return f"publicationDateOrYear={start_date.isoformat()}:{year}-12-31"
        return f"year={year}"

    def get_configurated_url(self):
        """
        Constructs the configured API URL with query parameters.

        Returns:
            str: The formatted API URL with the constructed query parameters.
                 Uses either regular or bulk endpoint based on semantic_scholar_mode config.
        """
        # Process keywords: Join multiple keywords with '+' (AND operator)
        # Wrap each keyword in quotes to preserve multi-word phrases
        query_keywords = "+".join(
            f'"{kw}"' for kw in self.get_keywords()
        )  # Use + for AND logic between keyword groups

        encoded_keywords = urllib.parse.quote(query_keywords)

        # Define fixed fields
        fields = "title,abstract,url,venue,publicationVenue,citationCount,externalIds,referenceCount,s2FieldsOfStudy,publicationTypes,publicationDate,isOpenAccess,openAccessPdf,authors,journal,fieldsOfStudy"

        # Choose endpoint based on config: regular (default) or bulk
        if self.use_bulk_api:
            base_url = f"{self.api_url}/bulk"
            logging.debug(
                "Using Semantic Scholar BULK endpoint (requires higher-tier access)"
            )
        else:
            base_url = self.api_url
            logging.debug("Using Semantic Scholar REGULAR endpoint (standard access)")

        # Construct the full URL with pagination parameters
        url = (
            f"{base_url}?query={encoded_keywords}"
            f"&{self._date_param()}"
            f"&fields={fields}"
            f"&limit={self.max_by_page}&offset={{}}"  # Add pagination: limit=100, offset placeholder
        )

        logging.debug(f"Constructed API URL: {url}")
        return url
