#!/usr/bin/env python3
"""
Created on Fri Apr 12 10:56:39 2024

@author: cringwal
"""

import json
from time import sleep

import requests
from ratelimit import limits, sleep_and_retry

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
    try:
        resp = requests.get(api_citations + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


@sleep_and_retry
@limits(calls=10, period=1)
def getReferences(doi):
    print("REQUEST ref -doi :", doi)
    try:
        resp = requests.get(api_references + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


def getitemVersion(item_key):
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(test)
    resp = test.json()
    version = resp["version"]
    return version


def patch_withreference(item_key, ref_list):
    print("----patch >", item_key)
    print("nb citing = ", len(ref_list["citing"]))
    print("nb cited = ", len(ref_list["cited"]))
    last_v = getitemVersion(item_key)
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps({"extra": str(ref_list)})
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


############## GET ALL PAPERS OF StateOfArtStudy

getDataInit = True
getRefData = True
pushToZotero = True
if getDataInit:
    nb_citation_toget = 0
    keep_citation_data = True
    paper_to_existing_ref = {}
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
                ### CHECK IF IT WORKS BECAUSE I UPDATED IT
                while nb_res > start + 100:
                    print(start)
                    if start != 0:
                        r_items = requests.get(
                            url + libs + key + "/items?limit=100&start=" + str(start),
                            headers=headers,
                        )
                        if r_items.status_code == 200:
                            dict_papers[key]["items"] = (
                                dict_papers[key]["items"] + r_items.json()
                            )
                    start += 100

                for paper in dict_papers[key]["items"]:
                    if "DOI" in paper["data"]:
                        paper_to_existing_ref[paper["data"]["DOI"]] = []
                        if keep_citation_data and "/" in paper["data"]["DOI"]:
                            if (
                                "extra" in paper["data"]
                                and "citing" in paper["data"]["extra"]
                            ):
                                try:
                                    paper_to_existing_ref[paper["data"]["DOI"]] = (
                                        json.loads(
                                            paper["data"]["extra"].replace("'", '"')
                                        )
                                    )
                                except:
                                    print("bad data in extra", paper["data"]["DOI"])
                            else:
                                paper_to_existing_ref[paper["data"]["DOI"]] = []
                            nb_citation_toget += 1
                        elif not keep_citation_data and "/" in paper["data"]["DOI"]:
                            nb_citation_toget += 1
            sleep(3)

#############

if getRefData:
    citations = {}
    zotid_doi = {}
    for coll in dict_papers:
        print("---", dict_papers[coll]["name"])
        items = dict_papers[coll]["items"]
        for paper in items:
            if "DOI" in paper["data"]:
                if "/" in paper["data"]["DOI"]:
                    doi_str = paper["data"]["DOI"]
                    # select=doi_str
                    # doi_str=select
                    item_id = paper["key"]
                    if (
                        doi_str in paper_to_existing_ref
                        and paper_to_existing_ref[doi_str] == []
                    ):
                        zotid_doi[doi_str] = item_id
                        # doi_str="10.18653/v1/2022.findings-acl.67"
                        citation = getCitations(doi_str.replace("https://doi.org/", ""))
                        reference = getReferences(
                            doi_str.replace("https://doi.org/", "")
                        )
                        try:
                            resp_cit = citation.json()
                            if len(resp_cit) > 0:
                                print("HEY")
                                if doi_str not in citations:
                                    citations[doi_str] = {"citing": [], "cited": []}

                                for cit in resp_cit:
                                    citations[doi_str]["citing"].append(cit["citing"])

                                print(
                                    "-", len(citations[doi_str]["citing"]), " citations"
                                )
                        except:
                            print("ERROR API opencitations")
                            # print(citations)

                        try:
                            resp_ref = reference.json()
                            if len(resp_ref) > 0:
                                if doi_str not in citations:
                                    citations[doi_str] = {"citing": [], "cited": []}
                                for ref in resp_ref:
                                    citations[doi_str]["cited"].append(ref["cited"])

                                print("-", len(citations[doi_str]["cited"]), " ref")
                        except:
                            print("ERROR API REF")

                    else:
                        citations[doi_str] = paper_to_existing_ref[doi_str]


####### PUSH to Zotero again
done = []

if pushToZotero:
    for ref in citations:
        if ref in zotid_doi:
            z_id = zotid_doi[ref]
            list_r = citations[ref]
            if (
                z_id not in done
                and len(list_r) > 0
                and ref not in paper_to_existing_ref
                or paper_to_existing_ref[ref] == []
            ):
                patch_withreference(z_id, list_r)
                done.append(z_id)
