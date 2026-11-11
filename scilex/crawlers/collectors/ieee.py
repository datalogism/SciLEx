import logging
import urllib
from datetime import date

from .base import API_collector


class IEEE_collector(API_collector):
    """Collector for fetching publication metadata from the IEEE Xplore API."""

    def __init__(self, filter_param, data_path, api_key):
        """Initializes the IEEE collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "IEEE"
        # Rate limit will be loaded from config or use DEFAULT_RATE_LIMITS (2.0 req/sec)
        self.max_by_page = (
            200  # IEEE API max records per page is 200 (not 25 as previously set)
        )
        # self.api_key = ieee_api
        self.api_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

        # Load rate limit from config after api_name is set
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

        try:
            # Parse the JSON response
            page_with_results = response.json()

            # Extract the total number of records
            total_records = page_with_results.get("total_records", 0)
            page_data["total"] = int(total_records)
            logging.debug(f"Total results found for page {page}: {page_data['total']}")

            # Extract articles
            articles = page_with_results.get("articles", [])
            for article in articles:
                # Collect relevant details from each article
                parsed_article = {
                    "doi": article.get("doi", ""),
                    "title": article.get("title", ""),
                    "publisher": article.get("publisher", ""),
                    "isbn": article.get("isbn", ""),
                    "issn": article.get("issn", ""),
                    "rank": article.get("rank", 0),
                    "authors": [
                        {
                            "full_name": author.get("full_name", ""),
                            "affiliation": author.get("affiliation", ""),
                        }
                        for author in article.get("authors", {}).get("authors", [])
                    ],
                    "access_type": article.get("access_type", ""),
                    "content_type": article.get("content_type", ""),
                    "abstract": article.get("abstract", ""),
                    "article_number": article.get("article_number", ""),
                    "pdf_url": article.get("pdf_url", ""),
                    # Additional metadata fields for better citation formatting
                    "start_page": article.get("start_page", ""),
                    "end_page": article.get("end_page", ""),
                    "publication_date": article.get("publication_date", ""),
                    "publication_title": article.get("publication_title", ""),
                    "volume": article.get("volume", ""),
                    "issue": article.get("issue", ""),
                }
                page_data["results"].append(parsed_article)

        except Exception as e:
            logging.error(f"Error parsing page {page}: {str(e)}")

        return page_data

    def get_configurated_url(self):
        """Constructs the configured API URL with query parameters based on filters.

        Returns:
            str: The formatted API URL with the constructed query parameters.
        """
        # Process keywords: Join multiple keywords with ' AND '
        # keywords_list = self.get_keywords()  # Assuming this returns a list of keyword sets
        query_keywords = (
            "(" + " AND ".join(f'"{kw}"' for kw in self.get_keywords()) + ")"
        )
        encoded_keywords = urllib.parse.quote(query_keywords)

        # Handle year range: Use min and max to set start_year and end_year
        self.get_year()
        # start_year = min(years) if years else None
        # end_year = max(years) if years else None

        # Construct URL with parameters

        return (
            self.get_url()
            + "?apikey="
            + str(self.get_apikey() or "")
            + "&format=json&max_records="
            + str(self.get_max_by_page())
            + "&sort_order=asc&sort_field=article_number&querytext="
            + encoded_keywords
            + "&publication_year="
            + str(self.get_year())
            + "&start_record={}"
        )

    def auth_failure_hints(self):
        return [
            "3. IEEE-specific: Check your API key quota (200 requests/day limit)",
            "4. IEEE-specific: Visit https://developer.ieee.org/ to verify key status",
        ]
