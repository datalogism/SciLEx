#!/usr/bin/env python3
"""
Created on Wed Jan 18 14:36:15 2023

@author: cringwal
"""

import requests
from lxml import etree
from ratelimit import limits, sleep_and_retry

ONE_SEC = 1
MAX_CALLS_PER_SECOND = 3


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


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
    if current["abstract"] != "" and current["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]
    if current["authors"] != "" and current["authors"] is not None:
        zotero_temp["authors"] = ";".join(current["authors"])
    if current["doi"] != "" and current["doi"] is not None:
        zotero_temp["DOI"] = current["doi"]
    if current["title"] != "" and current["title"] is not None:
        zotero_temp["title"] = row["title"]
    if current["id"] != "" and current["id"] is not None:
        zotero_temp["archiveID"] = row["id"]
    if current["published"] != "" and current["published"] is not None:
        zotero_temp["date"] = row["published"]
    if current["journal"] != "" and current["journal"] is not None:
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

        try:
            current["pdf"] = entry.xpath('*[local-name()="link" and @title="pdf"]')[
                0
            ].text
        except:
            print("NO pdf")
        try:
            current["doi"] = entry.xpath('*[local-name()="doi"]')[0].text
        except:
            try:
                current["doi"] = entry.xpath('*[local-name()="link" and @title="doi"]')[
                    0
                ].text
            except:
                print("NO doi")

        try:
            current["comment"] = entry.xpath('*[local-name()="comment"]')[0].text
        except:
            print("NO comment")
        # cuurent["url"]=entry.xpath('*[local-name()=" arxiv:comment"]')[0].text
        try:
            current["journal"] = entry.xpath('*[local-name()="journal_ref"]')[0].text
        except:
            print("NO journal")
        try:
            main_cat = entry.xpath('*[local-name()="primary_category"]')[0].attrib[
                "term"
            ]
        except:
            print("NO main categories")
        try:
            categories = entry.xpath('*[local-name()="category"]')
            cat_list = []
            for cat in categories:
                cat_list.append(cat.attrib["term"])
            current["categories"] = cat_list
        except:
            print("NO categories")
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
