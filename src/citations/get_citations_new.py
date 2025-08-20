#!/usr/bin/env python3
"""
Created on Fri Apr 12 10:56:39 2024

@author: cringwal
"""

import json
import logging
import random
import string
import sys

import requests
from ratelimit import limits, sleep_and_retry

from src.crawlers.utils import load_all_configs

############
# SCRIPT FOR QUERYING OPENCITATION AND SAVING IT TO ZOTERO
############


# with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml", "r") as ymlfile:
#    cfg = yaml.load(ymlfile)
#    collect_dir=cfg["collect"]["dir"]
#    api_key=cfg["zotero"]["api_key"]

# url="https://api.zotero.org/groups/5259782"
# libs="/collections/"
# headers={'Zotero-API-Key':api_key}
api_citations = "https://opencitations.net/index/coci/api/v1/citations/"
api_references = "https://opencitations.net/index/coci/api/v1/references/"


@sleep_and_retry
@limits(calls=10, period=1)
def getCitations(doi):
    print("REQUEST citations -doi :", doi)
    resp = None
    try:
        resp = requests.get(api_citations + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


@sleep_and_retry
@limits(calls=10, period=1)
def getReferences(doi):
    print("REQUEST ref -doi :", doi)
    resp = None
    try:
        resp = requests.get(api_references + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


def getitemVersion(url, api_key, item_key):
    print("INSIDE")
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    # print(test)
    resp = test.json()
    # print(len(resp))
    # print(resp)
    version = resp["version"]
    return version


def patch_withreference(url, api_key, item_key, ref_list):
    print("----patch >", item_key)
    print("nb citing = ", len(ref_list["citing"]))
    print("nb cited = ", len(ref_list["cited"]))
    last_v = getitemVersion(url, api_key, item_key)
    print(">>>>>>> last v")
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps({"extra": str(ref_list)})
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


############## GET ALL PAPERS OF StateOfArtStudy

logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log message format
    datefmt="%Y-%m-%d %H:%M:%S",  # Date format
)

# Define the configuration files to load
config_files = {
    "main_config": "../scilex.config.yml",
    "api_config": "../api.config.yml",
}
print("HEY")
# Load configurations
configs = load_all_configs(config_files)

# Access individual configurations
main_config = configs["main_config"]
api_config = configs["api_config"]


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info("================BEGIN Annotation Agreements================")

    user_id = api_config["Zotero"]["user_id"]
    user_role = api_config["Zotero"]["user_mode"]
    api_key = api_config["Zotero"]["api_key"]

    selected_libs = ["datasets", "models", "surveys"]

    # sys.exit()
    print("DONE")
    # as such, all entries are considered to be relevant
    templates_dict = {}

    libs = "/collections"
    lib_list = {}
    lib_ids = {}

    # users / "+str(user_id)+"
    # url="https://api.zotero.org/users/"+str(user_id)+libs
    headers = {"Zotero-API-Key": api_key}
    current_col_key = None
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id) + "/collections"
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id) + "/collections"
    if user_role == "group":
        url2 = "https://api.zotero.org/groups/" + str(user_id) + "/"
    elif user_role == "user":
        url2 = "https://api.zotero.org/users/" + str(user_id) + "/"
    print("BEFORE")
    found_parent_id = {}
    r_collections = requests.get(url + "?limit=1000?start=0", headers=headers)
    print(">>>>>>>>>>>>>>>>>>>>>>> GET COLLECTIONS DATA")
    print(r_collections.status_code)
    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        found_parent = False
        # print(data_collections.keys())

        # nb_res = int(r_items.headers["Total-Results"])
        # prin()
        papers_by_coll = {}
        coll_name_id = {}
        exits_url = []
        lib = None
        for d in data_collections:
            print(d["data"])
            if d["data"]["name"] in selected_libs:
                papers_by_coll[d["data"]["name"]] = []
                print("FOUND current Collection >", d["data"]["name"])
                coll_name_id[d["data"]["name"]] = d["data"]["key"]
                # lib_ids[key] = d
    print("GET articles ")
    nb_citation_toget = 0
    paper_to_existing_ref = {}

    zotid_doi = {}
    zotid_coll = {}
    for ck in coll_name_id:
        print(">>>>>>>>>>>>>>>>>>>>>>> CK: ", ck)
        lib_key = coll_name_id[ck]
        start = 0
        apicurl = url + "/" + lib_key + "/items?limit=100&start=" + str(start)
        r_items = requests.get(apicurl, headers=headers)

        if r_items.status_code == 200:
            papers_by_coll[ck] = r_items.json()
            print("FOUND ITEMS")
            nb_res = int(r_items.headers["Total-Results"])
            ### CHECK IF IT WORKS BECAUSE I UPDATED IT
            while nb_res > start + 100:
                print(start)
                if start != 0:
                    apicurl = (
                        url + "/" + lib_key + "/items?limit=100&start=" + str(start)
                    )
                    r_items = requests.get(apicurl, headers=headers)
                    if r_items.status_code == 200:
                        papers_by_coll[ck] = papers_by_coll[ck] + r_items.json()
                start += 100

        # sleep(3)
        for paper in papers_by_coll[ck]:
            if "DOI" in paper["data"] and "/" in paper["data"]["DOI"]:
                doi_str = paper["data"]["DOI"]
                item_id = paper["key"]
                zotid_coll[item_id] = lib_key
                zotid_doi[doi_str] = item_id
                nb_citation_toget += 1
    print(nb_citation_toget)
    print(">>>>>>>>>>>>>>>>>>>>>>> NOW GET CITATION NETWORK")

    for DOI in zotid_doi:
        print(DOI)
        z_id = zotid_doi[DOI]
        z_coll = zotid_coll[z_id]

        citations = {"citing": [], "cited": []}
        citation_local = getCitations(DOI.replace("https://doi.org/", ""))
        references_local = getReferences(DOI.replace("https://doi.org/", ""))
        if citation_local:
            resp_cit = citation_local.json()
            if len(resp_cit) > 0:
                for cit in resp_cit:
                    citations["citing"].append(cit["citing"])

                print("-", len(citations["citing"]), " citations")
        if references_local:
            resp_ref = references_local.json()
            if len(resp_ref) > 0:
                for ref in resp_ref:
                    citations["cited"].append(ref["cited"])

                print("-", len(citations["cited"]), " ref")
        try:
            url3 = url + "/" + z_coll
            print(url3)
            test = patch_withreference(url2, api_key, z_id, citations)
        except:
            print("EROOR")
            sys.exit()
