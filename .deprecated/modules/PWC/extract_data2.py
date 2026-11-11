#!/usr/bin/env python3
"""
Created on Wed May  3 17:20:54 2023

@author: cringwal
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar 31 09:16:16 2023

@author: cringwal
"""

import json
import random
import string

import pandas as pd
import requests
import yaml

############
# SCRIPT FOR EXTRACTING PWC DUMP DATA
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getWriteToken():
    return "".join(
        random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32)
    )


def PaperWithCodetoZoteroFormat(row):
    from src.constants import MISSING_VALUE

    # print(">>SemanticScholartoZoteroFormat")
    # bookSection?
    zotero_temp = {
        "title": MISSING_VALUE,
        "publisher": MISSING_VALUE,
        "itemType": MISSING_VALUE,
        "authors": MISSING_VALUE,
        "language": MISSING_VALUE,
        "abstract": MISSING_VALUE,
        "archiveID": MISSING_VALUE,
        "archive": MISSING_VALUE,
        "date": MISSING_VALUE,
        "DOI": "",
        "url": MISSING_VALUE,
        "rights": MISSING_VALUE,
        "pages": MISSING_VALUE,
        "journalAbbreviation": MISSING_VALUE,
        "volume": MISSING_VALUE,
        "serie": MISSING_VALUE,
        "issue": MISSING_VALUE,
    }
    zotero_temp["archive"] = row["paper_url"]
    # NOTE: publicationTypes is a list, but Zotero only accepts one value
    # TODO: Handle multiple publicationTypes - currently using first value only

    zotero_temp["itemType"] = "journalArticle"
    if row["proceeding"] != "" and row["proceeding"] is not None:
        zotero_temp["itemType"] = "conferencePaper"
        zotero_temp["conferenceName"] = row["proceeding"]
    elif "arxiv" in row["url_abs"]:
        zotero_temp["itemType"] = "preprint"

    if row["title"] != "" and row["title"] is not None:
        zotero_temp["title"] = row["title"]

    if len(row["authors"]) > 0:
        zotero_temp["authors"] = ";".join(row["authors"])

    if row["abstract"] != "" and row["abstract"] is not None:
        zotero_temp["abstract"] = row["abstract"]

    if row["date"] != "" and row["date"] is not None:
        zotero_temp["date"] = row["date"]

    if row["url_abs"] != "" and row["url_abs"] is not None:
        zotero_temp["url"] = row["url_abs"]

    return zotero_temp


def getSubCollectionId(parent_coll, subcoll_name):
    url = "https://api.zotero.org/users/5689645"
    libs = "/collections/"
    headers = {"Zotero-API-Key": api_key}
    current_col_key = None
    while current_col_key is None:
        r_collections = requests.get(url + libs + "?limit=100", headers=headers)

        if r_collections.status_code == 200:
            data_collections = r_collections.json()
            for d in data_collections:
                if d["data"]["name"] == parent_coll:
                    id_lib = d["data"]["key"]
                    break

            for d in data_collections:
                if (
                    d["data"]["parentCollection"] == str(id_lib)
                    and d["data"]["name"] == subcoll_name
                ):
                    print("FOUND current Collection >", d["data"]["name"])
                    current_col_key = d["data"]["key"]
                    break
            if current_col_key is None:
                ## CREATE COLLECTION
                # headers={'Zotero-Write-Token':"19a4f01ad623aa7214f82347e3711f56"}
                headers = {
                    "Zotero-API-Key": api_key,
                    "Zotero-Write-Token": getWriteToken(),
                    "Content-Type": "application/json",
                }
                body = json.dumps(
                    [{"name": subcoll_name, "parentCollection": str(id_lib)}]
                )
                requests.post(url + "/collections", headers=headers, data=body)

    return current_col_key


def collectTags(row):
    tags = []
    if "methods" in row and len(row["methods"]) > 0:
        for m in row["methods"]:
            tag_name = "Pwc_method:" + m["name"]
            tags.append({"tag": tag_name})
    if "tasks" in row and len(row["tasks"]) > 0:
        for t in row["tasks"]:
            tag_name = "Pwc_task:" + t
            tags.append({"tag": tag_name})
    return tags


getData = True
cleanData = True
pushData = False

if getData:
    print(">>>>>>>>>>>>>>>>>>>>>>>> GET DATA")
    base_dir = "/user/cringwal/home/Desktop/THESE_YEAR1/SAT/PaperWithCode/"

    ## DOWNLOAD EACH TIME FROM SOURCE ?
    # url_dl="https://production-media.paperswithcode.com/"
    DATA_PATH = base_dir + "data"
    files = [
        "dataset",
        "methods",
        "evaluation-tables",
        "links-between-papers-and-code",
        "papers-with-abstracts",
    ]
    data = {}
    for f in files:
        print(f)
        with open(DATA_PATH + "/" + f + ".json", encoding="utf-8") as json_file:
            data[f] = json.load(json_file)
        print(data[f][0].keys())

    temp = None
    dict_tasks_ds = {}
    for row in data["dataset"]:
        for i in range(len(row["tasks"])):
            temp = row
            if row["tasks"][i]["task"] not in dict_tasks_ds:
                dict_tasks_ds[row["tasks"][i]["task"]] = 1
            else:
                dict_tasks_ds[row["tasks"][i]["task"]] += 1
