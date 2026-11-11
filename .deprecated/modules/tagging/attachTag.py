#!/usr/bin/env python3
"""
Created on Wed Sep 27 10:15:27 2023

@author: cringwal
"""

import json
import random
import string
from time import sleep

import pandas as pd
import requests
import yaml

############
# SCRIPT FOR REPLACING TAGS DEPENDING A FILE
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


def getitemVersion(item_key):
    print("HEY")
    url = "https://api.zotero.org/users/5689645"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    print(resp)
    version = resp["version"]
    return version


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    last_v = getitemVersion(item_key)
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    print(body)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


getDataInit = False
getDataChanges = True
attachTag = True


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


if getDataChanges:
    ############################## REPLACE DICT
    file = "/user/cringwal/home/tags_count_ds_and_survey_NOW.csv"
    df = pd.read_csv(file)
    dict_tags_replace = {}
    for _index, row in df.iterrows():
        columns = list(row.keys())
        dict_tags_replace[str(row["tag"]).strip()] = {}
        for col in columns:
            if col != "tag":
                dict_tags_replace[str(row["tag"]).strip()][str(col).strip()] = row[col]

    val_count = {}
    tag_changes = {}
    for item in dict_papers["IJAAEH8Q"][
        "items"
    ]:  # DHHJ7YZF for models only / R67UC3PV for dataset / IJAAEH8Q for surveys
        z_id = item["key"]
        data = item["data"]
        tags = data["tags"]
        if len(tags) > 0:
            todo = True
            tags_new = {}

            new_tags2 = []
            for t in tags:
                tag = t["tag"]
                if tag in dict_tags_replace:
                    if str(dict_tags_replace[tag]["replace_by"]) != "nan":
                        val = dict_tags_replace[tag]["replace_by"]
                        if val not in val_count:
                            val_count[val] = 0
                        val_count[val] += 1

                        tags_new[val] = val

                    elif str(dict_tags_replace[tag]["keep"]) != "nan":
                        # print("KEEEP>",tag)
                        todo = False

                        if tag not in val_count:
                            val_count[tag] = 0
                        val_count[tag] += 1

                        tags_new[tag] = tag

                    elif str(dict_tags_replace[tag]["delete"]) != "nan":
                        todo = False
                    else:
                        todo = False
                        # print("REPLACE",tag)

                        columns = list(dict_tags_replace[tag].keys())
                        for col in columns:
                            if col not in ["delete", "nb", "replace_by", "keep"]:
                                val = str(dict_tags_replace[tag][col]).strip()
                                if str(val) != "nan":
                                    col2 = col.replace("1", "").replace("2", "").strip()

                                    if col2 not in val_count:
                                        val_count[col2] = 0
                                    if col2 not in tags_new:
                                        tags_new[col2] = []
                                    tags_new[col2].append(val)
                                    val_count[col2] += 1
                    # print("DELETE",tag)
            if len(tags_new.keys()) == 0 or todo:
                print("PB WITH_________________")
                print(tags)
            else:
                for k in tags_new:
                    if type(tags_new[k]) is list:
                        uniq = list(set(tags_new[k]))
                        for un in uniq:
                            new_tags2.append({"tag": k + ":" + un})

                    else:
                        new_tags2.append({"tag": k.replace("PWC:", "")})
                tag_changes[z_id] = new_tags2

        #     print(">>>>>>>>>>>>>>>")
        #     print(tags_new)
        # else:
        #     print("PB")


if attachTag:
    for z_id in tag_changes:
        print(z_id)
        url = "https://api.zotero.org/users/5689645"
        libs = "/collections/"
        changes = {"tags": tag_changes[z_id]}
        print(changes)
        patch_withdata(z_id, changes)
