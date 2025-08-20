#!/usr/bin/env python3
"""
Created on Wed Jan 18 10:50:00 2023

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


year = 2017
keyword = "'relation extraction'"

hal_url = (
    "http://api.archives-ouvertes.fr/search/?q="
    + keyword
    + "&fl=title_s,abstract_s,label_s,arxivId_s,audience_s,authFullNameIdHal_fs,bookTitle_s,classification_s,conferenceTitle_s,docType_s,doiId_id,files_s,halId_s,jel_t,journalDoiRoot_s,journalTitle_t,keyword_s,type_s,submittedDateY_i&fq=submittedDateY_i:"
    + str(year)
    + "&rows=500&start={}"
)


page = 1
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = hal_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["response"]
    ### could be interresting to check results["completions"]

    # next page
    page = page + 500
    total = results["numFound"]
    has_more_pages = len(results["docs"]) == 500
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
        time_needed = total10 / 60
        print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")
