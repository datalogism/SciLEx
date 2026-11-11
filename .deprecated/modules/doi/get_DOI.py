#!/usr/bin/env python3
"""
Created on Thu Apr 13 16:26:32 2023

@author: cringwal
"""

import json
import re
import urllib.parse

import requests
import textdistance
import yaml
from ratelimit import limits, sleep_and_retry

############
# SCRIPT FOR GETTING DOI FROM CROSSREF
############


# NOTE: This is a standalone utility script for DOI resolution using Crossref API
# It is NOT part of the main SciLEx collection pipeline
# Crossref API benefits from email for "polite pool" access (50 req/sec vs 1 req/sec)
# See: https://github.com/CrossRef/rest-api-doc#good-manners--more-reliable-service

with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

# Optional email for Crossref API polite pool access
# Set this to your email if you want better Crossref rate limits
# Otherwise, leave as empty string for standard access (1 req/sec)
email = ""  # e.g., "your.email@example.com"


@sleep_and_retry
@limits(calls=100, period=1)
def getDOI_ref(title):
    url = (
        "https://api.crossref.org/works?rows=2&order=desc&sort=score&mailto="
        + email
        + "&select=DOI%2Ctitle&query="
    )
    title_clean = urllib.parse.quote(title)
    title2 = re.sub("[^A-Za-z0-9]+", "", title).lower()
    resp = requests.get(url + title_clean)
    try:
        res = resp.json()
        results = res["message"]["items"]
        for row in results:
            t = row["title"]
            t2 = re.sub("[^A-Za-z0-9]+", "", t[0]).lower()
            dist = textdistance.damerau_levenshtein(title2, t2)
            if dist < 2:
                return row["DOI"]
    except:
        print("PB AFTER REQUEST")
    return False


def getitemVersion(item_key):
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    resp = test.json()
    version = resp["version"]
    return version


def patch_withDOI(item_key, DOI):
    print("HEY")
    last_v = getitemVersion(item_key)
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps({"DOI": str(DOI)})
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


getDataInit = True
getDOIData = True
pushToZotero = False
url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}

if getDataInit:
    keep_citation_data = False
    papers_to_update = {}

    r_collections = requests.get(url + libs + "?limit=100", headers=headers)
    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        data_lib = None
        id_lib = None
        for d in data_collections:
            if d["data"]["name"] == "StateOfArtStudy":
                id_lib = d["data"]["key"]
        lib_list = []
        for d in data_collections:
            if str(d["data"]["parentCollection"]) == str(id_lib):
                lib_list.append(d)

        dict_papers = {}
        for lib in lib_list:
            name = lib["data"]["name"]
            print(name)
            nb_items = lib["meta"]["numItems"]
            key = lib["key"]
            dict_papers[key] = {
                "key": key,
                "nbItems": nb_items,
                "name": name,
                "items": [],
            }
            start = 0
            r_items = requests.get(
                url + libs + key + "/items?limit=100&start=" + str(start),
                headers=headers,
            )
            if r_items.status_code == 200:
                dict_papers[key]["items"] = r_items.json()
                nb_res = int(r_items.headers["Total-Results"])

                while nb_res > start + 100:
                    if start != 0:
                        r_items = requests.get(
                            url + libs + key + "/items?limit=100&start=" + str(start),
                            headers=headers,
                        )
                        if r_items.status_code == 200:
                            dict_papers[key]["items"] = r_items.json()
                    start += 100
                    for paper in dict_papers[key]["items"]:
                        if "DOI" in paper["data"]:
                            # print(paper["data"]["DOI"])
                            if (
                                from src.constants import is_valid
                                not is_valid(paper.get("data", {}).get("DOI"))
                            ) and "/" not in paper["data"]["DOI"]:
                                papers_to_update[paper["key"]] = {
                                    "title": paper["data"]["title"],
                                    "DOI": None,
                                }


if getDOIData:
    print(">>>>>>>>>", len(list(papers_to_update.keys())), " PAPERS TO UPDATE")
    nb_to_rq = len([k for k in papers_to_update if papers_to_update[k]["DOI"] is None])
    print(">>>>", nb_to_rq, " PAPERS TO RQ AGAIN")
    n = 0
    for k in papers_to_update:
        print(papers_to_update[k]["DOI"])
        if papers_to_update[k]["DOI"] is None:
            print("-", n, "/", nb_to_rq)
            n += 1
            DOI = getDOI_ref(papers_to_update[k]["title"])
            print(DOI)
            if DOI:
                papers_to_update[k]["DOI"] = DOI
            else:
                papers_to_update[k]["DOI"] = "not found"
            ##### AND SAVE
            patch_withDOI(k, papers_to_update[k]["DOI"])


####### PUSH to Zotero again
# if pushToZotero==True:
#   for z_id in papers_to_update.keys():
#       z_id=zotid_doi[ref]
#       list_r=references[ref]
#       if(len(list_r)>0 and ref not in paper_to_existing_ref.keys() or paper_to_existing_ref[ref]==[]):
#          patch_withreference(z_id,list_r)
