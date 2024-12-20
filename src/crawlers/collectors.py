#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 25 09:07:19 2023

@author: cringwal
"""

############## TO DO 
# https://doaj.org/api/docs
# https://api.base-search.net/ 
# https://www.doabooks.org/en/article/api-search-doab
# https://core.ac.uk/services/api
# https://graph.openaire.eu/develop/
# + Springer

import requests
import traceback
from ratelimit import limits, RateLimitException, sleep_and_retry
from csv import writer
import os
import json
import urllib.parse
from lxml import etree
from xml.etree import ElementTree
import logging
from datetime import date

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

import yaml
############ 
# CLASS USED FOR PARAMETRIZE CRAWLERS
############

# Get the current working directory
current_directory = os.getcwd()

root_dir=current_directory.split("/src/")
root_dir=root_dir[0]+"/src/"
# Construct the full path to the YAML file
yaml_file_path = os.path.join(root_dir, "scilex.config.yml")

# Open and read the YAML file
with open(yaml_file_path, "r") as ymlfile:

    cfg = yaml.load(ymlfile, Loader=yaml.SafeLoader)
    sem_scholar_api=cfg["sem_scholar"]["api_key"]
    springer_api=cfg["springer"]["api_key"]
    elsevier_api=cfg["elsevier"]["api_key"]
    google_api=cfg["google_scholar"]["api_key"]
    ieee_api=cfg["ieee"]["api_key"]
    openalex_mail=cfg["email"]

class Filter_param:
    def __init__(self, year, keywords, focus):
        # Initialize the parameters
        self.year = year
        # Keywords is now a list of lists to support multiple sets
        self.keywords = keywords
        self.focus = focus
        
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
    def __init__(self, filter_param, save, data_path):
        # In second
        self.filter_param = filter_param
        self.save= save     
        self.rate_limit = 10
        self.datadir=data_path
        self.collectId=0
        self.lastpage=0
        self.big_collect=0
        self.max_by_page=100
        self.api_url=""
        self.complete=0
        
    def set_collectId(self, collectId):
        self.collectId = collectId
    def set_lastpage(self, lastpage):
        self.lastpage = lastpage
    def set_complete(self, complete):
        self.complete = complete
        
    def get_collectId(self):
        return self.collectId   
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
        return self.get_dataDir()+"/"+self.get_api_name()
    def get_collectDir(self):
        return self.get_apiDir()+"/"+str(self.get_collectId())
    def get_fileCollect(self):
        return self.get_dataDir()+"/collect_dict.json"
    def get_url(self):
         return self.api_url
    def get_apikey(self):
          return self.api_key
    def get_configurated_url(self):
        return self.get_url()
    def get_max_by_page(self):
        return self.max_by_page
    def get_ratelimit(self):
        return self.rate_limit
    
    def api_call_decorator(self,configurated_url):
        #print("REQUEST")
        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            #print("REQUEST")
            try:
                resp = requests.get(configurated_url)
            except:
                print("PB AFTER REQUEST")
            return resp
        return access_rate_limited_decorated(configurated_url)
    
    def toZotero():
        pass
    
    def get_configurated_url(self):
        return self.get_url()
    
    def getCollectId(self):
        try:
            with open(self.get_fileCollect()) as json_file:
                data_coll = json.load(json_file) 
            print("LOAD FILE")
        except:
            print("EMPTY FILE")
            data_coll = {}
            
        
        id_collect=self.get_collectId()
        found=False
        max_id=-1
        for k in data_coll.keys():
            if(data_coll[k]["API"]==self.get_api_name() and data_coll[k]["kwd"]==self.get_keywords() and data_coll[k]["year"]==str(self.get_year())):
                self.set_collectId(k)
                self.set_lastpage(data_coll[k]["last_page"])
                self.set_complete(data_coll[k]["complete"])
                found=True
                print("FOUND")
                break
            max_id=max(int(k),max_id)
        #print("max_id",max_id)
        if(found==False):
            
            print("NOT FOUND")
            if(max_id!=-1):
                #print("max_id!=-1")
                #print("new id ?" ,str(max_id+1))
                self.set_collectId(str(max_id+1))
                #print("new id ?" ,self.get_collectId())
                data_coll[str(self.get_collectId())]={"API":self.get_api_name(),"kwd":self.get_keywords(),"year":str(self.get_year()),"last_page":0,"complete":0}
            if(max_id==-1):
                #print("max_id=-1")
                data_coll["0"]={"API":self.get_api_name(),"kwd":self.get_keywords(),"year":str(self.get_year()),"last_page":0,"complete":0}
        
            with open(self.get_fileCollect(), 'w') as json_file:
                json.dump(data_coll, json_file)
        
    def createCollectDir(self):
        if not os.path.isdir(self.get_apiDir()):
            os.makedirs(self.get_apiDir())
        if not os.path.isdir(self.get_collectDir()):
            os.makedirs(self.get_collectDir())
            
    def savePageResults(self,global_data,page):
        
        self.createCollectDir()
        print(self.get_collectDir()+"/page_"+str(page))
        with open(self.get_collectDir()+"/page_"+str(page), 'w', encoding='utf8') as json_file:
            json.dump(global_data, json_file)
        with open(self.get_fileCollect()) as json_file:
            data_coll = json.load(json_file)
        data_coll[str(self.get_collectId())]["last_page"]=page
        with open(self.get_fileCollect(), 'w') as json_file:
            json.dump(data_coll, json_file)
                

    # def parsePageResults(self, response, page):
    #     """
    #     Parses the JSON response from the API for a specific page of results.
        
    #     Args:
    #         response (requests.Response): The response object from the API call.
    #         page (int): The current page number being processed.
            
    #     Returns:
    #         dict: A dictionary containing metadata about the search, including
    #             the date of search, collection ID, current page, total results,
    #             and the parsed results.
    #     """
    #     try:
    #         # Parse the JSON response from the API
    #         page_with_results = response.json()
    #         # Initialize a dictionary to hold the parsed page data
    #         page_data = {
    #             "date_search": str(date.today()),  # Current date of the search
    #             "id_collect": self.get_collectId(),  # Collection ID for this search
    #             "page": page,  # Current page number
    #             "total": 0,    # Placeholder for total results count
    #             "results": []  # List to hold individual result entries
    #         }
    #         # Log the entire response for debugging (can be commented out in production)
    #         logging.debug(f"API Response for page {page}: {page_with_results}")

    #         # Check if the 'records' key exists, which holds the actual results
    #         if 'records' in page_with_results:
    #             results = page_with_results['records']
    #             total = int(page_with_results["result"][0].get("total", 0))  # Get total results count
    #             page_data["total"] = total  # Update the total number of results
                
    #             logging.info(f"Processing page {page}: Found {total} results.")

    #             # Iterate over each result and process it
    #             for result in results:
    #                 page_data["results"].append(result)  # Append result to the results list
    #                 SemanticScholartoZoteroFormat(result)  # Convert result to Zotero format

    #         else:
    #             # If the 'records' key is missing, log an error with response details
    #             logging.error(f"Missing 'records' key in API response for page {page}: {page_with_results}")

    #         # Log the parsed results for debugging
    #         logging.debug(f"Parsed results for page {page}: {page_data['results']}")

    #     except Exception as e:
    #         # Capture the traceback and include it in the error log
    #         logging.error(f"Error processing results on page {page} from URL '{response.url}': {str(e)}. "
    #                     f"Response type: {type(response)}. Response content: {response.text if hasattr(response, 'text') else 'N/A'}. "
    #                     f"Traceback: {traceback.format_exc()}")

    #     return page_data

    def flagAsComplete(self):
        with open(self.get_fileCollect()) as json_file:
            data_coll = json.load(json_file)
        data_coll[str(self.get_collectId())]["complete"]=1
        with open(self.get_fileCollect(), 'w') as json_file:
            json.dump(data_coll, json_file)
    
    def add_offset_param(self,page):
        return self.get_configurated_url().format((page-1)*self.get_max_by_page())
        
    def get_offset(self, page):
        return (page-1)*self.get_max_by_page()
    
    def runCollect(self):
        """
        Runs the collection process for DBLP and Springer publications.
        
        This method retrieves publication data in pages until all results
        are collected or a specified limit is reached.
        """
        self.getCollectId()  # Retrieve the collection identifier

        # Check if the collection has already been completed
        if self.complete == 1:
            logging.info("Collection already completed.")
            return  # Exit if collection is complete

        page = int(self.get_lastpage()) + 1  # Start from the next page
        has_more_pages = True

        # Determine if there are fewer than 10,000 results based on collection size
        fewer_than_10k_results = (self.big_collect == 0)

        if isinstance(self, Springer_collector):
            # If this is a Springer collector, use the 'collect_from_endpoints' method
            logging.info("Running collection for Springer data.")
            
            try:
                combined_results = self.collect_from_endpoints()  # Collect results from Springer endpoints
                
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
                    logging.info(f"Processed page {page}: {len(page_data['results'])} results. Total found: {page_data['total']}")
            
            except Exception as e:
                # Log additional context about the error
                logging.error(f"Error processing results on page {page} from Springer API: {str(e)}")
                has_more_pages = False  # Stop collecting if there's an error

        else:
            # If this is a DBLP collector, follow the normal process
            while has_more_pages and fewer_than_10k_results:
                offset = self.get_offset(page)  # Calculate the current offset
                url = self.get_configurated_url().format(offset)  # Construct the API URL
                logging.info(f"Fetching data from URL: {url}")

                response = self.api_call_decorator(url)  # Call the API
                try:
                    page_data = self.parsePageResults(response, page)  # Parse the response

                    # Save the page results for future use
                    self.savePageResults(page_data, page)

                    # Update the last page collected
                    self.set_lastpage(int(page) + 1)

                    # Determine if more pages are available based on results returned
                    has_more_pages = len(page_data["results"]) == self.get_max_by_page()
                    page = self.get_lastpage()  # Update the current page number

                    # Check if the total number of results is within the limit
                    fewer_than_10k_results = page_data["total"] <= 10000
                    logging.info(f"Processed page {page}: {len(page_data['results'])} results. Total found: {page_data['total']}")
                    
                except Exception as e:
                    # Log additional context about the error
                    logging.error(f"Error processing results on page {page} from URL '{url}': {str(e)}. "
                                f"Response type: {type(response)}.")
                    has_more_pages = False  # Stop collecting if there's an error

        # Final log messages based on the collection status
        if not has_more_pages:
            logging.info("No more pages to collect. Marking collection as complete.")
            self.flagAsComplete()
        else:
            time_needed = page_data["total"] / self.get_max_by_page() / 60 / 60
            logging.info(f"Total extraction will need approximately {time_needed:.2f} hours.")


