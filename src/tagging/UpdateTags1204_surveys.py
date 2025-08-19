#!/usr/bin/env python3
"""
Created on Fri Apr 12 11:51:36 2024

@author: cringwal
"""

import json

import requests
import yaml

############
# SCRIPT FOR MANAGING TAGS CREATED : DELETION - ADD - TO KEEP
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getitemData(item_key):
    print("HEY")
    url = "https://api.zotero.org/groups/5259782"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    return resp


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    url = "https://api.zotero.org/groups/5259782"
    data = getitemData(item_key)
    last_v = data["version"]
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


def getValNormalized(tag, val):
    val_2 = "".join(x for x in val.title() if not x.isspace())
    return tag + val_2


url = "https://api.zotero.org/groups/5259782/collections/B2ZVKHEP/"
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

### REINIT IF NEED
# for p in all_data:
#     z_id=p["key"]
#     changes={"tags":p["data"]["tags"]}
#     patch_withdata(z_id,changes)


tags_list = []
for p in all_data:
    if "tags" in p["data"]:
        tags = [t["tag"].upper() for t in p["data"]["tags"]]
        tags_prefix = [t.split(":")[0] for t in tags]
        for t in tags_prefix:
            if t not in tags_list:
                tags_list.append(t)


to_keep_list = [
    "SAT_ARCHI",
    "SAT_LANG",
    "SAT_DOMAIN",
    "SAT_FOCUS_PERIOD",
    "SAT_GRANULARITY",
    "SAT_MODEL",
    "SAT_TASK",
    "SAT_DATASET",
    "SAT_LEARNING",
]
to_add_list = ["SAT_PTM", "BIBLIO_METHODOBENCHMARK"]
to_delete_list = [
    "SAT_BENCHMARK_TYPE",
    "SAT_CONTEXT",
    "SAT_DEFINED_PROTOCOL",
    "SAT_FOCUS",
    "SAT_INTEREST",
    "SAT_NBDATASET",
    "SAT_NBMODEL",
    "SAT_REL_TYPE",
    "SAT_TYPE",
    "SAT_TYPOLOGY_DIM",
    "CHECKED1023",
    "SAT_TAXONOMY",
    "SAT_RQ",
    "EXCLUDED",
    "NEW",
    "NEW_CITATIONS",
    "PWC_TASK",
    "A.1",
    "COMPUTER SCIENCE - COMPUTATION AND LANGUAGE",
    "COMPUTER SCIENCE - ARTIFICIAL INTELLIGENCE",
    "HERE",
    "DONTHAVECODE",
    "NOTBENCHMARKED",
    "ACM",
    "HAVECODE",
    "HUMAN EVOLUTION",
    "INFORMATION OVERLOAD",
    "INFORMATION TECHNOLOGY EVOLUTION",
    "KNOWLEDGE ACQUISITION",
    "PROPAGATION SCHOLARLY ERRORS",
    "SEMANTIC WEB",
    "TECHNOLOGICAL FORECASTING",
    "WORLD WIDE WEB",
    "MANUALMODELS",
    "COMPUTER SCIENCE - INFORMATION RETRIEVAL",
    "SAT_TYPOLOGY",
    "SAT_NBTYPES_ENTITY",
    "SAT_SOURCE",
]

updates = {}
for p in all_data:
    z_id = p["key"]
    temp = {"to_add": [], "to_delete": []}
    change = False
    if "tags" in p["data"]:
        tags = [t["tag"] for t in p["data"]["tags"]]
        tags2 = []
        tags_prefix = [t.split(":")[0] for t in tags]
        for t in to_keep_list:
            if t not in tags_prefix:
                # print("ADD >",t)
                change = True
                temp["to_add"].append(t + ":?")
        for t in to_add_list:
            if t not in tags_prefix:
                # print("ADD >",t)
                change = True
                temp["to_add"].append(t + ":?")
        for t in to_delete_list:
            if t + ":?" in tags:
                temp["to_delete"].append(t + ":?")
                change = True
    if change:
        tags2 = []
        for t in tags:
            if t not in temp["to_delete"]:
                tags2.append(t)

        for t in temp["to_add"]:
            tags2.append(t)
        updates[z_id] = tags2

for zid in updates:
    print(zid)
    data = getitemData(zid)
    changes = {"tags": []}
    for TAG in updates[zid]:
        changes["tags"].append({"tag": TAG})
    if len(changes["tags"]) > 0:
        print(changes["tags"])
        try:
            patch_withdata(zid, changes)
        except:
            print("PB")
