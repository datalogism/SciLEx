#!/usr/bin/env python3
"""
Created on Wed Oct 18 18:15:08 2023

@author: cringwal
"""

import json

import requests
import yaml
from ratelimit import limits, sleep_and_retry

############
# SCRIPT FOR CHECKING CITATION NETWORK
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
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


def getitemVersion(item_key, api_key):
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(test)
    resp = test.json()
    version = resp["version"]
    return version


def patch_withreference(item_key, ref_list, api_key):
    print("----patch >", item_key)
    print("nb citing = ", len(ref_list["citing"]))
    print("nb cited = ", len(ref_list["cited"]))
    last_v = getitemVersion(item_key)
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps({"extra": str(ref_list)})
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


doi_str = "10.1609/aaai.v37i13.27084"
citation = getCitations(doi_str.replace("https://doi.org/", ""))
reference = getReferences(doi_str.replace("https://doi.org/", ""))
resp_cit = citation.json()
resp_ref = reference.json()
