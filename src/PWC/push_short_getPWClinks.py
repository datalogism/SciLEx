#!/usr/bin/env python3
"""
Created on Sat May  6 18:00:55 2023

@author: cringwal
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Feb 28 14:36:44 2023

@author: cringwal
"""

import json
import random
import string
from time import sleep

import requests
import yaml

############
# SCRIPT FOR GETTING DATA FROM PWD DUMP
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
    print(test)
    resp = test.json()
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


############## GET ALL PAPERS OF StateOfArtStudy

getDataInit = True
getRefData = True
pushToZotero = False
test_session = False

if getDataInit:
    nb_citation_toget = 0
    keep_citation_data = True
    paper_to_existing_ref = {}
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

#############

if getRefData:
    ## DOWNLOAD EACH TIME FROM SOURCE ?
    # url_dl="https://production-media.paperswithcode.com/"

    print(">>>>>>>>>>>>>>>>>>>>>>>> GET DATA")
    base_dir = "/user/cringwal/home/Desktop/THESE_YEAR1/SAT/PaperWithCode/"
    DATA_PATH = base_dir + "data"
    files = [
        "dataset",
        "evaluation-tables",
        "links-between-papers-and-code",
        "papers-with-abstracts",
    ]
    focused_tasks = [
        "Relation Extraction",
        "Relation Classification",
        "Zero-shot Relation Triplet Extraction",
        "Zero-shot Relation Classification",
        "Zero-shot Slot Filling",
        "Unsupervised KG-to-Text Generation",
        "Slot Filling",
        "Relation Classification",
        "Multi-Labeled Relation Extraction",
        "KG-to-Text Generation",
        "Data-to-Text Generation",
    ]
    data = {}

    for f in files:
        print(f)
        with open(DATA_PATH + "/" + f + ".json", encoding="utf-8") as json_file:
            data[f] = json.load(json_file)
        print(data[f][0].keys())

    datasets_url = {}
    datasets_title_url = {}
    for ds in data["dataset"]:
        inscope = False
        for task in ds["tasks"]:
            if task["task"] in focused_tasks:
                inscope = True
        if inscope:
            extra_url = "na"
            title = "na"
            pwc_url = ds["url"]
            if "paper" in ds and ds["paper"] is not None:
                title = ds["paper"]["title"]
                if "paperswithcode" in ds["paper"]["url"]:
                    pwc_url = ds["paper"]["url"]
                else:
                    extra_url = ds["paper"]["url"]

            datasets_url[pwc_url] = {
                "name": ds["name"],
                "title": title,
                "extra_url": extra_url,
            }
            if title != "na":
                datasets_title_url[title] = pwc_url

    paper_url = {}
    paper_extra_url = {}
    paper_title_url = {}
    for paper in data["papers-with-abstracts"]:
        inscope = False
        for task in paper["tasks"]:
            if task in focused_tasks:
                inscope = True
        if inscope:
            extra_url = paper["url_abs"]
            title = paper["title"]
            pwc_url = paper["paper_url"]
            paper_url[pwc_url] = {
                "title": title,
                "extraurl": extra_url,
                "code": "na",
                "results": {},
                "shortname": [],
            }
            paper_extra_url[extra_url] = pwc_url
            paper_title_url[title] = pwc_url

    for paper in data["links-between-papers-and-code"]:
        if paper["paper_url"] in paper_url:
            paper_url[paper["paper_url"]]["code"] = paper["repo_url"]

    for eval_ in data["evaluation-tables"]:
        if eval_["task"] in focused_tasks:
            for ds in eval_["datasets"]:
                name = ds["dataset"]
                print("----------", name)
                for res in ds["sota"]["rows"]:
                    if res["paper_url"] in paper_extra_url:
                        print("found")
                        pwc_url = paper_extra_url[res["paper_url"]]
                        paper_url[pwc_url]["shortname"].append(res["model_name"])
                        if name not in paper_url[pwc_url]["results"]:
                            paper_url[pwc_url]["results"][name] = {}
                        for m in res["metrics"]:
                            paper_url[pwc_url]["results"][name][m] = res["metrics"][m]
                        print(paper_url[pwc_url])


