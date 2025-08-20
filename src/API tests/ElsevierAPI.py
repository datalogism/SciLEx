#!/usr/bin/env python3
"""
Created on Fri Dec 16 16:21:32 2022

@author: cringwal
"""

import urllib.parse

import requests
import yaml
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 8

#     earch = "artificial intelligence+Deep Learning"

# or if you want to exclude some, use the - to exclude:

#     search = "artificial intelligence-application"


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    key = cfg["elsevier"]["api_key"]


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


keyword = "KEY(relation AND extraction AND survey)"
year = 2022
keywords = urllib.parse.quote(keyword + " AND PUBYEAR = " + str(year))
elsevier_url = (
    "https://api.elsevier.com/content/search/scopus?query="
    + keywords
    + "&count=100&apiKey="
    + key
    + "&start={}"
)

page = 0
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = elsevier_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["search-results"]

    # next page
    page = page + 100

    has_more_pages = len(results["entry"]) == 100
    total = int(results["opensearch:totalResults"])
    print(">>>>>", page, "/", total)
    fewer_than_10k_results = total <= 10000
    time_needed = total / 100 / 5 / 60
    print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