## OK 
class SemanticScholar_collector(API_collector):
    
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
  
        self.rate_limit = 100
        self.max_by_page = 100
        self.api_name = "SemanticScholar"
        self.api_key = sem_scholar_api
        self.api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        
    def api_call_decorator(self,configurated_url):
        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            resp = requests.get(configurated_url, headers={'x-api-key':  self.get_apikey()})
            return resp
        
        return access_rate_limited_decorated(configurated_url)
            
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        page_with_results =response.json()
       
        # loop through partial list of results
        try:
            total=page_with_results["total"]
            page_data["total"]=int(total)
            if(page_data["total"]>0):
                results = page_with_results['data']
                for result in results:
                    page_data["results"].append(result)
        except:
            print(response.status_code)
        
        return page_data
    
    def get_configurated_url(self):
        #kw=self.get_keywords().replace("AND ","").replace("'","")
        keywords=urllib.parse.quote(self.get_keywords())
        return self.get_url()+"?query="+keywords+"&fieldsOfStudy=Computer Science,Linguistics,Mathematics&fields=title,abstract,url,venue,publicationVenue,citationCount,externalIds,referenceCount,s2FieldsOfStudy,publicationTypes,publicationDate,isOpenAccess,openAccessPdf,authors,journal,fieldsOfStudy&year="+str(self.get_year())+"&limit="+str(self.get_max_by_page())+"&offset={}"

