import json
import logging
import os
import urllib
from datetime import date

import requests
from lxml import etree
from ratelimit import limits, sleep_and_retry

# # Set up logging configuration
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     datefmt='%Y-%m-%d %H:%M:%S'
# )


class Filter_param:
    def __init__(self, year, keywords):
        # Initialize the parameters
        self.year = year
        # Keywords is now a list of lists to support multiple sets
        self.keywords = keywords
        # self.focus = focus

    def get_dict_param(self):
        # Return the instance's dictionary representation
        return self.__dict__

    def get_year(self):
        return self.year

    def get_keywords(self):
        return self.keywords

    def get_focus(self):
        return self.focus


class API_collector:
    def __init__(self, data_query, data_path, api_key):
        # In second
        self.api_key = api_key
        self.api_name = "None"
        self.filter_param = Filter_param(data_query["year"], data_query["keyword"])
        self.rate_limit = 10
        self.datadir = data_path
        self.collectId = data_query["id_collect"]
        self.total_art = int(data_query["total_art"])
        self.lastpage = int(data_query["last_page"])
        self.nb_art_collected = int(data_query["coll_art"])
        self.big_collect = 0
        self.max_by_page = 100
        self.api_url = ""
        self.state = data_query["state"]

    def set_lastpage(self, lastpage):
        self.lastpage = lastpage

    def createCollectDir(self):
        if not os.path.isdir(self.get_apiDir()):
            os.makedirs(self.get_apiDir())
        if not os.path.isdir(self.get_collectDir()):
            os.makedirs(self.get_collectDir())

    def get_collectId(self):
        return self.collectId

    def set_collectId(self, collectId):
        self.collectId = collectId

    def createCollectDir(self):
        if not os.path.isdir(self.get_apiDir()):
            os.makedirs(self.get_apiDir())
        if not os.path.isdir(self.get_collectDir()):
            os.makedirs(self.get_collectDir())

    def get_collectDir(self):
        return self.get_apiDir() + "/" + str(self.get_collectId())

    def set_state(self, complete):
        self.state = complete

    def savePageResults(self, global_data, page):
        self.createCollectDir()
        print(self.get_collectDir() + "/page_" + str(page))
        with open(
            self.get_collectDir() + "/page_" + str(page), "w", encoding="utf8"
        ) as json_file:
            json.dump(global_data, json_file)

    def get_lastpage(self):
        return self.lastpage

    def get_api_name(self):
        return self.api_name

    def get_keywords(self):
        return self.filter_param.get_keywords()

    def get_year(self):
        return self.filter_param.get_year()

    def get_dataDir(self):
        return self.datadir

    def get_apiDir(self):
        return self.get_dataDir() + "/" + self.get_api_name()

    def get_collectDir(self):
        return self.get_apiDir() + "/" + str(self.get_collectId())

    def get_fileCollect(self):
        return self.get_dataDir() + "/collect_dict.json"

    def get_url(self):
        return self.api_url

    def get_apikey(self):
        return self.api_key

    def get_max_by_page(self):
        return self.max_by_page

    def get_ratelimit(self):
        return self.rate_limit

    def api_call_decorator(self, configurated_url):
        print("REQUEST")

        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            try:
                resp = requests.get(configurated_url)
            except:
                print("PB AFTER REQUEST")
            return resp

        return access_rate_limited_decorated(configurated_url)

    def toZotero():
        pass

    def get_lastpage(self):
        return self.lastpage

    def runCollect(self):
        """
        Runs the collection process for DBLP and Springer publications.

        This method retrieves publication data in pages until all results
        are collected or a specified limit is reached.
        """

        state_data = {
            "state": self.state,
            "last_page": self.lastpage,
            "total_art": self.total_art,
            "coll_art": self.nb_art_collected,
            "update_date": str(date.today()),
            "id_collect": self.collectId,
        }
        # self.getCollectId()  # Retrieve the collection identifier

        # Check if the collection has already been completed
        if self.state == 1:
            logging.info("Collection already completed.")
            return  # Exit if collection is complete

        page = int(self.get_lastpage()) + 1  # Start from the next page
        has_more_pages = True
        print("<<<<<<<<<<<<<", page)

        # Determine if there are fewer than 10,000 results based on collection size
        fewer_than_10k_results = self.big_collect == 0

        if isinstance(self, Springer_collector):
            # If this is a Springer collector, use the 'collect_from_endpoints' method
            logging.info("Running collection for Springer data.")

            try:
                combined_results = (
                    self.collect_from_endpoints()
                )  # Collect results from Springer endpoints

                for page_data in combined_results:
                    # Save each page's results

                    self.savePageResults(page_data, page)

                    # Update the last page collected
                    self.set_lastpage(int(page) + 1)

                    # Check if more pages are available based on results
                    has_more_pages = len(page_data["results"]) == self.get_max_by_page()
                    page = self.get_lastpage()  # Update the current page number

                    # Check if total results are within the limit
                    fewer_than_10k_results = page_data["total"] <= 10000
                    logging.info(
                        f"Processed page {page}: {len(page_data['results'])} results. Total found: {page_data['total']}"
                    )

            except Exception as e:
                # Log additional context about the error
                logging.error(
                    f"Error processing results on page {page} from Springer API: {str(e)}"
                )
                has_more_pages = False  # Stop collecting if there's an error

        else:
            # If this is a DBLP collector, follow the normal process
            print("NOT SPRINGER<<<<<<<<<<<<<")
            print("more pages ?", has_more_pages)
            print("fewer_than_10k_results ? ", fewer_than_10k_results)
            while has_more_pages and fewer_than_10k_results:
                print("NEW PAGE")
                offset = self.get_offset(page)  # Calculate the current offset
                print("url before")
                print(offset)
                url = self.get_configurated_url().format(
                    offset
                )  # Construct the API URL
                print("url after")

                logging.info(f"Fetching data from URL: {url}")

                response = self.api_call_decorator(url)  # Call the API
                print("CALL")
                try:
                    page_data = self.parsePageResults(
                        response, page
                    )  # Parse the response

                    self.nb_art_collected += int(len(page_data["results"]))
                    nb_res = len(page_data["results"])
                    print("---------")
                    print(nb_res)
                    print(nb_res == 0)
                    print("---------")
                    # Determine if more pages are available based on results returned
                    if nb_res != 0:
                        has_more_pages = nb_res == self.get_max_by_page()
                    else:
                        has_more_pages = False
                    print("has_more_pages>", has_more_pages)
                    if isinstance(self, Arxiv_collector):
                        page_data["results"] = [
                            x for x in page_data["results"] if x is not None
                        ]

                    print("NB ART COLLECTED >", self.nb_art_collected)
                    # Save the page results for future use
                    self.savePageResults(page_data, page)
                    # Update the last page collected
                    self.set_lastpage(int(page) + 1)

                    # print("MAX ART >", self.get_max_by_page())
                    page = self.get_lastpage()  # Update the current page number

                    state_data["last_page"] = page
                    state_data["total_art"] = page_data["total"]
                    state_data["coll_art"] = state_data["coll_art"] + len(
                        page_data["results"]
                    )

                    # Check if the total number of results is within the limit
                    # fewer_than_10k_results = page_data["total"] <= 10000

                    logging.info(
                        f"Processed page {page}: {len(page_data['results'])} results. Total found: {page_data['total']}"
                    )

                except Exception as e:
                    # Log additional context about the error
                    logging.error(
                        f"Error processing results on page {page} from URL '{url}': {str(e)}. "
                        f"Response type: {type(response)}."
                    )
                    has_more_pages = False  # Stop collecting if there's an error
                    state_data["state"] = 0
                    state_data["last_page"] = page
                    return state_data

        # Final log messages based on the collection status

        if not has_more_pages:
            logging.info("No more pages to collect. Marking collection as complete.")
            # self.flagAsComplete()
            state_data["state"] = 1
        else:
            time_needed = page_data["total"] / self.get_max_by_page() / 60 / 60
            logging.info(
                f"Total extraction will need approximately {time_needed:.2f} hours."
            )

        return state_data

    def add_offset_param(self, page):
        return self.get_configurated_url().format((page - 1) * self.get_max_by_page())

    def get_offset(self, page):
        return (page - 1) * self.get_max_by_page()


