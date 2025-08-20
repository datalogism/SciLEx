#!/usr/bin/env python3
"""
Created on Fri Dec 16 16:21:32 2022

@author: cringwal
"""

import requests
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 10


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


keyword = "'survey relation extraction'"
dblp_url = "https://dblp.org/search/publ/api?q=" + keyword + "&format=json&h=1000&f={}"

page = 0
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = dblp_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["result"]
    ### could be interresting to check results["completions"]

    # next page
    page = page + 1000
    total = int(results["hits"]["@total"])
    has_more_pages = len(results["hits"]["hit"]) == 1000
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
        time_needed = total10 / 60
        print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")