####### PUSH to Zotero again$
if pushToZotero:
    for lib in lib_list:
        key = lib["key"]
        name = lib["data"]["name"]
        # if("dataset" in name):
        # for item in dict_papers[key]["items"]:
        #     if(item["data"]["itemType"] not in ["attachment","webpage","note"]):
        #         archive=item["data"]["archive"]
        #         if("paperswithcode" in archive):
        #             if(archive in datasets_url.keys()):
        #                 if(item["data"]["shortTitle"]==""):
        #                     toADD={"shortTitle":datasets_url[archive]["name"]}
        #                     patch_withdata(item["key"],toADD)

        #         elif(item["data"]["title"] in datasets_title_url.keys()):
        #             url=datasets_title_url[item["data"]["title"]]
        #             toADD={"archive":url}
        #             if(item["data"]["shortTitle"]==""):
        #                 toADD["shortTitle"]=datasets_url[url]["name"]

        #             patch_withdata(item["key"],toADD)

        if "models" in name:
            for item in dict_papers[key]["items"]:
                if item["data"]["itemType"] not in ["attachment", "webpage", "note"]:
                    archive = item["data"]["archive"]

                    if "paperwithcode" in archive:
                        if archive in paper_url:
                            print(">>> FOUND")
                            toADD = {}
                            if len(paper_url[archive]["shortname"]) > 0:
                                toADD["shortTitle"] = ", ".join(
                                    list(set(paper_url[archive]["shortname"]))
                                )
                            # if(item["data"]["shortTitle"]=="" and len(paper_url[archive]["shortname"])>0):
                            #     toADD["shortTitle"]=", ".join(paper_url[archive]["shortname"])
                            # else:
                            #     print("title >",item["data"]["shortTitle"])
                            # "archiveLocation":datasets_url[archive]["name"]
                            #     toADD["shortTitle"]=dict_papers[url]["shortname"]

                            if paper_url[archive]["code"] != "" and (
                                item["data"]["archiveLocation"] in ["", "na", "NA"]
                            ):
                                toADD["archiveLocation"] = paper_url[archive]["code"]
                            else:
                                print("CODE >", item["data"]["archiveLocation"])
                            if (
                                len(list(paper_url[archive]["results"].keys())) > 0
                                and item["data"]["callNumber"] == ""
                            ):
                                toADD["callNumber"] == ""
                                toADD["callNumber"] = json.dumps(
                                    paper_url[archive]["results"]
                                )
                            else:
                                print("results >", item["data"]["callNumber"])
                            if len(list(toADD.keys())) > 0:
                                print(toADD)
                                patch_withdata(item["key"], toADD)
                    elif item["data"]["title"] in paper_title_url:
                        print(">>> ADD PWC")
                        arch_url = paper_title_url[item["data"]["title"]]
                        toADD = {"archive": arch_url}

                        if len(paper_url[arch_url]["shortname"]) > 0:
                            toADD["shortTitle"] = ", ".join(
                                list(set(paper_url[arch_url]["shortname"]))
                            )
                        # if(item["data"]["shortTitle"]=="" and len(paper_url[arch_url]["shortname"])>0):
                        #     toADD["shortTitle"]=paper_url[arch_url]["shortname"]
                        # else:
                        #     print("title >",item["data"]["shortTitle"])
                        # "archiveLocation":datasets_url[archive]["name"]
                        #     toADD["shortTitle"]=dict_papers[url]["shortname"]
                        if paper_url[arch_url]["code"] != "" and (
                            item["data"]["archiveLocation"] in ["", "na", "NA"]
                        ):
                            toADD["archiveLocation"] = paper_url[arch_url]["code"]
                        else:
                            print("CODE >", item["data"]["archiveLocation"])

                        if (
                            len(list(paper_url[arch_url]["results"].keys())) > 0
                            and item["data"]["callNumber"] == ""
                        ):
                            toADD["callNumber"] = json.dumps(
                                paper_url[arch_url]["results"]
                            )

                        print(toADD)
                        patch_withdata(item["key"], toADD)
                    else:
                        print("ADD NOTHING >", item["data"]["archive"])


if test_session:
    url = "https://api.zotero.org/users/5689645"
    resp = requests.get("https://api.zotero.org/items/new?itemType=Note")
    template = resp.json()
    current_temp = template
    # current_temp["collections"].append("IJAAEH8Q")
    current_temp["note"] = json.dumps({"F1": "92.5", "F1 (strict)": "90.2"})
    # current_temp["parentItem"]=[]
    # current_temp["parentItem"].append("CVTRXXRA")
    body = json.dumps([current_temp])
    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-Write-Token": getWriteToken(),
        "Content-Type": "application/json",
    }

    req2 = requests.post(url + "/items", headers=headers, data=body)
# if pushToZotero==True:
#     for ref in references.keys():
#         z_id=zotid_doi[ref]
#         list_r=references[ref]
#         if(len(list_r)>0 and ref not in paper_to_existing_ref.keys() or paper_to_existing_ref[ref]==[]):
#             patch_withreference(z_id,list_r)