class SemanticScholar_collector(API_collector):
    """
    Collector for fetching publication metadata from the Semantic Scholar API.
    """

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the Semantic Scholar collector with the given parameters.

        Args:
            filter_param (Filter_param): Parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 100  # API allows 100 requests per minute
        self.max_by_page = 100  # Maximum number of results per page
        self.api_name = "SemanticScholar"
        self.api_url = "https://api.semanticscholar.org/graph/v1/paper/search"

    def api_call_decorator(self, configurated_url):
        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            resp = requests.get(
                configurated_url, headers={"x-api-key": self.get_apikey()}
            )
            return resp

        return access_rate_limited_decorated(configurated_url)

    def parsePageResults(self, response, page):
        """
        Parses the results from a response for a specific page.

        Args:
            response (requests.Response): The API response object containing the results.
            page (int): The page number of results being processed.

        Returns:
            dict: A dictionary containing metadata about the collected results, including the total count and the results themselves.
        """
        print("Parse")
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        try:
            print("BFEFORE")
            page_with_results = response.json()
            print(page_with_results)
            page_data["total"] = int(page_with_results.get("total", 0))
            print(page_data["total"])
            if page_data["total"] > 0:
                for result in page_with_results.get("data", []):
                    parsed_result = {
                        "title": result.get("title", ""),
                        "abstract": result.get("abstract", ""),
                        "url": result.get("url", ""),
                        "venue": result.get("venue", ""),
                        "citation_count": result.get("citationCount", 0),
                        "reference_count": result.get("referenceCount", 0),
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
                    }
                    page_data["results"].append(parsed_result)

            logging.info(
                f"Page {page} parsed successfully with {len(page_data['results'])} results."
            )
        except Exception as e:
            logging.error(
                f"Error parsing page {page}: {str(e)}. Response content: {response.text}"
            )

        return page_data

    def get_configurated_url(self):
        """
        Constructs the configured API URL with query parameters for the bulk API.

        Returns:
            str: The formatted API URL for the bulk API with the constructed query parameters.
        """
        # Process keywords: Join multiple keywords with ' AND '
        print(">>>>>>>>>>>>>>>>>>>")
        print("KEYWORD")
        print(self.get_keywords())
        query_keywords = "|".join(
            self.get_keywords()
        )  # Assuming this returns a list of keyword sets

        # query_keywords = '|'.join(f'"{keyword})"' for keyword in keywords) for keywords in keywords_list
        # )
        encoded_keywords = urllib.parse.quote(query_keywords)

        # Handle year range: Use min and max to set the range
        #  years = self.get_year()
        # start_year = min(years) if years else None
        # end_year = max(years) if years else None
        # year_range = f"{start_year}-{end_year}" if start_year and end_year else ""

        # Define fixed fields and construct the URL
        fields = "title,abstract,url,venue,publicationVenue,citationCount,externalIds,referenceCount,s2FieldsOfStudy,publicationTypes,publicationDate,isOpenAccess,openAccessPdf,authors,journal,fieldsOfStudy"
        base_url = f"{self.api_url}/bulk"

        # Construct the full URL
        url = (
            f"{base_url}?query={encoded_keywords}"
            f"&year={self.get_year()}"
            f"&fieldsOfStudy=Computer%20Science"
            f"&fields={fields}"
        )

        logging.info(f"Constructed API URL: {url}")
        return url


