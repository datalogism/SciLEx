#!/usr/bin/env python3
"""
Created on Thu Apr 13 16:26:32 2023

@author: cringwal
"""

import json

import pandas as pd
import requests
import yaml

############
# SCRIPT FOR GETTINGS TAGS VIA GROUP
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getitemVersion(item_key):
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    resp = test.json()
    version = resp["version"]
    return version


def getitemData(item_key):
    print("HEY")
    url = "https://api.zotero.org/groups/5259782/"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    return resp


def patch_withdata(item_key, data_dict):
    url = "https://api.zotero.org/groups/5259782/"
    print("----patch >", item_key)
    data = getitemData(item_key)
    last_v = data["version"]
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


getDataInit = False
pushToZotero = False
url = "https://api.zotero.org/groups/5259782/"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}

file = "/user/cringwal/home/Desktop/THESE/SURVEY/TAG_LIST_FINAL.csv"
df = pd.read_csv(file)
tags_tofill_bytype = {"models": [], "surveys": [], "datasets": []}
for _index, row in df.iterrows():
    if "X" in str(row["models"]).upper():
        tags_tofill_bytype["models"].append(row["tag"])

    if "X" in str(row["surveys"]).upper():
        tags_tofill_bytype["surveys"].append(row["tag"])

    if "X" in str(row["datasets"]).upper():
        tags_tofill_bytype["datasets"].append(row["tag"])


if getDataInit:
    keep_citation_data = False
    papers_to_update = {}

    r_collections = requests.get(url + libs + "?limit=100", headers=headers)
    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        data_lib = None
        id_lib = None
        lib_list = []
        for d in data_collections:
            lib_list.append(d)

        dict_papers = {}
        for lib in lib_list:
            name = lib["data"]["name"]
            papers_to_update[name] = {}
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
                        if (
                            paper["data"]["itemType"] != "attachment"
                            and "title" in paper["data"]
                        ):
                            tags = paper["data"]["tags"]
                            tags_corr = [item["tag"].upper() for item in tags]
                            tags_todo = []
                            for todo in tags_tofill_bytype[name]:
                                found = False
                                for tag_in in tags_corr:
                                    if todo in tag_in:
                                        found = True
                                if not found:
                                    tags_todo.append(todo)

                            if len(tags_todo) > 0:
                                papers_to_update[name][paper["key"]] = tags_todo
for name in papers_to_update:
    print(name)
    for z_id in papers_to_update[name]:
        paper_info = getitemData(z_id)
        tags = paper_info["data"]["tags"]
        for todo in papers_to_update[name][z_id]:
            TAG = todo + ":?"
            tags.append({"tag": TAG})
        changes = {"tags": tags}
        # print(changes)
        # if(patch==True):
        #    print(patch)
        patch_withdata(z_id, changes)
