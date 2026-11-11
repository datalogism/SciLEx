#!/usr/bin/env python3
"""
Created on Wed Jan 18 14:36:15 2023

@author: cringwal
"""

import logging
import os
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from lxml import etree
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 3


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    """Access arXiv API with rate limiting."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to access arXiv API at {url}: {e}")
        return None


year = 2017
keyword = "survey relation extraction"
keywords = "ti:" + " AND ti:".join([k for k in keyword.split()])
# ti -> title, abs -> abstract, all -> all fields
arxiv_url = (
    "http://export.arxiv.org/api/query?search_query="
    + keywords
    + "&sortBy=lastUpdatedDate&max_results=500&start={}"
)


def toZoteroFormat(row):
    from src.constants import MISSING_VALUE

    zotero_temp = {
        "title": MISSING_VALUE,
        "itemType": MISSING_VALUE,
        "authors": MISSING_VALUE,
        "language": MISSING_VALUE,
        "abstract": MISSING_VALUE,
        "archiveID": MISSING_VALUE,
        "archive": MISSING_VALUE,
        "date": MISSING_VALUE,
        "DOI": MISSING_VALUE,
        "url": MISSING_VALUE,
        "rights": MISSING_VALUE,
        "pages": MISSING_VALUE,
        "journalAbbreviation": MISSING_VALUE,
        "volume": MISSING_VALUE,
        "serie": MISSING_VALUE,
    }

    from src.constants import is_valid

    # Genre pas clair
    zotero_temp["archive"] = "Arxiv"
    if is_valid(current.get("abstract")):
        zotero_temp["abstract"] = row["abstract"]
    if is_valid(current.get("authors")):
        zotero_temp["authors"] = ";".join(current["authors"])
    if is_valid(current.get("doi")):
        zotero_temp["DOI"] = current["doi"]
    if is_valid(current.get("title")):
        zotero_temp["title"] = row["title"]
    if is_valid(current.get("id")):
        zotero_temp["archiveID"] = row["id"]
    if is_valid(current.get("published")):
        zotero_temp["date"] = row["published"]
    if is_valid(current.get("journal")):
        zotero_temp["journalAbbreviation"] = row["journal"]

    return zotero_temp


page = 1
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = arxiv_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.content
    tree = etree.fromstring(page_with_results)
    entries = tree.xpath('*[local-name()="entry"]')
    results = []
    for entry in entries:
        print("---------")
        current = {}
        current["id"] = entry.xpath('*[local-name()="id"]')[0].text
        current["updated"] = entry.xpath('*[local-name()="updated"]')[0].text
        current["published"] = entry.xpath('*[local-name()="published"]')[0].text
        current["title"] = entry.xpath('*[local-name()="title"]')[0].text
        current["abstract"] = entry.xpath('*[local-name()="summary"]')[0].text
        authors = entry.xpath('*[local-name()="author"]')
        current["doi"] = ""
        current["journal"] = ""
        auth_list = []
        for auth in authors:
            auth_list.append(auth.xpath('*[local-name()="name"]')[0].text)
        current["authors"] = auth_list

        # Extract optional fields with proper error handling
        try:
            pdf_links = entry.xpath('*[local-name()="link" and @title="pdf"]')
            if pdf_links:
                current["pdf"] = pdf_links[0].text
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No PDF link found for entry: {e}")

        # Try to get DOI from multiple possible locations
        try:
            doi_elements = entry.xpath('*[local-name()="doi"]')
            if doi_elements:
                current["doi"] = doi_elements[0].text
            else:
                doi_links = entry.xpath('*[local-name()="link" and @title="doi"]')
                if doi_links:
                    current["doi"] = doi_links[0].text
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No DOI found for entry: {e}")

        try:
            comment_elements = entry.xpath('*[local-name()="comment"]')
            if comment_elements:
                current["comment"] = comment_elements[0].text
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No comment found for entry: {e}")

        try:
            journal_elements = entry.xpath('*[local-name()="journal_ref"]')
            if journal_elements:
                current["journal"] = journal_elements[0].text
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No journal found for entry: {e}")

        try:
            primary_cat = entry.xpath('*[local-name()="primary_category"]')
            if primary_cat:
                main_cat = primary_cat[0].attrib["term"]
            else:
                main_cat = None
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No main category found for entry: {e}")
            main_cat = None

        try:
            categories = entry.xpath('*[local-name()="category"]')
            cat_list = []
            for cat in categories:
                if "term" in cat.attrib:
                    cat_list.append(cat.attrib["term"])
            current["categories"] = cat_list
        except (IndexError, KeyError, AttributeError) as e:
            logging.debug(f"No categories found for entry: {e}")
            current["categories"] = []
        results.append(current)
    # loop through partial list of results
    # results = page_with_results['response']
    ### could be interresting to check results["completions"]
    for res in results:
        print(toZoteroFormat(res))

    # next page
    page = page + 500
    total_raw = tree.xpath('*[local-name()="totalResults"]')
    total = int(total_raw[0].text)
    has_more_pages = len(entries) == 500
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
        time_needed = total / 3 / 60
        print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")