if cleanData:
    sourcetopwc_url = {}
    print(">>>>>>>>>>>>>>>>>>>>>>>> CLEAN DATA")
    # sorted_dict = sorted(dict_tasks_ds.keys(), key=data.get)
    focused_tasks = [
        "Relation Extraction",
        # "Coreference Resolution",
        # "Knowledge Graphs",
        # "Entity Linking",
        # "Text Generation",
        # "Named Entity Recognition (NER)",
        # "Text2text Generation",
        # "Synthetic Data Generation",
        "Relation Classification",
        "Zero-shot Relation Triplet Extraction",
        "Zero-shot Relation Classification",
        "Zero-shot Slot Filling",
        # "Weakly-Supervised Named Entity Recognition",
        "Unsupervised KG-to-Text Generation",
        "Slot Filling",
        "Relation Classification",
        "Multi-Labeled Relation Extraction",
        # "Knowledge Graphs",
        # "Knowledge Graph Embeddings",
        # "Knowledge Graph Completion",
        # "Knowledge Graph Embedding",
        # "Knowledge Base Population",
        # "Knowledge Base Completion",
        "KG-to-Text Generation",
        # "Entity Linking",
        # "Data Augmentation",
        "Data-to-Text Generation",
        # "Concept-To-Text Generation",
        # "Conditional Text Generation",
        # "Commonsense Knowledge Base Construction"
    ]
    ### add variation in case of
    temp = []
    for t in focused_tasks:
        temp.append(t.lower())
    focused_tasks = focused_tasks + temp

    tasks_data_ = {}
    keep_ds_k = [
        "name",
        "full_name",
        "homepage",
        "description",
        "paper",
        "introduced_date",
        "warning",
        "modalities",
        "languages",
        "variants",
        "num_papers",
    ]

    dataset_data_ = {}
    dataset_data_papers = {}
    for row in data["dataset"]:
        task_list = []
        for i in range(len(row["tasks"])):
            if row["tasks"][i]["task"].lower() in focused_tasks:
                task_list.append(row["tasks"][i]["task"])
                if row["tasks"][i]["task"] not in tasks_data_:
                    tasks_data_[row["tasks"][i]["task"]] = {
                        "url": row["tasks"][i]["url"],
                        "datasets": [row["url"]],
                    }
                else:
                    tasks_data_[row["tasks"][i]["task"]]["datasets"].append(row["url"])
        if len(task_list) > 0:
            dataset_data_[row["url"]] = {}
            if row["paper"] is not None:
                dataset_data_papers[row["url"]] = row["paper"]["url"]
            for k in keep_ds_k:
                dataset_data_[row["url"]][k] = row[k]

    task_eval_data_ = {}
    for row in data["evaluation-tables"]:
        if row["task"].lower() in focused_tasks:
            if row["task"] not in task_eval_data_:
                task_eval_data_[row["task"]] = {}
            for ds in row["datasets"]:
                for links in ds["dataset_links"]:
                    if "https://paperswithcode.com/" in links["url"]:
                        if len(ds["sota"]["rows"]) > 0:
                            task_eval_data_[row["task"]][links["url"]] = ds["sota"]

    methods_used = {}
    models_data_ = {}
    datasets_papers_data = {}
    nb_in_eval = 0
    proceeding_list = {}
    for row in data["papers-with-abstracts"]:
        focused = False
        found_task_in_sota = []
        for task in row["tasks"]:
            if task.lower() in focused_tasks:
                focused = True
                if task in task_eval_data_:
                    for k in task_eval_data_[task]:
                        sota = task_eval_data_[task][k]
                        for meth in sota["rows"]:
                            if row["arxiv_id"] and row["arxiv_id"] in meth["paper_url"]:
                                found_task_in_sota.append({"task": task, "ds": k})
        if focused:
            sourcetopwc_url[row["url_abs"]] = row["paper_url"]
            models_data_[row["paper_url"]] = row
            models_data_[row["paper_url"]]["found_eval"] = found_task_in_sota

            if row["paper_url"] in list(
                dataset_data_papers.values()
            ):  # IS IT A DATASET PAPER ?
                datasets_papers_data[row["paper_url"]] = models_data_[row["paper_url"]]
            if row["proceeding"] is not None:
                if row["proceeding"] not in proceeding_list:
                    proceeding_list[row["proceeding"]] = 0
                proceeding_list[row["proceeding"]] += 1
            if len(found_task_in_sota) > 0:
                nb_in_eval += 1
            if len(row["methods"]) > 0:
                for meth in row["methods"]:
                    if meth["name"] not in methods_used:
                        methods_used[meth["name"]] = meth
                        methods_used[meth["name"]]["nb"] = 0
                    methods_used[meth["name"]]["nb"] += 1