class IEEE_collector(API_collector):
    """
    Collector for fetching publication metadata from the IEEE Xplore API.
    """

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the IEEE collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "IEEE"
        self.rate_limit = 200
        self.max_by_page = 25  # IEEE API max records per page is 25
        # self.api_key = ieee_api
        self.api_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

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
            logging.info(f"Total results found for page {page}: {page_data['total']}")

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
                            "name": author.get("full_name", ""),
                            "affiliation": author.get("affiliation", ""),
                        }
                        for author in article.get("authors", {}).get("authors", [])
                    ],
                    "access_type": article.get("access_type", ""),
                    "content_type": article.get("content_type", ""),
                    "abstract": article.get("abstract", ""),
                    "article_number": article.get("article_number", ""),
                    "pdf_url": article.get("pdf_url", ""),
                }
                page_data["results"].append(parsed_article)

        except Exception as e:
            logging.error(f"Error parsing page {page}: {str(e)}")

        return page_data

    def get_configurated_url(self):
        """
        Constructs the configured API URL with query parameters based on filters.

        Returns:
            str: The formatted API URL with the constructed query parameters.
        """
        # Process keywords: Join multiple keywords with ' AND '
        # keywords_list = self.get_keywords()  # Assuming this returns a list of keyword sets
        query_keywords = f"({' AND '.join(self.get_keywords())})"
        encoded_keywords = urllib.parse.quote(query_keywords)

        # Handle year range: Use min and max to set start_year and end_year
        self.get_year()
        # start_year = min(years) if years else None
        # end_year = max(years) if years else None

        # Construct URL with parameters

        return (
            self.get_url()
            + "?apikey="
            + self.get_apikey()
            + "&format=json&max_records="
            + str(self.get_max_by_page())
            + "&sort_order=asc&sort_field=article_number&querytext="
            + encoded_keywords
            + "&publication_year="
            + str(self.get_year())
            + "&start_record={}"
        )

    #   fields = (
    #      "title"
    # )
    # url = (
    #   f"{self.api_url}?query={encoded_keywords}"
    #   f"&fieldsOfStudy=Computer Science"
    #   f"&fields={fields}"
    #   f"&limit={self.max_by_page}&offset={offset_placeholder}"
    #   f"&year={self.get_year()}"
    # )

    # Append year range to the query if available
    # if start_year and end_year:
    #    url += f"&year={start_year}-{end_year}"

    # logging.info(f"Constructed API URL: {url}")
    # return url


