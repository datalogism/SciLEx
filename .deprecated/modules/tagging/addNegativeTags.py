#!/usr/bin/env python3
"""
Created on Thu Sep 28 11:00:25 2023

@author: cringwal
"""

import json
import random
import string
from time import sleep

import requests
import yaml

############
# SCRIPT FOR SELECTING A TAGG AND ADD A SPECIFIC NEGEATIVE TAG IF NOT ATTACHED
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
api_crossref = "https://opencitations.net/index/coci/api/v1/citations/"


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


def getitemData(
    item_key,
):
    print("HEY")
    url = "https://api.zotero.org/users/5689645"
    api_key = "jP0akBLAcUhBFHDX2xnCAy0e"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    print(resp)
    version = resp["version"]
    return version


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    last_v = getitemVersion(item_key, "version")
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


getDataInit = True
getDataChanges = True
attachTag = False
if getDataInit:
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

            sleep(3)

target_tag = "SAT_task:RE"
negative_tag = "SAT_task:RE_NO"
if getDataChanges:
    tag_changes = {}
    for item in dict_papers["DHHJ7YZF"]["items"]:  # DHHJ7YZF for models only
        z_id = item["key"]
        data = item["data"]
        tags = data["tags"]
        have_target = False
        for t in tags:
            if t["tag"] == target_tag:
                have_target = True
        if not have_target:
            temp_tags = tags
            temp_tags.append({"tag": negative_tag})
            tag_changes[z_id] = temp_tags

if attachTag:
    for z_id in tag_changes:
        print(z_id)
        url = "https://api.zotero.org/users/5689645"
        libs = "/collections/"
        changes = {"tags": tag_changes[z_id]}
        patch_withdata(z_id, changes)
