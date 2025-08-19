#!/usr/bin/env python3
"""
Created on Mon Apr 15 17:36:05 2024

@author: cringwal
"""

import json

import requests
import yaml
from SPARQLWrapper import SPARQLWrapper

############
# SCRIPT FOR GETTING ABSTRACT FROM linkedpaperswithcode
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getitemData(item_key, api_key):
    print("HEY")
    url = "https://api.zotero.org/groups/5259782"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    return resp


def patch_withdata(item_key, data_dict, api_key):
    print("----patch >", item_key)
    url = "https://api.zotero.org/groups/5259782"
    data = getitemData(item_key)
    last_v = data["version"]
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


url = "https://api.zotero.org/groups/5259782/collections/242BEP5Z/"
libs = "/items"
headers = {"Zotero-API-Key": api_key}

start = 0
all_data = []
continue_ = True
while continue_:
    print("HEY >", start)
    r_items = requests.get(
        url + "/items/top?limit=100&start=" + str(start), headers=headers
    )
    data_current = r_items.json()
    if len(data_current) == 0:
        continue_ = False
    all_data += data_current
    start += 100

dict_meta_data = {}

for p in all_data:
    z_id = p["key"]

    if "DOI" in p["data"]:
        doi = p["data"]["DOI"]
        results = requests.get("https://api.crossref.org/works/" + doi)
        try:
            data_res = results.json()
            dict_meta_data[z_id] = data_res
        except:
            print("ERROR with ", doi)

dict_abstract_data = {}
for k in dict_meta_data:
    if "abstract" in dict_meta_data[k]["message"]:
        print("YEAH")
        dict_abstract_data[k] = (
            dict_meta_data[k]["message"]["abstract"]
            .replace("</jats:p>", "")
            .replace("<jats:p>", "")
        )


sparql = SPARQLWrapper("https://linkedpaperswithcode.com/sparql")

for p in all_data:
    z_id = p["key"]
    if z_id not in dict_abstract_data:
        prefix_pwc_url = "https://paperswithcode.com/"
        pwc_url = p["data"]["archive"]
        if prefix_pwc_url in pwc_url:
            lp_id = pwc_url.replace(prefix_pwc_url, "https://linkedpaperswithcode.com/")
            print(lp_id)

            sparql.setReturnFormat("json")
            sparql.setQuery(
                """
             PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
            PREFIX dcterms: <http://purl.org/dc/terms/>
                                 select ?id ?abstract where {
                                  <"""
                + lp_id
                + """> dcterms:abstract ?abstract
                                 }
             """
            )
            ret = sparql.query()
            d = ret.convert()
            print(d["results"]["bindings"])
            if len(d["results"]["bindings"]) > 0:
                dict_abstract_data[k] = d["results"]["bindings"][0]["abstract"]["value"]
                print("======================================")

for z_id in dict_abstract_data:
    data = getitemData(z_id, api_key)
    changes = {"abstractNote": dict_abstract_data[z_id]}
    print("=============")
    print(z_id)
    print(changes)
    patch_withdata(z_id, changes, api_key)