class Elsevier_collector(API_collector):
    """Store file metadata from Elsevier API."""

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 8
        self.max_by_page = 100
        self.api_name = "Elsevier"
        self.api_url = "https://api.elsevier.com/content/search/scopus"

    def parsePageResults(self, response, page):
        print("parsePageResults")
        """Parse the JSON response from Elsevier API and return structured data."""
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        page_with_results = response.json()
        print(page_with_results)
        # Loop through partial list of results
        results = page_with_results["search-results"]
        total = results["opensearch:totalResults"]
        page_data["total_nb"] = int(total)
        if page_data["total_nb"] > 0:
            for result in results["entry"]:
                page_data["results"].append(result)

        return page_data

    def construct_search_query(self):
        print("construct_search_query")
        """
        Constructs a search query for the API from the keyword sets.
        The format will be:
        TITLE(NLP OR Natural Language Processing) AND TITLE(Pragmatic OR Pragmatics)
        """
        # formatted_keyword_groups = []

        # Iterate through each set of keywords
        # for keyword_set in self.get_keywords():
        # Initialize a list to hold the formatted keywords for the current group
        #  group_keywords = []

        # Join keywords within the same set with ' OR '
        # group_keywords += [f'"{keyword}"' for keyword in keyword_set]  # Use quotes for exact matching

        # Join the current group's keywords with ' OR ' and wrap in TITLE()

        search_query = f"TITLE-ABS({' AND '.join(self.get_keywords())})"

        # Join all formatted keyword groups with ' AND '
        # search_query = ' AND '.join(formatted_keyword_groups)
        print("end construct query")
        print(search_query)
        return search_query

    def get_configurated_url(self):
        print("get_configurated_url")
        """Constructs the API URL with the search query and publication year filters."""
        # Construct the search query
        keywords_query = (
            self.construct_search_query()
        )  # Get the formatted keyword query

        # Create the years query
        years_query = self.get_year()
        # Combine the queries
        query = f"{keywords_query}&date={years_query}"

        return f"{self.api_url}?query={query}&apiKey={self.api_key}&count={self.max_by_page}&start={{}}"


