#!/usr/bin/env python3
"""
Created on Wed Mar  8 08:06:34 2023

@author: cringwal
@project:Scilex
"""

import json
from time import sleep

import pandas as pd
import requests
import yaml

############
# SCRIPT FOR IRAMUTEQ ANALYSIS
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
getDataInit = True

## Zotero libs names
list_of_interest = ["dataset", "models", "SURVEYS_RE"]
if getDataInit:
    list_id_interest = {}
    paper_to_existing_ref = {}
    r_collections = requests.get(url + libs, headers=headers)
    if r_collections.status_code == 200:
        data_collections = r_collections.json()

        data_lib = None
        for d in data_collections:
            if str(d["data"]["name"]) in list_of_interest:
                list_id_interest[d["data"]["key"]] = str(d["data"]["name"])
            if d["data"]["name"] == "StateOfArtStudy":
                id_lib = d["data"]["key"]
                break

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
            r_items = requests.get(
                url + libs + key + "/items?limit=100", headers=headers
            )
            if r_items.status_code == 200:
                dict_papers[key]["items"] = r_items.json()

                for paper in dict_papers[key]["items"]:
                    if "DOI" in paper["data"]:
                        if (
                            paper["data"]["DOI"] != ""
                            and paper["data"]["DOI"] != "nan"
                            and "/" in paper["data"]["DOI"]
                        ):
                            if (
                                "extra" in paper["data"]
                                and paper["data"]["extra"] != ""
                                and "['" in paper["data"]["extra"]
                            ):
                                try:
                                    paper_to_existing_ref[paper["data"]["DOI"]] = (
                                        json.loads(
                                            paper["data"]["extra"].replace("'", '"')
                                        )
                                    )
                                except:
                                    print("bad data in extra", paper["data"]["DOI"])
                            else:
                                paper_to_existing_ref[paper["data"]["DOI"]] = []
            sleep(3)

papers_enriched = pd.read_csv(collect_dir + "/nodes050323_cleaned.csv")
from dateutil import parser

dict_export = {}
for id_ in list_id_interest:
    dict_export[list_id_interest[id_]] = []

for k in dict_papers:
    lib = dict_papers[k]
    print(lib["key"])
    if lib["key"] in list_id_interest:
        parent = list_id_interest[lib["key"]]
        print(">FOUND", parent)
        for paper in lib["items"]:
            tempo = {"title": "", "abstract": "", "year": "none", "label": "none"}
            if "DOI" in paper["data"]:
                if (
                    paper["data"]["DOI"] != ""
                    and paper["data"]["DOI"] != "nan"
                    and "/" in paper["data"]["DOI"]
                ):
                    p = papers_enriched[papers_enriched["Id"] == paper["data"]["DOI"]]
                    tempo["label"] = p["Label"].values[0]

            if "abstractNote" in paper["data"]:
                # print(">>>>>>>>>",parent)
                # print("Abstracts")
                tempo["title"] = paper["data"]["title"]
                tempo["abstract"] = paper["data"]["abstractNote"]
                date = paper["data"]["date"]
                if date != "":
                    d_raw = parser.parse(paper["data"]["date"])
                    tempo["year"] = d_raw.year

                dict_export[parent].append(tempo)


f_all_t = open(collect_dir + "/all_title_iramuteq.txt", "w")
f_all_a = open(collect_dir + "/all_abstract_iramuteq.txt", "w")
for coll in dict_export:
    print(">>>>>>>>>>>>>>>", coll)
    with open(collect_dir + "/" + coll + "_abstract_iramuteq.txt", "w") as file:
        for paper in dict_export[coll]:
            f_all_t.write(
                "**** *"
                + coll
                + " *"
                + str(paper["year"])
                + " *"
                + paper["label"]
                + "\n"
            )
            f_all_t.write(paper["title"] + "\n")
            f_all_a.write(
                "**** *"
                + coll
                + " *"
                + str(paper["year"])
                + " *"
                + paper["label"]
                + "\n"
            )
            f_all_a.write(paper["abstract"] + "\n")
            # print(paper["year"])
            file.write("**** *" + str(paper["year"]) + " *" + paper["label"] + "\n")
            file.write(paper["abstract"] + "\n")
#    coll_clean='_'.join(coll)paper["label"]

f_all_t.close()
f_all_a.close()