### IS WORKING ?
class IEEE_collector(API_collector):
    #https://developer.ieee.org/docs
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.api_name="IEEE"
        self.rate_limit = 200
        self.max_by_page = 200
        self.api_key=ieee_api
        self.api_url="http://ieeexploreapi.ieee.org/api/v1/search/articles"
        
    def get_configurated_url(self):
        # PUB YEAR ?
        keywords=urllib.parse.quote(self.get_keywords())
        return self.get_url()+"?apikey="+self.get_apikey()+"&format=json&max_records="+str(self.get_max_by_page())+"&sort_order=asc&sort_field=article_number&article_title="+keywords+"&publication_year="+str(self.get_year())+"&start_record={}"
   
    # REALLY NEEDED ?
    # def api_call_decorator(self,configurated_url):
    #     @sleep_and_retry
    #     @limits(calls=self.get_ratelimit(), period=1)
    #     def access_rate_limited_decorated(configurated_url):
    #         resp = requests.get(configurated_url, headers={'x-api-key':  self.get_apikey()})
    #         return resp
        
    #     return access_rate_limited_decorated(configurated_url)
            
    
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
      
        page_with_results =response.json()
        # loop through partial list of results
        total=page_with_results["total_records"]
        page_data["total"]=int(total)
        if(page_data["total"]>0):
            results = page_with_results['articles']
            for result in results:
                page_data["results"].append(result)
        
        return page_data
