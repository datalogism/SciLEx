#!/usr/bin/env python3
"""
Created on Wed Nov 29 15:50:09 2023

@author: cringwal
"""

import json
import logging
import random
import string
from datetime import datetime

############
# SCRIPT FOR REPLACING TAGS DEPENDING OF CHANGES DEFINED IN A FILE
############
import pandas as pd
import requests

from src.crawlers.utils import load_all_configs

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

user_id = api_config["Zotero"]["user_id"]
user_role = api_config["Zotero"]["user_mode"]
api_key = api_config["Zotero"]["api_key"]
research_coll = main_config["collect_name"]


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


def getitemData(item_key):
    print("HEY")
    url = None
    resp = "No URL"
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id)
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id)
    if url:
        headers = {"Zotero-API-Key": api_key}
        test = requests.get(
            url + "/items/" + item_key + "?format=json", headers=headers
        )
        print(">", test)
        resp = test.json()
    return resp


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    url = None
    resp = "No URL"
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id)
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id)
    if url:
        data = getitemData(item_key)
        last_v = data["version"]
        headers = {
            "Zotero-API-Key": api_key,
            "If-Unmodified-Since-Version": str(last_v),
        }
        body = json.dumps(data_dict)
        resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
        return resp.status_code
    else:
        return resp


def getValNormalized(val):
    val_2 = "".join(x for x in val.title() if not x.isspace())
    return val_2


if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info(f"Systematic review search started at {datetime.now()}")
    logging.info("================BEGIN Systematic Review Search================")
    type = "datasets"
    user_id = api_config["Zotero"]["user_id"]
    user_role = api_config["Zotero"]["user_mode"]
    api_key = api_config["Zotero"]["api_key"]
    research_coll = main_config["collect_name"]

    research_coll = "datasets"
    file = "/home/cringwal/PycharmProjects/SciLEx/src/output/relationExtraction_new/tag_FOCUS.csv"
    df = pd.read_csv(file)
    tags_tofill_bytype = {"models": [], "surveys": [], "datasets": []}
    for _index, row in df.iterrows():
        if "X" in str(row["models"]).upper():
            tags_tofill_bytype["models"].append(row["tag"].upper())

        if "X" in str(row["surveys"]).upper():
            tags_tofill_bytype["surveys"].append(row["tag"].upper())

        if "X" in str(row["datasets"]).upper():
            tags_tofill_bytype["datasets"].append(row["tag"].upper())

    papers_to_update = {type: {}}

    headers = {"Zotero-API-Key": api_key}
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id) + "/collections"
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id) + "/collections"
    r_collections = requests.get(url + "?limit=100?start=0", headers=headers)

    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        current_col_key = None
        print(data_collections)
        papers_by_coll = {}
        exits_url = []
        found = False
        lib = None
        for d in data_collections:
            print(d["data"])
            if d["data"]["name"] == research_coll:
                print("FOUND current Collection >", d["data"]["name"])
                # lib = d
                current_col_key = d["data"]["key"]
                break
        if current_col_key:
            print("YEA")

            if user_role == "group":
                url2 = (
                    "https://api.zotero.org/groups/"
                    + str(user_id)
                    + "/collections/"
                    + str(current_col_key)
                )
            elif user_role == "user":
                url2 = (
                    "https://api.zotero.org/users/"
                    + str(user_id)
                    + "/collections/"
                    + str(current_col_key)
                )

            headers = {"Zotero-API-Key": api_key}
            start = 0
            all_data = []
            continue_ = True
            while continue_:
                print("HEY >", start)
                r_items = requests.get(
                    url2 + "/items/top?limit=100&start=" + str(start), headers=headers
                )
                data_current = r_items.json()
                start += 100
                if len(data_current) == 0:
                    continue_ = False
                all_data += data_current

        for paper in all_data:
            if paper["data"]["itemType"] != "attachment" and "title" in paper["data"]:
                tags = paper["data"]["tags"]
                tags_corr = []
                for tagggg in tags:
                    item = tagggg["tag"]
                    if "?" not in item:
                        tag_part = item.split(":")
                        dim = tag_part[0].upper()
                        if dim in tags_tofill_bytype[type]:
                            val = getValNormalized(tag_part[1])
                            new = dim + ":" + val
                            new = new.strip()
                            if new not in tags_corr:
                                tags_corr.append(new)

                for todo in tags_tofill_bytype[type]:
                    found = False
                    for tag_in in tags_corr:
                        if todo in tag_in:
                            found = True
                    if not found:
                        tags_corr.append(todo + ":?")

                if len(tags_corr) > 0:
                    papers_to_update[type][paper["key"]] = tags_corr
        print(papers_to_update)

    for lib in papers_to_update:
        print(lib)
        if lib == "datasets":
            for zid in papers_to_update[lib]:
                print(papers_to_update[lib][zid])
                data = getitemData(zid)
                changes = {"tags": []}
                for TAG in papers_to_update[lib][zid]:
                    changes["tags"].append({"tag": TAG})
                if len(changes["tags"]) > 0:
                    print(changes["tags"])
                    try:
                        patch_withdata(zid, changes)
                    except:
                        print("PB")