class DBLP_collector(API_collector):
    """Class to collect publication data from the DBLP API."""

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the DBLP collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 10  # Number of requests allowed per second
        self.max_by_page = 1000  # Maximum number of results to retrieve per page
        self.api_name = "DBLP"
        self.api_url = "https://dblp.org/search/publ/api"

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
            "date_search": str(date.today()),  # Date of the search
            "id_collect": self.get_collectId(),  # Unique identifier for this collection
            "page": page,  # Current page number
            "total": 0,  # Total number of results found
            "results": [],  # List to hold the collected results
        }
        print("INSIDE")
        # Parse the JSON response
        page_with_results = response.json()

        print("AFTER")
        # Extract the total number of hits from the results
        results = page_with_results["result"]
        total = results["hits"]["@total"]
        page_data["total"] = int(total)
        logging.info(f"Total results found for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            # Loop through the hits and append them to the results list
            print("TOTAL")
            print(results["hits"].keys())
            for result in results["hits"]["hit"]:
                page_data["results"].append(result)
            print("OK")

        return page_data

    def get_configurated_url(self):
        """
        Constructs the configured API URL based on keywords and years.

        Returns:
            str: The formatted API URL with the constructed query parameters.
        """
        # Process keywords: Join items in each list with '|', then join the lists with ' '
        keywords = self.get_keywords()
        keywords_query = ""
        for keyword in keywords:
            keywords_query = keywords_query + "+" + "+".join(keyword.split(" "))

        #### OR CONFIG
        # keywords_query ='|'.join(self.get_keywords())

        years_query = str(self.get_year())
        # Combine keywords and years into the query string
        query = f"{keywords_query} year:{years_query}:"
        logging.info(f"Constructed query for API: {query}")

        # Return the final API URL
        return f"{self.api_url}?q={query}&format=json&h={self.max_by_page}&f={{}}"


class OpenAlex_collector(API_collector):
    """Class to collect publication data from the OpenAlex API."""

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the OpenAlex collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 10  # Number of requests allowed per second
        self.max_by_page = 200  # Maximum number of results to retrieve per page
        self.api_name = "OpenAlex"
        self.api_url = "https://api.openalex.org/works"

    # self.openalex_mail = openalex_mail  # Add your email for the OpenAlex API requests

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
            "date_search": str(date.today()),  # Date of the search
            "id_collect": self.get_collectId(),  # Unique identifier for this collection
            "page": page,  # Current page number
            "total": 0,  # Total number of results found
            "results": [],  # List to hold the collected results
        }

        # Parse the JSON response
        page_with_results = response.json()

        # Extract the total number of hits from the results
        total = page_with_results.get("meta", {}).get("count", 0)
        page_data["total"] = int(total)
        logging.info(f"Total results found for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            # Loop through the hits and append them to the results list
            for result in page_with_results.get("results", []):
                page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """
        Constructs the API URL with the search query and filters based on the year and pagination.

        Returns:
            str: The formatted API URL for the request.
        """
        keyword_filters = []

        # Iterate through each set of keywords and format them for title and abstract search
        for keyword_set in self.get_keywords():
            keyword_filters += [f"abstract.search:{keyword_set}"]
            keyword_filters += [f"title.search:{keyword_set}"]

        # Join all keyword filters with commas (as per OpenAlex API format)
        formatted_keyword_filters = ",".join(keyword_filters)

        # Extract the min and max year from self.get_year() and create the range
        years = self.get_year()  # Assuming this returns a list of years
        # min_year = min(years)
        # max_year = max(years)
        year_filter = f"publication_year:{years}"

        # Combine all filters into the final URL
        api_url = (
            f"{self.api_url}?filter={formatted_keyword_filters},{year_filter}"
            f"&per-page={self.max_by_page}&mailto={self.api_key}&page={{}}"
        )

        logging.info(f"Configured URL: {api_url}")
        return api_url

    def get_offset(self, page):
        """
        Returns the page number for OpenAlex pagination.

        Args:
            page (int): The current page number.

        Returns:
            int: The offset for the API request, which in OpenAlex is the page number.
        """
        return page


# class HAL_collector(API_collector):
#     """store file metadata"""
#     def __init__(self, filter_param, save, data_path):
#         super().__init__(filter_param, save, data_path)
#         self.rate_limit = 10
#         self.max_by_page = 500
#         self.api_name = "HAL"
#         self.api_url = "http://api.archives-ouvertes.fr/search/"

#     def parsePageResults(self,response,page):
#         page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
#         page_with_results =response.json()

#         # loop through partial list of results
#         results =  page_with_results['response']

#         for result in results["docs"]:
#             page_data["results"].append(result)

#         total=results["numFound"]
#         page_data["total"]=int(total)

#         return page_data

#     def get_configurated_url(self):
#         return self.get_url()+"?q="+self.get_keywords()+"&fl=title_s,abstract_s,label_s,arxivId_s,audience_s,authFullNameIdHal_fs,bookTitle_s,classification_s,conferenceTitle_s,docType_s,doiId_id,files_s,halId_s,jel_t,journalDoiRoot_s,journalTitle_t,keyword_s,type_s,submittedDateY_i&fq=submittedDateY_i:"+str(self.get_year())+"&rows="+str(self.get_max_by_page())+"&start={}"


class HAL_collector(API_collector):
    """Collector for fetching publication metadata from the HAL API."""

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the HAL collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 10  # Number of requests allowed per second
        self.max_by_page = 500  # Maximum number of results to retrieve per page
        self.api_name = "HAL"
        self.api_url = "http://api.archives-ouvertes.fr/search/"

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
        logging.info(f"Total results found for page {page}: {page_data['total']}")

        if total > 0:
            # Loop through the documents and append them to the results list
            for result in results["docs"]:
                page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """
        Constructs the API URL with the search query and filters based on the year and pagination.

        Returns:
            str: The formatted API URL for the request.
        """
        # Get all years from the filter parameter
        year_range = self.get_year()  # Assuming it returns a list or tuple of years

        # Determine the minimum and maximum years
        # year_min = min(year_range)
        # year_max = max(year_range)

        year_filter = f"submittedDateY_i:[{year_range}]"  # Create year range filter

        keywords = self.get_keywords()  # Get keywords from filter parameters

        # Flatten the keyword list if it contains lists of keywords
        flat_keywords = [
            keyword
            for sublist in keywords
            for keyword in (sublist if isinstance(sublist, list) else [sublist])
        ]

        # Construct keyword query by joining all keywords into a single string
        keyword_query = "%20AND%20".join(flat_keywords)  # Join keywords with ' OR '

        # Wrap the keyword query in parentheses
        keyword_query = f"({keyword_query})"

        # Construct the final URL
        configured_url = (
            f"{self.api_url}?q={keyword_query}&fl=title_s,abstract_s,label_s,arxivId_s,audience_s,authFullNameIdHal_fs,bookTitle_s,classification_s,conferenceTitle_s,docType_s,doiId_id,files_s,halId_s,jel_t,journalDoiRoot_s,journalTitle_t,keyword_s,type_s,submittedDateY_i&"
            f"{year_filter}&wt=json&rows={self.max_by_page}&start={{}}"
        )

        logging.info(f"Configured URL: {configured_url}")
        return configured_url


class Arxiv_collector(API_collector):
    """Collector for fetching publication metadata from the Arxiv API.

    This class constructs search queries based on title and abstract keywords
    and processes the results from the Arxiv API.
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 3  # Limit of API calls per second
        self.max_by_page = 500  # Maximum results per page
        self.api_name = "Arxiv"
        self.api_url = "http://export.arxiv.org/api/query"

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
        # Process each entry
        for entry in entries:
            date_published = entry.xpath('*[local-name()="published"]')[0].text
            if years_query in date_published:
                ### ADD IT TO KEEP ONLY GOOD DATE art

                current = {
                    "id": entry.xpath('*[local-name()="id"]')[0].text,
                    "updated": entry.xpath('*[local-name()="updated"]')[0].text,
                    "published": date_published,
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

        logging.info(f"Parsed {len(page_data['results'])} results from page {page}.")
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
        """
        Constructs a search query for the API from the keyword sets.
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
            group_keywords += [f'ti:"{urllib.parse.quote(keyword)}"']
            group_keywords += [f'abs:"{urllib.parse.quote(keyword)}"']

            # Join the current group's keywords with ' +OR+ '
            formatted_keyword_groups.append(f"({' +OR+ '.join(group_keywords)})")

        years_query = str(self.get_year())
        year_arg = (
            "submittedDate:["
            + years_query
            + "01D10000 + TO + "
            + years_query
            + "31122400]"
        )
        # Join all formatted keyword groups with ' +AND+ '
        search_query = "+AND+".join(formatted_keyword_groups)
        search_query = search_query + "&" + year_arg
        logging.info(f"Constructed search query: {search_query}")
        return search_query

    def get_configurated_url(self):
        """Constructs the API URL with the search query and date filters."""
        search_query = self.construct_search_query()  # Use the constructed search query

        logging.info(
            f"Configured URL: {self.api_url}?search_query={search_query}&sortBy=relevance&sortOrder=descending&start={{}}&max_results={self.max_by_page}"
        )
        return f"{self.api_url}?search_query={search_query}&sortBy=relevance&sortOrder=descending&start={{}}&max_results={self.max_by_page}"


# class Istex_collector(API_collector):
#     """store file metadata"""
#     def __init__(self, filter_param, save, data_path):
#          super().__init__(filter_param, save, data_path)
#          self.rate_limit = 3
#          self.max_by_page = 500
#          self.api_name = "Istex"
#          self.api_url = "https://api.istex.fr/document/"

#     def parsePageResults(self,response,page):
#          page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
#          page_with_results =response.json()
#          #print(page_with_results)
#          # loop through partial list of results
#          results =  page_with_results

#          for result in results["hits"]:
#              page_data["results"].append(result)

#          total=results["total"]
#          page_data["total"]=int(total)

#          return page_data

#     def get_configurated_url(self):
#         #kwd=" AND ".join(self.get_keywords().split(" "))
#         kwd=self.get_keywords()
#         kwd2="(publicationDate:"+str(self.get_year())+" AND title:("+kwd+") OR abstract:("+kwd+"))"
#         return self.get_url()+"?q="+kwd2+"&output=*&size"+str(self.get_max_by_page())+"&from={}"


class Istex_collector(API_collector):
    """Collector for fetching publication metadata from the Istex API."""

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 3
        self.max_by_page = 500  # Maximum number of results to retrieve per page
        self.api_name = "Istex"
        self.api_url = "https://api.istex.fr/document/"

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
        logging.info(f"Total results found for page {page}: {page_data['total']}")

        # Loop through the hits and append them to the results list
        for result in page_with_results.get("hits", []):
            page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """
        Constructs the API URL with the search query and filters based on the year and pagination.

        Returns:
            str: The formatted API URL for the request.
        """
        year_range = self.get_year()  # Assuming this returns a list of years
        # year_min = min(year_range)
        # year_max = max(year_range)

        # Construct the keyword query
        keywords = self.get_keywords()  # Get keywords from filter parameters

        # Flatten the keywords if necessary
        flat_keywords = [
            keyword
            for sublist in keywords
            for keyword in (sublist if isinstance(sublist, list) else [sublist])
        ]
        keyword_query = "%20AND%20".join(flat_keywords)  # Join keywords with ' OR '

        # Construct the final query string
        query = f"(publicationDate:{year_range} AND (title:({keyword_query}) OR abstract:({keyword_query})))"

        # Construct the URL
        configured_url = (
            f"{self.api_url}?q={query}&output=*&size={self.max_by_page}&from={{}}"
        )

        logging.info(f"Configured URL: {configured_url}")
        return configured_url


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
        self.rate_limit = 8
        self.max_by_page = 100
        self.api_name = "Springer"
        #     self.api_key = springer_api

        # Define both API URLs
        self.meta_url = "http://api.springernature.com/meta/v2/json"
        self.openaccess_url = "http://api.springernature.com/openaccess/json"

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

            page_data["total_nb"] = int(total)

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

    def get_configurated_url(self):
        """
        Constructs the URLs for both API endpoints.

        Returns:
            list: A list of constructed API URLs for both endpoints.
        """
        # Construct the search query
        keywords_query = self.construct_search_query()

        # Construct the URLs for both endpoints
        meta_url = f"{self.meta_url}?q={keywords_query}&api_key={self.api_key}"
        openaccess_url = (
            f"{self.openaccess_url}?q={keywords_query}&api_key={self.api_key}"
        )

        logging.info(f"Constructed query for meta: {meta_url}")
        logging.info(f"Constructed query for openaccess: {openaccess_url}")

        return [meta_url, openaccess_url]

    def collect_from_endpoints(self):
        """
        Collects data from both the meta and openaccess endpoints with pagination.

        Returns:
            list: Combined results from both endpoints.
        """
        urls = self.get_configurated_url()  # Get the list of API URLs
        combined_results = []

        for base_url in urls:  # Iterate through each base URL
            ################################# TO DO ?
            page = 1
            has_more_pages = True

            while has_more_pages:
                # Append pagination parameter to the base URL
                paginated_url = (
                    f"{base_url}&p={page}"  # Use 'p' for Springer API pagination
                )
                logging.info(f"Fetching data from URL: {paginated_url}")

                # Call the API
                try:
                    response = self.api_call_decorator(paginated_url)

                    # Parse the response
                    page_data = self.parsePageResults(response, page)
                    combined_results.append(
                        page_data
                    )  # Store results from this endpoint

                    # Determine if more pages are available
                    has_more_pages = len(page_data["results"]) == self.max_by_page
                    page += 1  # Increment page number for the next request

                except Exception as e:
                    logging.error(
                        f"Error fetching or parsing data from {paginated_url}: {str(e)}"
                    )
                    has_more_pages = False  # Stop fetching on error

        return combined_results


class GoogleScholarCollector(API_collector):
    """Collector for fetching publication metadata from Google Scholar via SerpAPI."""

    def __init__(self, filter_param, data_path, api_key):
        """
        Initializes the Google Scholar collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, data_path, api_key)
        self.rate_limit = 3  # Number of requests allowed per second
        self.max_by_page = 100  # Maximum number of results to retrieve per page
        self.api_name = "GoogleScholar"
        self.api_url = "https://serpapi.com/search.json"

    #     self.api_key = google_api

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
            "date_search": str(date.today()),  # Date of the search
            "id_collect": self.get_collectId(),  # Unique identifier for this collection
            "page": page,  # Current page number
            "total": 0,  # Total number of results found
            "results": [],  # List to hold the collected results
        }

        # Parse the JSON response
        page_with_results = response.json()

        # Extract total number of hits from the results
        total = page_with_results.get("search_information", {}).get("total_results", 0)
        page_data["total"] = int(total)
        logging.info(f"Total results found for page {page}: {page_data['total']}")

        if page_data["total"] > 0:
            # Loop through the hits and append them to the results list
            for result in page_with_results.get("organic_results", []):
                page_data["results"].append(result)

        return page_data

    def get_configurated_url(self):
        """
        Constructs the API URL with the search query and year filters for Google Scholar via SerpAPI.

        Returns:
            str: The formatted API URL for the request.
        """
        # Ensure keywords are flattened into a single space-separated string
        keywords_list = (
            self.get_keywords()
        )  # Assuming this returns a list of keyword sets
        # Flatten the list of keywords into a single string for the query
        keywords = "+".join(keywords_list)
        year_start = int(self.get_year())
        year_end = year_start + 1
        # year_start, year_end = self.get_year_range()  # Assuming get_year_range() returns a tuple (min_year, max_year)

        logging.info(
            f"Constructed Google Scholar URL with keywords: {keywords} and years: {year_start} - {year_end}"
        )
        return f"{self.api_url}?engine=google_scholar&api_key={self.api_key}&q={keywords}&as_ylo={year_start}&as_yhi={year_end}&hl=en"

    def get_year_range(self):
        """
        Returns the minimum and maximum year from the filter parameters.

        Returns:
            tuple: A tuple containing (min_year, max_year).
        """
        years = self.get_year()  # Assuming this returns a list of years
        if years:
            return (min(years), max(years))
        return (None, None)
