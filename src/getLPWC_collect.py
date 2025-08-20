#!/usr/bin/env python3
"""
Created on Thu Apr 11 19:34:58 2024

@author: cringwal
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Nov 21 15:15:23 2023

@author: cringwal
"""

import json
import logging
import random
import string
from datetime import datetime

import requests
from SPARQLWrapper import SPARQLWrapper

from src.crawlers.utils import load_all_configs

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


def getValNormalized(tag, val):
    val_2 = "".join(x for x in val.title() if not x.isspace())
    return tag + val_2


if __name__ == "__main__":
    model_list = [
        "BERT",
        "BART",
        "RoBERTA",
        "T5",
        "CharacterBERT",
        "GPT",
        "Elmo",
        "GPT3",
        "Ernie",
        "RoBERTA",
        "SpanBERT",
        "GPT2",
        "XLNET",
        "Glove",
        "OpenIE",
        "word2vec",
        "AlBERT",
        "mBERT",
        "GraphTransformer",
        "XML",
        "RoBERTA",
        "RelationEmbed",
        "SciBERT",
        "PubMedBERT",
        "BioBERT",
        "TransformerXL",
        "ClausIE",
        "mT5",
        "DeBerta",
        "GLM",
        "COMET",
        "mBART",
        "REBEL",
        "BREDS",
        "MIML",
        "PEGASUS",
        "TranS2S",
        "BERTSum",
        "WebIsALOD",
        "PURE",
        "CasRel",
        "TranEsGCN",
        "OLLIE",
        "TextRunner",
        "REVERB",
        "FRED",
        "MinIE",
        "T0",
        "FlanT5",
        "DistillBert",
        "ELectra",
        "GOpher",
        "LamDA",
        "BARD",
        "Alpaca",
        "LLAMA",
        "VICUNA",
        "LUKE",
        "CokeBERT",
        "KGBART",
        "CLIP",
        "XLM",
        "GPT4",
        "KBERT",
        "KEPLER",
        "Flair",
        "LongFormer",
        "TranE",
    ]
    model_list = list(set([model.upper() for model in model_list]))
    research_coll = "DatasetSurveys"
    # Log the overall process with timestamps
    logging.info(f"Systematic review search started at {datetime.now()}")
    logging.info("================BEGIN Systematic Review Search================")
    sparql = SPARQLWrapper("https://linkedpaperswithcode.com/sparql")

    headers = {"Zotero-API-Key": api_key}
    if user_role == "group":
        url = "https://api.zotero.org/groups/" + str(user_id) + "/collections"
    elif user_role == "user":
        url = "https://api.zotero.org/users/" + str(user_id) + "/collections"
    r_collections = requests.get(url + "?limit=100?start=0", headers=headers)
    print(r_collections)
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
                if len(data_current) == 0:
                    continue_ = False
                all_data += data_current
                start += 100
            print("END")
            dict_to_upt = {}
            list_tags = ["ARCHI:", "DATASET:", "LANG:", "PTM:", "TASK:"]
            list_tags = [t.upper() for t in list_tags]
            nb_all = 0
            for p in all_data:
                p_copy = {}
                p_update = False
                if p["data"]["itemType"] != "attachment" and "title" in p["data"]:
                    nb_all += 1
                    title = p["data"]["title"].lower()

                    if title[-1] == ".":
                        title = title[0 : len(title) - 1]
                    tags = []
                    dict_found_tags = {t.upper(): False for t in list_tags}
                    if "tags" in p["data"]:
                        tags = [t["tag"].upper() for t in p["data"]["tags"]]
                        for t in list_tags:
                            for t2 in tags:
                                if (
                                    not dict_found_tags[t]
                                    and t in t2
                                    and t + "?" not in t2
                                ):
                                    dict_found_tags[t] = True

                    #   try :
                    sparql.setReturnFormat("json")
                    query = (
                        '''
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    PREFIX dcterms: <http://purl.org/dc/terms/>
                    select ?paper ?t where {
                    ?paper dcterms:title ?t.
                    FILTER (lcase(str(?t))="'''
                        + title
                        + """")
                    }
                    """
                    )
                    # print(query)
                    sparql.setQuery(query)

                    # ^^xsd:string
                    ret = sparql.query()
                    d = ret.convert()

                    if len(d["results"]["bindings"]) == 1:
                        p_update = True
                        print("FOUND THIS PAPER >", title)
                        print(dict_found_tags)

                        id_lpc = d["results"]["bindings"][0]["paper"]["value"]
                        print("================")
                        if not dict_found_tags["TASK:"]:
                            print(">LOOK FOR TASK")
                            sparql.setReturnFormat("json")
                            query2 = (
                                """PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                                   PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                                    select  ?task ?name where {
                                     <"""
                                + id_lpc
                                + """> lpwc:hasTask ?task.
                                     ?task foaf:name ?name
                                    }"""
                            )
                            sparql.setQuery(query2)
                            ret = sparql.query()
                            d = ret.convert()
                            if len(d["results"]["bindings"]) > 1:
                                print("FIND TASK")
                                for val in d["results"]["bindings"]:
                                    task = val["name"]["value"]
                                    new_val = getValNormalized("TASK:", task)
                                    if new_val.upper() not in tags:
                                        # print("FOUND NEW TASK >",new_val)
                                        if "tags" not in p_copy:
                                            p_copy["tags"] = []
                                        p_copy["tags"].append({"tag": new_val})
                        if not dict_found_tags["ARCHI:"]:
                            print(">LOOK FOR ARCHI")
                            sparql.setReturnFormat("json")
                            query3 = (
                                """PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                                             PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                                             select   ?method where {
                                             <"""
                                + id_lpc
                                + """> lpwc:hasMethod ?m.
                                             ?m foaf:name ?method
                                             }"""
                            )
                            print(query3)
                            sparql.setQuery(query3)
                            ret = sparql.query()
                            d = ret.convert()
                            if len(d["results"]["bindings"]) > 1:
                                print("FIND METTHOD")
                                for val in d["results"]["bindings"]:
                                    method = val["method"]["value"]
                                    if method.upper() in model_list:
                                        new_val = getValNormalized("PTM:", method)
                                        if new_val.upper() not in tags:
                                            print("FOUND NEW MODEL >", new_val)
                                            if "tags" not in p_copy:
                                                p_copy["tags"] = []
                                            p_copy["tags"].append({"tag": new_val})
                                    else:
                                        new_val = getValNormalized("ARCHI:", method)
                                        if new_val.upper() not in tags:
                                            if "tags" not in p_copy:
                                                p_copy["tags"] = []
                                            p_copy["tags"].append({"tag": new_val})

                        if (
                            not dict_found_tags["DATASET:"]
                            or not dict_found_tags["LANG:"]
                        ):
                            # DATASET FOR ALL
                            print("LOOK for dataset and lang")
                            sparql.setReturnFormat("json")
                            query4 = (
                                """
                              PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                              PREFIX dcterms: <http://purl.org/dc/terms/>
                              select  DISTINCT ?title ?lang where {
                              <"""
                                + id_lpc
                                + """> lpwc:usesDataset ?d.
                              ?d dcterms:title ?title. ?d dcterms:language ?lang.
                             }"""
                            )
                            print(query4)
                            sparql.setQuery(query4)

                            ret = sparql.query()
                            d = ret.convert()
                            if len(d["results"]["bindings"]) > 1:
                                print(":) FOUND LANg OR DATASET")
                                for val in d["results"]["bindings"]:
                                    dataset = val["title"]["value"]
                                    new_val = getValNormalized("DATASET:", dataset)
                                    if new_val.upper() not in tags:
                                        print("NEWDS")
                                        if "tags" not in p_copy:
                                            p_copy["tags"] = []
                                        p_copy["tags"].append({"tag": new_val})
                                    lang = val["lang"]["value"]
                                    new_val = getValNormalized("LANG:", lang)
                                    if new_val.upper() not in tags:
                                        print("NEWLANG")
                                        if "tags" not in p_copy:
                                            p_copy["tags"] = []
                                        p_copy["tags"].append({"tag": new_val})

                        if (
                            "shortTitle" in p["data"]
                            and len(p["data"]["shortTitle"]) < 2
                        ) or "shortTitle" not in p["data"]:
                            print("LOOK FOR SHORT TITLE")
                            sparql.setReturnFormat("json")
                            sparql.setQuery(
                                """PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                                            PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                                           select  DISTINCT ?name where {
                                               <"""
                                + id_lpc
                                + """> lpwc:hasModel ?m.
                                           ?m foaf:name ?name.
                                           }"""
                            )
                            ret = sparql.query()
                            d = ret.convert()
                            if len(d["results"]["bindings"]) == 1:
                                name = d["results"]["bindings"][0]["name"]["value"]
                                p_copy["shortTitle"] = name

                        # if (("archive" in p["data"].keys() and len(p["data"]["archive"]) < 5)
                        #        or "archive" not in p["data"].keys()):
                        print("GET ARCHIVE")
                        add = id_lpc.replace(
                            "https://linkedpaperswithcode.com/",
                            "https://paperswithcode.com/",
                        )
                        p_copy["archive"] = add

                        # if (("archiveLocation" in p["data"].keys() and len(p["data"]["archiveLocation"]) == 7)
                        #        or "archiveLocation" not in p["data"].keys()):
                        print("ADD REPO CODE")
                        sparql.setReturnFormat("json")
                        sparql.setQuery(
                            """
                                       PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                                        select  ?url where {
                                         <"""
                            + id_lpc
                            + """> lpwc:hasRepository ?r.
                                        ?r <http://purl.org/spar/fabio/hasURL> ?url
                                        }"""
                        )
                        ret = sparql.query()
                        d = ret.convert()
                        if len(d["results"]["bindings"]) == 1:
                            url = d["results"]["bindings"][0]["url"]["value"]
                            p_copy["archiveLocation"] = url
                if p_update:
                    dict_to_upt[p["key"]] = p_copy

            for z_id in dict_to_upt:
                data = getitemData(z_id)
                changes = {}
                if "tags" in dict_to_upt[z_id]:
                    tags = data["data"]["tags"]
                    tags_2 = []
                    for t in tags:
                        if isinstance(t["tag"], str):
                            tags_2.append(t)
                    for TAG in dict_to_upt[z_id]["tags"]:
                        tags_2.append(TAG)
                    changes = {"tags": tags_2}

                for field in dict_to_upt[z_id]:
                    if field != "tags":
                        changes[field] = dict_to_upt[z_id][field]
                print("---------NEW---------")
                print(dict_to_upt[z_id])
                print("---------CHANGES---------")
                print(changes)
                print("------------------")

                patch_withdata(z_id, changes)