## OK 
class Elsevier_collector(API_collector):
    """Store file metadata from Elsevier API."""
    
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 8
        self.max_by_page = "100"
        self.api_name = "Elsevier"
        self.api_key = elsevier_api
        self.api_url = "https://api.elsevier.com/content/search/scopus"
        
    def parsePageResults(self, response, page):
        """Parse the JSON response from Elsevier API and return structured data."""
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": []
        }
      
        page_with_results = response.json()
        
        # Loop through partial list of results
        results = page_with_results['search-results']
        total = results["opensearch:totalResults"]
        page_data["total_nb"] = int(total)
        if page_data["total_nb"] > 0:
            for result in results["entry"]:
                page_data["results"].append(result)
        
        return page_data
    
    def construct_search_query(self):
        """
        Constructs a search query for the API from the keyword sets.
        The format will be:
        TITLE(NLP OR Natural Language Processing) AND TITLE(Pragmatic OR Pragmatics)
        """
        formatted_keyword_groups = []

        # Iterate through each set of keywords
        for keyword_set in self.get_keywords():
            # Initialize a list to hold the formatted keywords for the current group
            group_keywords = []

            # Join keywords within the same set with ' OR '
            group_keywords += [f'"{keyword}"' for keyword in keyword_set]  # Use quotes for exact matching

            # Join the current group's keywords with ' OR ' and wrap in TITLE()
            formatted_keyword_groups.append(f'TITLE({" OR ".join(group_keywords)})')

        # Join all formatted keyword groups with ' AND '
        search_query = ' AND '.join(formatted_keyword_groups)

        logging.info(f"Constructed search query: {search_query}")
        return search_query
    
    def get_configurated_url(self):
        """Constructs the API URL with the search query and publication year filters."""
        # Construct the search query
        keywords_query = self.construct_search_query()  # Get the formatted keyword query

        # Create the years query
        years_query = ' OR '.join(str(year) for year in self.get_year())

        # Combine the queries
        query = f"{keywords_query} AND PUBYEAR > {years_query}"

        # Construct the final URL
        return f"{self.api_url}?query={query}&apiKey={self.api_key}"

