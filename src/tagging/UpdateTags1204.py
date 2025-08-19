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


url = "https://api.zotero.org/groups/5259782/collections/8G5JB9UZ/"
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


updates = {}
for p in all_data:
    z_id = p["key"]
    changes = {"tags": p["data"]["tags"]}
    patch_withdata(z_id, changes)


tags_list = []
for p in all_data:
    if "tags" in p["data"]:
        tags = [t["tag"].upper() for t in p["data"]["tags"]]
        tags_prefix = [t.split(":")[0] for t in tags]
        for t in tags_prefix:
            if t not in tags_list:
                tags_list.append(t)


to_keep_list = [
    "SAT_DOMAIN",
    "SAT_GRANULARITY",
    "SAT_LANG",
    "SAT_MODEL",
    "SAT_TASK",
    "SAT_ARCHI",
    "SAT_BASELINE",
    "SAT_DATASET",
    "SAT_LEARNING",
    "SAT_FEATURES",
    "SAT_NEGATIVEEXAMPLES",
    "SAT_DECODING",
    "SAT_LOSS",
    "SAT_COST_EVAL",
    "SAT_OUTPUT",
]
to_add_list = ["1_SPECIFIC_REL_TYPE", "N_OBJECT_PROP", "N_DATATYPE_PROP", "PROMPT_TYPE"]
to_delete_list = [
    "SAT_METHOD_GENERATION",
    "SAT_METHOD_SELECTION",
    "SAT_DATATYPES_PROP",
    "SAT_NBENTITY",
    "SAT_NBEVALEX",
    "SAT_REL_TYPE",
    "SAT_NBEXPOSITIVE",
    "SAT_NBIMAGES",
    "SAT_NBNEGATIVEEXAMPLES",
    "SAT_NBPARAGRAPH",
    "SAT_NBSENT",
    "SAT_NBTABLES",
    "SAT_NBTESTEX",
    "SAT_NBTRAINEX",
    "SAT_NBTRIPLES",
    "SAT_NBTYPES_ENTITY",
    "SAT_NBTYPES_RELATIONS",
    "SAT_CONTEXT",
    "SAT_NBDOC",
    "SAT_5STARS",
    "SAT_FOCUS",
    "SAT_EXTEND",
    "FOCUS_STUDY",
    "FOCUS_STUDY_FINAL",
    "EXAMPLE",
    "SAT_CROSSVALIDATION",
    "SAT_METRIC",
    "SAT_NBDATASET",
    "SAT_NBMODEL_COMPARED",
    "FOCUS_EXAMPLE",
    "SAT_OLDTAG",
    "SAT",
    "SAT_MODEL_COMPARE",
    "SAT_OPTI",
    "SAT_OPTI_DROPOUT",
    "SAT_OPTI_LR",
    "SAT_RQ",
    "SAT_SPLIT_DATA_EVAL",
    "SAT_SPLIT_DATA_TEST",
    "SAT_SPLIT_DATA_TRAIN",
    "SAT_CLARITY",
    "FOCUS_STUDY_OCT",
    "SAT_MULTICOMPONENTS",
    "SAT_OPTI_SCH",
    "SAT_OPTI_STEPS",
    "SAT_OPTI_WEIGHT_DECAY",
    "SAT_NBEVALEX_INST",
    "SAT_NBEVALEX_TRIPLE",
    "SAT_NBTESTEX_INST",
    "SAT_NBTESTEX_TRIPLE",
    "SAT_NBTRAINEX_INST",
    "SAT_NBTRAINEX_TRIPLE",
    "SAT_OPTI_EPOCH",
    "SAT_OPTI_WARMUP",
    "SAT__FEATURE",
    "SAT_EXTENDABLE",
    "CONTEXTUALIZED REPRESENTATION",
    "KNOWLEDGE GRAPH COMPLETION",
    "KNOWLEDGE GRAPH EMBEDDING",
    "LINK PREDICTION",
    "STRUCTURED KNOWLEDGESAT_ALL_CHECKED",
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
