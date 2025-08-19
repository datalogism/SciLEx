#!/usr/bin/env python3
"""
Created on Wed Jan 18 10:31:14 2023

@author: cringwal
"""

import requests
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 10
import yaml

############
# SCRIPT FOR GETTING ABSTRACT FROM linkedpaperswithcode
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    email = cfg["openalex"]["email"]


def toZoteroFormat(row):
    zotero_temp = {
        "title": "NA",
        "itemType": "NA",
        "authors": "NA",
        "language": "NA",
        "abstract": "NA",
        "archiveID": "NA",
        "archive": "NA",
        "date": "NA",
        "DOI": "NA",
        "url": "NA",
        "rights": "NA",
        "pages": "NA",
        "journalAbbreviation": "NA",
        "volume": "NA",
        "serie": "NA",
    }

    # Genre pas clair
    zotero_temp["archive"] = "Arxiv"

    return zotero_temp


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


year = 2017
keyword = "'survey relation extraction'"

oa_url = (
    "https://api.openalex.org/works?q="
    + keyword
    + "&per-page=200&filter=publication_year:"
    + str(year)
    + "&mailto="
    + email
    + "&page={}"
)


page = 1
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = oa_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["results"]
    ### could be interresting to check results["completions"]

    # next page
    page = page + 200
    total = page_with_results["meta"]["count"]
    has_more_pages = len(results["hits"]["hit"]) == 200
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
        time_needed = total10 / 60
        print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")