class DBLP_collector(API_collector):
    """Class to collect publication data from the DBLP API."""
    
    def __init__(self, filter_param, save, data_path):
        """
        Initializes the DBLP collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, save, data_path)
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
            "results": []  # List to hold the collected results
        }
        
        # Parse the JSON response
        page_with_results = response.json()
         
        # Extract the total number of hits from the results
        results = page_with_results['result']
        total = results["hits"]["@total"]
        page_data["total"] = int(total)
        logging.info(f"Total results found for page {page}: {page_data['total']}")
        
        if page_data["total"] > 0:
            # Loop through the hits and append them to the results list
            for result in results["hits"]["hit"]:
                page_data["results"].append(result)

        return page_data
    
    def get_configurated_url(self):
        """
        Constructs the configured API URL based on keywords and years.

        Returns:
            str: The formatted API URL with the constructed query parameters.
        """
        # Process keywords: Join items in each list with '|', then join the lists with ' '
        keywords_query = ' '.join(['|'.join(keyword_set) for keyword_set in self.get_keywords()])

        # Process year: Join years with '|'
        years_query = '|'.join(str(year) for year in self.get_year())
        
        # Combine keywords and years into the query string
        query = f"{keywords_query} {years_query}"
        logging.info(f"Constructed query for API: {query}")
        
        # Return the final API URL
        return f"{self.api_url}?q={query}&format=json&h={self.max_by_page}&f={{}}"

class OpenAlex_collector(API_collector):
    """Class to collect publication data from the OpenAlex API."""
    
    def __init__(self, filter_param, save, data_path):
        """
        Initializes the OpenAlex collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 10  # Number of requests allowed per second
        self.max_by_page = 200  # Maximum number of results to retrieve per page
        self.api_name = "OpenAlex"
        self.api_url = "https://api.openalex.org/works"
        self.openalex_mail = openalex_mail  # Add your email for the OpenAlex API requests

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
            "results": []  # List to hold the collected results
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
            keyword_filters += [f"abstract.search:{keyword}" for keyword in keyword_set]
            keyword_filters += [f"title.search:{keyword}" for keyword in keyword_set]

        # Join all keyword filters with commas (as per OpenAlex API format)
        formatted_keyword_filters = ','.join(keyword_filters)

        # Extract the min and max year from self.get_year() and create the range
        years = self.get_year()  # Assuming this returns a list of years
        min_year = min(years)
        max_year = max(years)
        year_filter = f"publication_year:{min_year}-{max_year}"

        # Combine all filters into the final URL
        api_url = (f"{self.api_url}?filter={formatted_keyword_filters},{year_filter}"
                f"&per-page={self.max_by_page}&mailto={self.openalex_mail}&page={{}}")

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
    
    def __init__(self, filter_param, save, data_path):
        """
        Initializes the HAL collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, save, data_path)
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
            "results": []  # List to hold the collected results
        }
        
        # Parse the JSON response
        page_with_results = response.json()
        
        # Extract the total number of hits from the results
        results = page_with_results['response']
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
        year_min = min(year_range)
        year_max = max(year_range)
        
        year_filter = f"submittedDateY_i:[{year_min}%20TO%20{year_max}]"  # Create year range filter
        
        keywords = self.get_keywords()  # Get keywords from filter parameters
        
        # Flatten the keyword list if it contains lists of keywords
        flat_keywords = [keyword for sublist in keywords for keyword in (sublist if isinstance(sublist, list) else [sublist])]

        # Construct keyword query by joining all keywords into a single string
        keyword_query = '%20OR%20'.join(flat_keywords)  # Join keywords with ' OR '
        
        # Wrap the keyword query in parentheses
        keyword_query = f"({keyword_query})"

        # Construct the final URL
        configured_url = (
            f"{self.api_url}?q={keyword_query}&fl=title_s,abstract_s,keyword_s&"
            f"{year_filter}&wt=json&rows={self.max_by_page}&start={{}}"
        )
        
        logging.info(f"Configured URL: {configured_url}")
        return configured_url


class Arxiv_collector(API_collector):
    """Collector for fetching publication metadata from the Arxiv API.
    
    This class constructs search queries based on title and abstract keywords
    and processes the results from the Arxiv API.
    """

    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
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
            "results": []
        }
        
        # Parse the XML response content
        page_with_results = response.content
        tree = etree.fromstring(page_with_results)
        
        # Extract entries from the XML tree
        entries = tree.xpath('*[local-name()="entry"]')
        
        # Process each entry
        for entry in entries:
            current = {
                "id": entry.xpath('*[local-name()="id"]')[0].text,
                "updated": entry.xpath('*[local-name()="updated"]')[0].text,
                "published": entry.xpath('*[local-name()="published"]')[0].text,
                "title": entry.xpath('*[local-name()="title"]')[0].text,
                "abstract": entry.xpath('*[local-name()="summary"]')[0].text,
                "authors": self.extract_authors(entry),  # Extract authors separately
                "doi": self.extract_doi(entry),  # Extract DOI separately
                "pdf": self.extract_pdf(entry),  # Extract PDF link
                "journal": self.extract_journal(entry),  # Extract journal reference
                "categories": self.extract_categories(entry)  # Extract categories
            }
            page_data["results"].append(current)
        
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
        return [cat.attrib['term'] for cat in categories]

    def construct_search_query(self):
        """
        Constructs a search query for the API from the keyword sets.
        The format will be:
        ti:"NLP" OR ti:"Natural Language Processing" OR abs:"NLP" OR abs:"Natural Language Processing"
        AND
        ti:"Pragmatic" OR ti:"Pragmatics" OR abs:"Pragmatic" OR abs:"Pragmatics"
        """
        formatted_keyword_groups = []

        # Iterate through each set of keywords
        for keyword_set in self.get_keywords():
            # Initialize a list to hold the formatted keywords for the current group
            group_keywords = []

            # Join keywords within the same set with ' OR '
            group_keywords += [f'ti:"{keyword}"' for keyword in keyword_set]  # Title queries
            group_keywords += [f'abs:"{keyword}"' for keyword in keyword_set]  # Abstract queries

            # Join the current group's keywords with ' OR '
            formatted_keyword_groups.append('+OR+'.join(group_keywords))

        # Join all formatted keyword groups with ' +AND+ '
        search_query = '+AND+'.join(formatted_keyword_groups)

        logging.info(f"Constructed search query: {search_query}")
        return search_query
    
    def get_configurated_url(self):
        """Constructs the API URL with the search query and date filters."""
        search_query = self.construct_search_query()  # Use the constructed search query

        logging.info(f"Configured URL: {self.api_url}?search_query={search_query}&sortBy=relevance&sortOrder=descending&start={{}}&max_results={self.max_by_page}")
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
    
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
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
            "results": []  # List to hold the collected results
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
        year_min = min(year_range)
        year_max = max(year_range)

        # Construct the keyword query
        keywords = self.get_keywords()  # Get keywords from filter parameters
        
        # Flatten the keywords if necessary
        flat_keywords = [keyword for sublist in keywords for keyword in (sublist if isinstance(sublist, list) else [sublist])]
        keyword_query = '%20OR%20'.join(flat_keywords)  # Join keywords with ' OR '

        # Construct the final query string
        query = f"(publicationDate:[{year_min} TO {year_max}] AND (title:({keyword_query}) OR abstract:({keyword_query})))"
        
        # Construct the URL
        configured_url = f"{self.api_url}?q={query}&output=*&size={self.max_by_page}&from={{}}"
        
        logging.info(f"Configured URL: {configured_url}")
        return configured_url


class Springer_collector(API_collector):
    """Store file metadata from Springer API."""
    
    def __init__(self, filter_param, save, data_path):
        """
        Initialize the Springer Collector.

        Args:
            filter_param (dict): The filter parameters for the search query.
            save (bool): Flag to indicate whether to save the data.
            data_path (str): Path to save the data.
        """
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 8
        self.max_by_page = 100
        self.api_name = "Springer"
        self.api_key = springer_api

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
            "results": []
        }

        try:
            # Parse the JSON response from the API
            page_with_results = response.json()

            # Extract the 'records' list and the 'result' which contains metadata
            records = page_with_results.get('records', [])
            result_info = page_with_results.get('result', [])

            # Handle 'result' being a list and extract the first entry's 'total' if available
            if isinstance(result_info, list) and len(result_info) > 0:
                total = result_info[0].get('total', 0)
            else:
                total = 0

            page_data["total_nb"] = int(total)

            # Process the 'records' if they exist and are in the correct format
            if isinstance(records, list) and len(records) > 0:
                for result in records:
                    page_data["results"].append(result)
            else:
                logging.warning(f"No valid records found on page {page}. Records type: {type(records)}. Response: {page_with_results}")
            
        except Exception as e:
            # Log detailed error information
            logging.error(f"Error parsing page {page}. Response content: {response.text}. Error: {str(e)}")
            raise

        return page_data

    def construct_search_query(self):
        """
        Constructs a search query for the Springer API from the keyword sets.
        The format will be:
        (title:"keyword1" OR title:"keyword2") AND (title:"keyword3" OR title:"keyword4")
        """
        formatted_keyword_groups = []

        # Iterate through each set of keywords
        for keyword_set in self.get_keywords():
            # Join keywords within the same set with ' OR ' and format for title
            group_keywords = ' OR '.join([f'"{keyword}"' for keyword in keyword_set])
            formatted_keyword_groups.append(f"({group_keywords})")

        # Join all formatted keyword groups with ' AND '
        search_query = ' AND '.join(formatted_keyword_groups)
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
        openaccess_url = f"{self.openaccess_url}?q={keywords_query}&api_key={self.api_key}"

        logging.info(f"Constructed query for meta: {meta_url}")
        logging.info(f"Constructed query for openaccess: {openaccess_url}")
        
        return [meta_url, openaccess_url]

    def collect_from_endpoints(self):
        """
        Collects data from both the meta and openaccess endpoints with pagination.
        
        Returns:
            list: Combined results from both endpoints.
        """
        urls = self.get_configurated_url()
        combined_results = []

        for url in urls:
            page = 1
            has_more_pages = True

            while has_more_pages:
                logging.info(f"Fetching data from URL: {url}&offset={page}")
                response = self.api_call_decorator(f"{url}&offset={page}")  # Call the API with pagination
                page_data = self.parsePageResults(response, page)  # Parse the response
                
                combined_results.append(page_data)  # Store results from this endpoint

                has_more_pages = len(page_data['results']) == self.max_by_page
                page += 1  # Increment page number for next request

        return combined_results


class GoogleScholarCollector(API_collector):
    """Collector for fetching publication metadata from Google Scholar via SerpAPI."""
    
    def __init__(self, filter_param, save, data_path):
        """
        Initializes the Google Scholar collector with the given parameters.

        Args:
            filter_param (Filter_param): The parameters for filtering results (years, keywords, etc.).
            save (int): Flag indicating whether to save the collected data.
            data_path (str): Path to save the collected data.
        """
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 3  # Number of requests allowed per second
        self.max_by_page = 100  # Maximum number of results to retrieve per page
        self.api_name = "GoogleScholar"
        self.api_url = "https://serpapi.com/search.json"
        self.api_key = google_api


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
            "results": []  # List to hold the collected results
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
        keywords_list = self.get_keywords()  # Assuming this returns a list of keyword sets
        # Flatten the list of keywords into a single string for the query
        keywords = "+".join(" + ".join(keyword_set) for keyword_set in keywords_list)

        year_start, year_end = self.get_year_range()  # Assuming get_year_range() returns a tuple (min_year, max_year)

        logging.info(f"Constructed Google Scholar URL with keywords: {keywords} and years: {year_start} - {year_end}")
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
