import logging
import urllib
from datetime import date

from lxml import etree

from .base import API_collector


class Arxiv_collector(API_collector):
    """Collector for fetching publication metadata from the Arxiv API.

    This class constructs search queries based on title and abstract keywords
    and processes the results from the Arxiv API.
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.max_by_page = 500  # Maximum results per page
        self.api_name = "Arxiv"
        self.api_url = "https://export.arxiv.org/api/query"
        self.load_rate_limit_from_config()

    def parsePageResults(self, response, page):
        """Parses the results from a response and organizes it into a structured format."""
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        # Parse the XML response content
        page_with_results = response.content
        tree = etree.fromstring(page_with_results)

        # Extract entries from the XML tree
        entries = tree.xpath('*[local-name()="entry"]')
        years_query = str(self.get_year())
        # Process each entry — use 'updated' (current version date) to match
        # the submittedDate filter in the URL, not 'published' (original date).
        for entry in entries:
            date_updated = entry.xpath('*[local-name()="updated"]')[0].text
            if years_query in date_updated:
                ### ADD IT TO KEEP ONLY GOOD DATE art

                current = {
                    "id": entry.xpath('*[local-name()="id"]')[0].text,
                    "updated": date_updated,
                    "published": entry.xpath('*[local-name()="published"]')[0].text,
                    "title": entry.xpath('*[local-name()="title"]')[0].text,
                    "abstract": entry.xpath('*[local-name()="summary"]')[0].text,
                    "authors": self.extract_authors(
                        entry
                    ),  # Extract authors separately
                    "doi": self.extract_doi(entry),  # Extract DOI separately
                    "pdf": self.extract_pdf(entry),  # Extract PDF link
                    "journal": self.extract_journal(entry),  # Extract journal reference
                    "categories": self.extract_categories(entry),  # Extract categories
                }
                page_data["results"].append(current)
            else:
                page_data["results"].append(None)

        # Get the total number of results from the response
        total_raw = tree.xpath('*[local-name()="totalResults"]')
        page_data["total"] = int(total_raw[0].text) if total_raw else 0

        logging.debug(f"Parsed {len(page_data['results'])} results from page {page}.")
        return page_data

    def _post_process_page(self, page_data):
        """Drop entries outside the requested year (parsed as ``None``)."""
        page_data["results"] = [x for x in page_data["results"] if x is not None]
        return page_data

    def extract_authors(self, entry):
        """Extracts authors from the entry and returns a list."""
        authors = entry.xpath('*[local-name()="author"]')
        return [auth.xpath('*[local-name()="name"]')[0].text for auth in authors]

    def extract_doi(self, entry):
        """Extracts the DOI from the entry."""
        try:
            return entry.xpath('*[local-name()="doi"]')[0].text
        except IndexError:
            return ""

    def extract_pdf(self, entry):
        """Extracts the PDF link from the entry."""
        try:
            return entry.xpath('*[local-name()="link" and @title="pdf"]')[0].text
        except IndexError:
            return ""

    def extract_journal(self, entry):
        """Extracts the journal reference from the entry."""
        try:
            return entry.xpath('*[local-name()="journal_ref"]')[0].text
        except IndexError:
            return ""

    def extract_categories(self, entry):
        """Extracts categories from the entry."""
        categories = entry.xpath('*[local-name()="category"]')
        return [cat.attrib["term"] for cat in categories]

    def construct_search_query(self):
        """Constructs a search query for the API from the keyword sets.
        The format will be:
        ti:"NLP" OR ti:"Natural Language Processing" OR abs:"NLP" OR abs:"Natural Language Processing"
        AND
        ti:"Pragmatic" OR ti:"Pragmatics" OR abs:"Pragmatic" OR abs:"Pragmatics"
        """
        # List to hold formatted keyword groups
        formatted_keyword_groups = []

        # Iterate through each set of keywords
        for keyword in self.get_keywords():
            # Initialize a list to hold the formatted keywords for the current group
            group_keywords = []

            # Add 'ti' (title) and 'abs' (abstract) queries for each keyword
            group_keywords += [f"ti:%22{urllib.parse.quote(keyword)}%22"]
            group_keywords += [f"abs:%22{urllib.parse.quote(keyword)}%22"]

            formatted_keyword_groups.append(f"({'+OR+'.join(group_keywords)})")

        years_query = str(self.get_year())
        start_date = self.get_query_start_date()
        range_start = (
            start_date.strftime("%Y%m%d") if start_date else years_query + "0101"
        )
        year_arg = (
            "submittedDate:%5B" + range_start + "0000+TO+" + years_query + "12312359%5D"
        )
        # Join keyword groups and year filter all within search_query (Arxiv API requirement)
        search_query = "+AND+".join(formatted_keyword_groups) + "+AND+" + year_arg
        logging.debug(f"Constructed search query: {search_query}")
        return search_query

    def get_configurated_url(self):
        """Constructs the API URL with the search query and date filters."""
        search_query = self.construct_search_query()  # Use the constructed search query

        logging.debug(
            f"Configured URL: {self.api_url}?search_query={search_query}&sortBy=relevance&sortOrder=descending&start={{}}&max_results={self.max_by_page}"
        )
        return f"{self.api_url}?search_query={search_query}&sortBy=relevance&sortOrder=descending&start={{}}&max_results={self.max_by_page}"
