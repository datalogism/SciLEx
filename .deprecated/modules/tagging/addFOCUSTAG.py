#!/usr/bin/env python3
"""
Created on Fri Sep 29 13:40:09 2023

@author: cringwal
"""

import json
import random
import string

import pandas as pd
import requests
import yaml

############
# SCRIPT FOR TAGGING SPECIFICS ARTICLES FROM CSV FILE OF ID
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


def getitemData(item_key):
    print("HEY")
    url = "https://api.zotero.org/users/5689645"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    return resp


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    data = getitemData(item_key)
    last_v = data["version"]
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


id_file = "/user/cringwal/home/Desktop/THESE/SURVEY/list_focus_FINALE.csv"
df = pd.read_csv(id_file)
patch = True
url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
api_crossref = "https://opencitations.net/index/coci/api/v1/citations/"

TAG = "FOCUS_STUDY_FINAL"
dict_changes = {}

for _index, row in df.iterrows():
    columns = list(row.keys())
    z_id = row[0]
    data = getitemData(z_id)
    tags = data["data"]["tags"]
    tags.append({"tag": TAG})
    changes = {"tags": tags}
    print(z_id)
    if patch:
        patch_withdata(z_id, changes)

    # url="https://api.zotero.org/users/5689645"
    # libs="/collections/"
    # +TAG
    # changes={"tags":tag_changes[z_id]}
    # #patch_withdata(z_id,changes)
