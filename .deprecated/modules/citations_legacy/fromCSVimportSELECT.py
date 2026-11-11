#!/usr/bin/env python3
"""
Created on Thu Apr 11 12:13:28 2024

@author: cringwal
"""

import pandas as pd
import requests
import yaml
from ratelimit import limits, sleep_and_retry

############
# SCRIPT FOR SELECTING ARTICLE DEPENDING CITATION COUNT
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


api_citations = "https://opencitations.net/index/coci/api/v1/citation-count/"


@sleep_and_retry
@limits(calls=10, period=1)
def getCitations(doi):
    print("REQUEST citations -doi :", doi)
    try:
        resp = requests.get(api_citations + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


file_new_art = pd.read_csv("/user/cringwal/home/Downloads/Article2324.csv")
doi_stats = {}
for _index, row in file_new_art.iterrows():
    print(row["DOI"])
    doi_str = row["DOI"].replace("https://doi.org/", "").lower()
    date = int(row["date"][0:4])
    if date > 2018:
        duree = 2024 - int(date)
        nb_cit = 0
        citation = getCitations(doi_str.replace("https://doi.org/", ""))
        ratio = 0
        interest = 0
        try:
            resp_cit = citation.json()
            nb_cit = int(resp_cit[0]["count"])
        except:
            print("PB with citation count")
        if duree > 0 and nb_cit > 0:
            ratio = nb_cit / duree
            if ratio > 1:
                interest = 1

        elif nb_cit > 0:
            interest = 1
        if interest == 1:
            row["title"]
        tempo = {
            "year": date,
            "duree": duree,
            "nb_cit": nb_cit,
            "ratio": ratio,
            "interest": interest,
        }
        doi_stats[doi_str] = tempo

url = "https://api.zotero.org/groups/5259782/collections/8G5JB9UZ"
headers = {"Zotero-API-Key": api_key}

r_collections = requests.get(url, headers=headers)
data_meta = r_collections.json()
nb_res = int(data_meta["meta"]["numItems"])
start = 0
all_data = []
continue_ = True
if r_collections.status_code == 200:
    while continue_:
        print("HEY")
        r_items = requests.get(
            url + "/items?limit=100&start=" + str(start), headers=headers
        )
        data_current = r_items.json()
        if len(data_current) == 0:
            continue_ = False
        all_data += data_current
        start += 100

in_zotero_list = []
for d in all_data:
    if "DOI" in d["data"]:
        in_zotero_list.append(d["data"]["DOI"].replace("https://doi.org/", ""))


nb = 0
for k in doi_stats:
    if doi_stats[k]["interest"] == 1:
        nb += 1

to_add_list = []
for doi in doi_stats:
    if doi_stats[doi]["interest"] == 1 and doi.lower() not in in_zotero_list:
        to_add_list.append(doi)


columns = list(file_new_art.columns)

ds = []

for _index, row in file_new_art.iterrows():
    doi_str = row["DOI"].replace("https://doi.org/", "").lower()
    if doi_str in to_add_list:
        ds.append(dict(row))

df_new = pd.DataFrame(ds)

df_new.to_csv("/user/cringwal/home/Downloads/Article2324_filtered.csv")
# file_new_art= pd.read_csv("/user/cringwal/home/Downloads/Article2324_filtered.csv")
