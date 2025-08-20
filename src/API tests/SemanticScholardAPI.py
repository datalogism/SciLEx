#!/usr/bin/env python3
"""
Created on Fri Dec 16 16:21:32 2022

@author: cringwal
"""

import json
import os
from datetime import date

import requests
import yaml
from ratelimit import limits, sleep_and_retry

SAVE = 0
ONE_SEC = 1
MAX_CALLS_PER_SECOND = 100
# keyword="'relation extraction' AND survey"
keyword = "The R book"
year = 2010
sem_scholar_url = (
    "https://api.semanticscholar.org/graph/v1/paper/search?query=title:"
    + keyword
    + "&fieldsOfStudy=Computer Science,Linguistics,Mathematics&fields=title,abstract,url,venue,publicationVenue,citationCount,externalIds,referenceCount,s2FieldsOfStudy,publicationTypes,publicationDate,isOpenAccess,openAccessPdf,authors,journal,fieldsOfStudy&year="
    + str(year)
    + "&limit=100&offset={}"
)
last_page = 0

with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    API_key = cfg["sem_scholar"]["api_key"]


#     earch = "artificial intelligence+Deep Learning"

# or if you want to exclude some, use the - to exclude:

#     search = "artificial intelligence-application"


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=ONE_SEC)
def access_rate_limited_api(url):
    resp = requests.get(url, headers={"x-api-key": API_key})
    return resp


def SemanticScholartoZoteroFormat(row):
    # bookSection?
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

    zotero_temp["archive"] = "Semantic Scholar"
    #### publicationTypes is a list Zotero only take one value
    if row["publicationTypes"] != "" and row["publicationTypes"] is not None:
        if len(row["publicationTypes"]) == 1:
            if row["publicationTypes"][0] == "JournalArticle":
                zotero_temp["itemType"] = "journalArticle"

            if row["publicationTypes"][0] == "Conference":
                zotero_temp["itemType"] = "conferencePaper"

            if row["publicationTypes"][0] == "Book":
                zotero_temp["itemType"] = "book"
        if len(row["publicationTypes"]) > 1:
            if "Book" in row["publicationTypes"]:
                zotero_temp["itemType"] = "book"
            if "Conference" in row["publicationTypes"]:
                zotero_temp["itemType"] = "conferencePaper"

    if row["publicationVenue"] != "" and row["publicationVenue"] is not None:
        if "type" in row["publicationVenue"] and row["publicationVenue"]["type"] != "":
            if row["publicationVenue"]["type"] == "journal":
                zotero_temp["itemType"] = "journalArticle"
                if row["publicationVenue"]["name"] != "":
                    zotero_temp["journalAbbreviation"] = row["publicationVenue"]["name"]
            if row["publicationVenue"]["type"] == "conference":
                zotero_temp["itemType"] = "conferencePaper"
                if row["publicationVenue"]["name"] != "":
                    zotero_temp["conferenceName"] = row["publicationVenue"]["name"]

    if row["journal"] != "" and row["journal"] is not None:
        if "pages" in row["journal"] and row["journal"]["pages"] != "":
            zotero_temp["pages"] = row["journal"]["pages"]
            if zotero_temp["itemType"] == "book":
                zotero_temp["itemType"] = "bookSection"
        if "name" in row["journal"] and row["journal"]["name"] != "":
            zotero_temp["journalAbbreviation"] = row["journal"]["name"]
        if "volume" in row["journal"] and row["journal"]["volume"] != "":
            zotero_temp["volume"] = row["journal"]["volume"]

    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]
    auth_list = []
    for auth in row["authors"]:
        if auth["name"] != "" and auth["name"] is not None:
            auth_list.append(auth["name"])
    if len(auth_list) > 0:
        zotero_temp["authors"] = ";".join(auth_list)

    if row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]

    if row["paperId"] != "" and row["paperId"] is not None:
        zotero_temp["archiveID"] = row["paperId"]

    if row["publicationDate"] != "" and row["publicationDate"] is not None:
        zotero_temp["date"] = row["publicationDate"]

    if "DOI" in row["externalIds"]:
        zotero_temp["DOI"] = row["externalIds"]["DOI"]

    if row["url"] != "" and row["url"] is not None:
        zotero_temp["url"] = row["url"]
    if row["isOpenAccess"] != "" and row["isOpenAccess"] is not None:
        zotero_temp["rights"] = row["isOpenAccess"]

    return zotero_temp


################################## GET COLLECT ID
if SAVE:
    file_collect = "/user/cringwal/home/Desktop/THESE YEAR1/SAT/DATA/collect_dict.json"
    with open(file_collect) as json_file:
        data_coll = json.load(json_file)

    id_collect = 0
    max_id = 0
    for k in data_coll:
        if (
            data_coll[k]["API"] == "SemanticScholar"
            and data_coll[k]["kwd"] == keyword
            and data_coll[k]["year"] == str(year)
        ):
            id_collect = str(k)
            last_page = data_coll[k]["last_page"]
        max_id = max(int(k), max_id)

    if id_collect == 0:
        if id_collect == 0 and max_id != 0:
            id_collect = str(max_id + 1)
            data_coll[id_collect] = {
                "API": "SemanticScholar",
                "kwd": keyword,
                "year": str(year),
                "last_page": 0,
                "complete": 0,
            }
        if id_collect == 0 and max_id == 0:
            data_coll["0"] = {
                "API": "SemanticScholar",
                "kwd": keyword,
                "year": str(year),
                "last_page": 0,
                "complete": 0,
            }

        with open(file_collect, "w") as json_file:
            json.dump(data_coll, json_file)

############################ CREATE DIRECTORY IF NEEEDED
if SAVE:
    current_dir = "/user/cringwal/home/Desktop/THESE YEAR1/SAT/DATA/SemanticScholar/"
    if not os.path.isdir(current_dir + str(id_collect)):
        os.makedirs(current_dir + str(id_collect))


page = last_page + 1
has_more_pages = True
fewer_than_10k_results = True

while has_more_pages and fewer_than_10k_results:
    url = sem_scholar_url.format(page)
    global_data = {
        "date_search": str(date.today()),
        "id_collect": id_collect,
        "page": page,
        "total_nb": 0,
        "results": [],
    }
    print("\n" + url)

    response = access_rate_limited_api(url)
    page_with_results = response.json()

    # loop through partial list of results
    results = page_with_results["data"]
    for result in results:
        global_data["results"].append(result)
        SemanticScholartoZoteroFormat(result)

    total = int(page_with_results["total"])
    global_data["total_nb"] = total

    if SAVE:
        with open(
            current_dir + str(id_collect) + "/page_" + str(page), "w", encoding="utf8"
        ) as json_file:
            json.dump(global_data, json_file)

        with open(file_collect) as json_file:
            data_coll = json.load(json_file)
        data_coll[id_collect]["last_page"] = page
        with open(file_collect, "w") as json_file:
            json.dump(data_coll, json_file)

    page = page_with_results["next"]
    has_more_pages = len(results) == 100
    fewer_than_10k_results = total <= 10000
    print(">>>>>", page, "/", total)

    time_needed = total / 100 / 60 / 60
    print("TOTAL EXTRACTION WILL NEED >", time_needed, "minutes")

    if not fewer_than_10k_results:
        print("QUERY TOO LARGE MUST BE REVIEWED")

if (not has_more_pages) and SAVE:
    with open(file_collect) as json_file:
        data_coll = json.load(json_file)
    data_coll[id_collect]["complete"] = 1
    with open(file_collect, "w") as json_file:
        json.dump(data_coll, json_file)
