#!/usr/bin/env python3
"""
Created on Wed May 24 09:06:48 2023

@author: cringwal
"""

# -*- coding: utf-8 -*-
"""
Created on Sun May  8 12:18:35 2022

@author: Celian
"""
import csv

import yaml

############
# SCRIPT FOR GETTING ABSTRACT FROM linkedpaperswithcode
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["orcid"]["dir"]
    client_id = cfg["orcid"]["client_id"]
    client_secret = cfg["orcid"]["client_secret"]


dict_orcid = {}
with open(
    collect_dir + "orcid_id_all_checked.csv", newline="", encoding="utf-8"
) as csvfile:
    spamreader = csv.reader(csvfile, delimiter=";", quotechar="|")
    for row in spamreader:
        dict_orcid[row[0]] = row[1]


import requests

# https://groups.google.com/g/orcid-api-users/c/b4-5oZ5PfWw

body = {
    "client_id": client_id,
    "client_secret": client_secret,
    "grant_type": "client_credentials",
    "scope": "/read-public",
}
url = "https://orcid.org/oauth/token"
token_resp = requests.post(url, data=body)
token_data = token_resp.json()

# CALL THE API FOR EACH ORCID ID
import time

dict_orcid_data = {}
for orcid_name in dict_orcid:
    if dict_orcid[orcid_name] != "":
        print(orcid_name)
        orcid_test = dict_orcid[orcid_name]
        url = "https://pub.orcid.org/v2.1/" + orcid_test + "/keywords"
        record_resp = requests.get(
            url,
            headers={
                "Accept": "application/orcid+json",
                "Authorization": "Bearer " + token_data["access_token"],
            },
        )
        keywords = record_resp.json()
        # employement
        url = "https://pub.orcid.org/v2.1/" + orcid_test + "/employments"
        record_resp = requests.get(
            url,
            headers={
                "Accept": "application/orcid+json",
                "Authorization": "Bearer " + token_data["access_token"],
            },
        )
        employments = record_resp.json()
        # education
        url = "https://pub.orcid.org/v2.1/" + orcid_test + "/educations"
        record_resp = requests.get(
            url,
            headers={
                "Accept": "application/orcid+json",
                "Authorization": "Bearer " + token_data["access_token"],
            },
        )
        educations = record_resp.json()
        # education
        url = "https://pub.orcid.org/v2.1/" + orcid_test + "/address"
        record_resp = requests.get(
            url,
            headers={
                "Accept": "application/orcid+json",
                "Authorization": "Bearer " + token_data["access_token"],
            },
        )
        address = record_resp.json()
        dict_orcid_data[orcid_test] = {
            "kwd": keywords,
            "employments": employments,
            "adress": address,
            "educations": educations,
        }
        time.sleep(1)

import json

with open(collect_dir + "dict_orcid_all_checked_raw.json", "w") as outfile:
    json.dump(dict_orcid_data, outfile)
