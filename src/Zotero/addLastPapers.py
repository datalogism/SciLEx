#!/usr/bin/env python3
"""
Created on Thu Apr 11 19:07:31 2024

@author: cringwal
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 30 16:06:58 2023

@author: cringwal
"""

import json
import random
import string

import pandas as pd
import requests


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


import yaml

############
# SCRIPT ADDING ARTICLES FROM FILE  TO ZOTERO
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


url = "https://api.zotero.org/groups/5259782"

data = pd.read_csv("/user/cringwal/home/Downloads/Article2324_filtered.csv")


templates_dict = {}


headers = {"Zotero-API-Key": api_key}
current_col_key = None


for _index, row in data.iterrows():
    itemType = row["itemType"]
    if itemType != "" and itemType != "NA" and not pd.isna(itemType):
        if itemType not in templates_dict:
            resp = requests.get("https://api.zotero.org/items/new?itemType=" + itemType)
            template = resp.json()
            templates_dict[itemType] = template

        current_temp = templates_dict[itemType]
        current_temp["collections"] = ["242BEP5Z"]
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
        print(current_temp)
        body = json.dumps([current_temp])
        headers = {
            "Zotero-API-Key": api_key,
            "Zotero-Write-Token": getWriteToken(),
            "Content-Type": "application/json",
        }

        req2 = requests.post(url + "/items", headers=headers, data=body)
