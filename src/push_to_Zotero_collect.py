#!/usr/bin/env python3
"""
Created on Mon Jan 30 16:06:58 2023

@author: cringwal
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import logging
import os
import random
import string
from datetime import datetime

import pandas as pd
import requests

from src.crawlers.utils import load_all_configs

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log message format
    datefmt="%Y-%m-%d %H:%M:%S",  # Date format
)

# Define the configuration files to load
config_files = {
    "main_config": "scilex.config.yml",
    "api_config": "api.config.yml",
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


def get_zotero_user_id(api_key):
    """Get Zotero user ID from the API using the provided API key."""
    try:
        headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "SciLEx/1.0"}
        response = requests.get("https://api.zotero.org/keys/current", headers=headers)
        response.raise_for_status()

        key_info = response.json()
        user_id = str(key_info["userID"])
        logging.info(f"Retrieved Zotero user ID: {user_id}")
        return user_id
    except Exception as e:
        logging.error(f"Failed to get Zotero user ID: {e}")
        raise


if __name__ == "__main__":
    # Log the overall process with timestamps
    logging.info(f"Systematic review search started at {datetime.now()}")
    logging.info("================BEGIN ZOTERO PUSH================")

    api_key = api_config["zotero"]["api_key"]
    user_role = api_config["zotero"]["user_mode"]
    user_id = get_zotero_user_id(api_key)
    research_coll = main_config["collect_name"]

    dir_collect = os.path.join(main_config["output_dir"], main_config["collect_name"])
    research_coll = "DatasetSurveys"
    aggr_file = main_config["aggregate_file"]

    print(dir_collect)
    # collect_dir="/user/cringwal/home/Desktop/THESE YEAR1/SAT/"+research_coll
    # file_to_push=os.path.join(dir_collect,aggr_file)
    # print(file_to_push)
    data = pd.read_csv(dir_collect + aggr_file, delimiter=";", index_col=0)
    print(data)
    # sys.exit()
    print("DONE")
    relevant_data = data  # [data["relevant"].fillna(-1).astype('int')==1]
    # as such, all entries are considered to be relevant
    templates_dict = {}

    libs = "/collections"
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

    r_collections = requests.get(url + "?limit=100?start=0", headers=headers)

    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        found_parent = False
        print(data_collections)
        papers_by_coll = {}
        exits_url = []
        lib = None
        for d in data_collections:
            print(d["data"])
            if d["data"]["name"] == research_coll:
                print("FOUND current Collection >", d["data"]["name"])
                lib = d
                current_col_key = d["data"]["key"]
                break
        print(current_col_key)

        if current_col_key is None:
            headers = {
                "Zotero-API-Key": api_key,
                "Zotero-Write-Token": getWriteToken(),
                "Content-Type": "application/json",
            }
            body = json.dumps([{"name": research_coll}])
            print(body)
            req2 = requests.post(url, headers=headers, data=body)
        else:
            print(lib)
            dict_papers = {}
            papers_url = []
            name = lib["data"]["name"]
            nb_items = lib["meta"]["numItems"]
            key = lib["key"]
            print(nb_items)
            if int(nb_items) > 0:
                dict_papers = {
                    "key": key,
                    "nbItems": nb_items,
                    "name": name,
                    "items": [],
                }
                start = 0
                r_items = requests.get(
                    url2 + "/items?limit=100&start=" + str(start), headers=headers
                )
                if r_items.status_code == 200:
                    print(url2)
                    items = r_items.json()
                    for row in items:
                        print(row)
                        if "collections" in row["data"]:
                            if current_col_key in row["data"]["collections"]:
                                exits_url.append(row["data"]["url"])
                    nb_res = int(r_items.headers["Total-Results"])

                    while nb_res > start + 100:
                        print(start)
                        if start != 0:
                            r_items = requests.get(
                                url
                                + libs
                                + key
                                + "/items?limit=100&start="
                                + str(start),
                                headers=headers,
                            )
                            if r_items.status_code == 200:
                                # dict_papers["items"]
                                items = r_items.json()
                                for row in items:
                                    print(row)
                                    if "collections" in row["data"]:
                                        if (
                                            current_col_key
                                            in row["data"]["collections"]
                                        ):
                                            print(
                                                "JEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"
                                            )
                                            exits_url.append(row["data"]["url"])

                        start += 100
                # papers_by_coll[name] = dict_papers

    print(">>>>>>>>>>>> ADD NEW PAPERS")
    print(relevant_data)
    # sys.exit()
    for _index, row in relevant_data.iterrows():
        itemType = row["itemType"]
        if itemType == "bookSection":
            itemType = "journalArticle"
        if itemType != "" and itemType != "NA" and not pd.isna(itemType):
            if itemType not in templates_dict:
                resp = requests.get(
                    "https://api.zotero.org/items/new?itemType=" + itemType
                )
                template = resp.json()
                templates_dict[itemType] = template
            current_temp = templates_dict[itemType]
            current_temp["collections"] = [current_col_key]
            common_cols = [
                "publisher",
                "title",
                "date",
                "DOI",
                "archive",
                "url",
                "rights",
                "pages",
                "journalAbbreviation",
                "conferenceName",
                "volume",
                "issue",
            ]

            for col in common_cols:
                if col in current_temp and col in row:
                    current_temp[col] = str(row[col])

            current_temp["abstractNote"] = str(row["abstract"])
            if "archiveLocation" in current_temp:
                current_temp["archiveLocation"] = str(row["archiveID"])

            template_authors = current_temp["creators"][0].copy()
            auth_list = []
            if "authors" in row:
                if (
                    row["authors"] != ""
                    and row["authors"] != "NA"
                    and not pd.isna(row["authors"])
                ):
                    authors = row["authors"].split(";")
                    for auth in authors:
                        current_auth = template_authors.copy()
                        current_auth["firstName"] = auth
                        auth_list.append(current_auth)
                    current_temp["creators"] = auth_list

            if (
                current_temp["url"] == ""
                or current_temp["url"].upper() == "NA"
                or current_temp["url"].upper() == "NAN"
            ):
                if (
                    pd.notna(row["DOI"])
                    and str(row["DOI"]) != ""
                    and str(row["DOI"]).upper() != "NA"
                    and str(row["DOI"]).upper() != "NAN"
                ):
                    current_temp["url"] = row["DOI"]
                else:
                    current_temp["url"] = None
                # if("http" not in current_temp["DOI"]):

            if current_temp["url"] is not None:
                if current_temp["url"] not in exits_url:
                    print(">>>>" + current_temp["url"])
                    body = json.dumps([current_temp])
                    print(row["title"])
                    headers = {
                        "Zotero-API-Key": api_key,
                        "Zotero-Write-Token": getWriteToken(),
                        "Content-Type": "application/json",
                    }

                    req2 = requests.post(url2 + "items", headers=headers, data=body)
                    print(req2)
                    print(row)
            else:
                print("PB with following :")
                print(current_temp)
            # print(url2+"/items")
