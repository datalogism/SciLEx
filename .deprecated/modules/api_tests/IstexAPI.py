#!/usr/bin/env python3
"""
Created on Mon Jan 23 11:04:29 2023

@author: cringwal
"""

import requests
from ratelimit import limits, sleep_and_retry

SAVE = 0
ONE_SEC = 1
MAX_CALLS_PER_SECOND = 3
year = 2017
keyword = "survey relation extraction"
keywords = '"relation extraction" AND survey'
# ti -> title, abs -> abstract, all -> all fields
istex_url = (
    "https://api.istex.fr/document/?q=" + keywords + "&output=*&size=500&from={}"
)


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url)
    return resp


def IstextoZoteroFormat(row):
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

    # Genre pas clair
    zotero_temp["archive"] = "Istex"
    if row["genre"] != "" and len(row["genre"]) == 1:
        if row["genre"][0] == "research-article":
            zotero_temp["itemType"] = "journalArticle"
        if row["genre"][0] == "conference":
            zotero_temp["itemType"] = "conferencePaper"
        if row["genre"][0] == "article":
            zotero_temp["itemType"] = "bookSection"

    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    auth_list = []
    for auth in row["author"]:
        if auth["name"] != "" and auth["name"] is not None:
            auth_list.append(auth["name"])

    if len(auth_list) > 0:
        zotero_temp["authors"] = ";".join(auth_list)

    # NO ABSTRACT ?
    if "abstract" in row and row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]

    if row["arkIstex"] != "" and row["arkIstex"] is not None:
        zotero_temp["archiveID"] = row["arkIstex"]

    if row["publicationDate"] != "" and row["publicationDate"] is not None:
        zotero_temp["date"] = row["publicationDate"]

    if ("doi" in row) and (len(row["doi"]) > 0):
        list_doi = []
        for doi in row["doi"]:
            list_doi.append(doi)
        zotero_temp["DOI"] = ";".join(list_doi)

    if ("language" in row) and (len(row["language"]) == 1):
        zotero_temp["language"] = row["language"][0]

    if "series" in row and len(row["series"].keys()) > 0:
        zotero_temp["series"] = row["series"]["title"]
    if "host" in row:
        if "volume" in row["host"]:
            zotero_temp["volume"] = row["host"]["volume"]

        if "issue" in row["host"]:
            zotero_temp["issue"] = row["host"]["issue"]

        if "title" in row["host"]:
            zotero_temp["journalAbbreviation"] = row["host"]["title"]

        if "pages" in row["host"]:
            if (
                len(row["host"]["pages"].keys()) > 0
                and row["host"]["pages"]["first"] != ""
                and row["host"]["pages"]["last"] != ""
            ):
                p = row["host"]["pages"]["first"] + "-" + row["host"]["pages"]["last"]
                zotero_temp["pages"] = p
        if "publisherId" in row["host"] and len(row["host"]["publisherId"]) == 1:
            zotero_temp["publisher"] = row["host"]["publisherId"][0]
    # NO URL ?
    if "url" in row and row["url"] != "" and row["url"] is not None:
        zotero_temp["url"] = row["url"]

    if row["accessCondition"] != "" and row["accessCondition"] is not None:
        if (
            row["accessCondition"]["contentType"] != ""
            and row["accessCondition"]["contentType"] is not None
        ):
            zotero_temp["rights"] = row["accessCondition"]["contentType"]

    return zotero_temp


page = 0
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = istex_url.format(page)
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["hits"]
    for res in results:
        print(IstextoZoteroFormat(res))

    # next page
    page = page + 500
    total = page_with_results["total"]
    has_more_pages = len(results) == 500
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")
        time_needed = total10 / 60
        print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")