if computeStat:
    ############## SOME STATS
    nb_preprint = 0
    code_links = []
    benchmak_links = []
    nb_code = 0
    nb_benchmarked = 0

    for current in data["evaluation-tables"]:
        for ds in current["datasets"]:
            for rows in ds["sota"]["rows"]:
                # for rows in sota["rows"]:
                if rows["paper_url"] in sourcetopwc_url:
                    url2 = sourcetopwc_url[rows["paper_url"]]
                    if url2 in models_data_ and url2 not in benchmak_links:
                        benchmak_links.append(url2)

                        print("ADD THERE")
        if "subtasks" in current and len(current["subtasks"]) > 0:
            for st in current["subtasks"]:
                for ds2 in st["datasets"]:
                    for rows2 in ds2["sota"]["rows"]:
                        if rows2["paper_url"] in sourcetopwc_url:
                            url2 = sourcetopwc_url[rows2["paper_url"]]
                            if url2 in models_data_ and url2 not in benchmak_links:
                                benchmak_links.append(url2)

                                print("ADD HERE")

    for k in models_data_:
        if "arxiv" in models_data_[k]["url_abs"]:
            nb_preprint += 1
    for current in data["links-between-papers-and-code"]:
        # current=data["links-between-papers-and-code"][k]
        if current["paper_url"] in models_data_:
            if current["paper_url"] not in code_links:
                print(current["paper_url"])
                code_links.append(current["paper_url"])
                nb_code += 1

    years = list(
        set(
            [
                models_data_[k]["date"][0:4]
                for k in models_data_
                if "date" in models_data_[k]
            ]
        )
    )
    sorted_years = sorted(years)
    variables = ["Total", "Nb Preprint", "Nb code", "Nb benchmarked"]
    dict_years = {
        "Total": [0] * len(sorted_years),
        "Nb Preprint": [0] * len(sorted_years),
        "Nb code": [0] * len(sorted_years),
        "Nb benchmarked": [0] * len(sorted_years),
    }
    for i in range(len(sorted_years)):
        year = sorted_years[i]
        for k in models_data_:
            if year in models_data_[k]["date"]:
                dict_years["Total"][i] += 1
                if "arxiv" in models_data_[k]["url_abs"]:
                    dict_years["Nb Preprint"][i] += 1
                if models_data_[k]["paper_url"] in code_links:
                    dict_years["Nb code"][i] += 1
                if models_data_[k]["paper_url"] in benchmak_links:
                    dict_years["Nb benchmarked"][i] += 1

    plt2 = pd.DataFrame(dict_years, index=sorted_years)
    plt2.plot(kind="bar")
# plt.title("Mince Pie Consumption Study")
# plt.xlabel("Family Member")
# plt.ylabel("Pies Consumed")
##### FIRST DATA SET

if pushData:
    parent_coll = "StateOfArtStudy"
    subcoll_name = "PWC_models_new"
    current_col_key = getSubCollectionId(parent_coll, subcoll_name)

    ##### MODELS DATA

    print(">>>>>>>>>>>>>>>>>>>>> PUSH DATA")

    current_col_key = getSubCollectionId(parent_coll, subcoll_name)
    url = "https://api.zotero.org/users/5689645"
    libs = "/collections/"
    for k in models_data_:
        if (
            "arxiv" not in models_data_[k]["url_abs"]
            or models_data_[k]["paper_url"] in code_links
            or models_data_[k]["paper_url"] in benchmak_links
        ):
            if k not in list(datasets_papers_data.keys()):
                print(k)
                templates_dict = {}
                row = PaperWithCodetoZoteroFormat(models_data_[k])
                itemType = row["itemType"]
                from src.constants import is_valid

                if is_valid(itemType):
                    if itemType not in templates_dict:
                        resp = requests.get(
                            "https://api.zotero.org/items/new?itemType=" + itemType
                        )
                        template = resp.json()
                        templates_dict[itemType] = template

                    current_temp = templates_dict[itemType]
                    current_temp["tags"] = collectTags(models_data_[k])
                    if models_data_[k]["paper_url"] in code_links:
                        current_temp["tags"].append({"tag": "PWC:havecode"})
                    else:
                        current_temp["tags"].append({"tag": "PWC:donthavecode"})
                    if models_data_[k]["paper_url"] in benchmak_links:
                        current_temp["tags"].append({"tag": "PWC:isbenchmarked"})
                    else:
                        current_temp["tags"].append({"tag": "PWC:notbenchmarked"})
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
                            and is_valid(row.get("authors"))
                            and not pd.isna(row["authors"])
                        ):
                            authors = row["authors"].split(";")
                            for auth in authors:
                                current_auth = template_authors.copy()
                                current_auth["firstName"] = auth
                                auth_list.append(current_auth)
                            current_temp["creators"] = auth_list

                    body = json.dumps([current_temp])
                    headers = {
                        "Zotero-API-Key": api_key,
                        "Zotero-Write-Token": getWriteToken(),
                        "Content-Type": "application/json",
                    }

                    req2 = requests.post(url + "/items", headers=headers, data=body)
