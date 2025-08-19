"""
Created on Mon Dec 19 09:48:58 2022

@author: cringwal
"""

import urllib.parse

import requests
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 10
MAX_call_day = 200

#     earch = "artificial intelligence+Deep Learning"

# or if you want to exclude some, use the - to exclude:

#     search = "artificial intelligence-application"
with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    key = cfg["springer"]["api_key"]


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


keyword = "(relation AND extraction AND survey)"
year = 2018
keywords = urllib.parse.quote(keyword)
springer_url = (
    "http://api.springernature.com/meta/v2/json?q=year:"
    + str(year)
    + " AND "
    + keywords
    + "&p=100&api_key="
    + key
    + "&s={}"
)


page = 1
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = springer_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["records"]

    #    ID : doi /
    #   Info : title/  creators / openaccess / publisher

    # next page
    page = page + 100

    has_more_pages = len(results) == 100
    total = int(page_with_results["result"][0]["total"])
    print(">>>>>", page, "/", total)
    fewer_than_10k_results = total <= 10000
    time_needed = total / 100 / 5 / 60
    print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
