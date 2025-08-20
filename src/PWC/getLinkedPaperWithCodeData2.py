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

import requests
import yaml
from SPARQLWrapper import SPARQLWrapper

############
# SCRIPT FOR GETTING DATA FROM linkedpaperswithcode
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]


def getitemData(item_key):
    print("HEY")
    url = "https://api.zotero.org/groups/5259782"
    headers = {"Zotero-API-Key": api_key}
    test = requests.get(url + "/items/" + item_key + "?format=json", headers=headers)
    print(">", test)
    resp = test.json()
    return resp


def patch_withdata(item_key, data_dict):
    print("----patch >", item_key)
    url = "https://api.zotero.org/groups/5259782"
    data = getitemData(item_key)
    last_v = data["version"]
    headers = {"Zotero-API-Key": api_key, "If-Unmodified-Since-Version": str(last_v)}
    body = json.dumps(data_dict)
    resp = requests.patch(url + "/items/" + item_key, data=body, headers=headers)
    return resp.status_code


def getValNormalized(tag, val):
    val_2 = "".join(x for x in val.title() if not x.isspace())
    return tag + val_2


sparql = SPARQLWrapper("https://linkedpaperswithcode.com/sparql")


getDataInit = True
getDataToUpdate = True
pushToZotero = False
url = "https://api.zotero.org/groups/5259782/collections/242BEP5Z/"
libs = "/items"
headers = {"Zotero-API-Key": api_key}


start = 0
all_data = []
continue_ = True
while continue_:
    print("HEY >", start)
    r_items = requests.get(
        url + "/items/top?limit=100&start=" + str(start), headers=headers
    )
    data_current = r_items.json()
    if len(data_current) == 0:
        continue_ = False
    all_data += data_current
    start += 100


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

if getDataToUpdate:
    dict_to_upt = {}
    list_tags = [
        "SAT_archi:",
        "SAT_DATASET:",
        "SAT_metric:",
        "SAT_lang:",
        "SAT_model:",
        "SAT_task:",
    ]
    list_tags = [t.upper() for t in list_tags]
    nb_all = 0
    for p in all_data:
        p_copy = {}
        p_update = False
        if p["data"]["itemType"] != "attachment" and "title" in p["data"]:
            # print(p)
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
                        if not dict_found_tags[t] and t in t2 and t + "?" not in t2:
                            dict_found_tags[t] = True

            #   try :
            sparql.setReturnFormat("json")
            sparql.setQuery(
                '''
            select ?paper ?t where {
            ?paper dcterms:title ?t.
            FILTER (lcase(str(?t))="'''
                + title
                + """")
            }
            """
            )
            # ^^xsd:string
            ret = sparql.query()
            d = ret.convert()

            if len(d["results"]["bindings"]) == 1:
                print("FOUND THIS PAPER >", title)

                id_lpc = d["results"]["bindings"][0]["paper"]["value"]

                if not dict_found_tags["SAT_TASK:"]:
                    sparql.setReturnFormat("json")
                    sparql.setQuery(
                        """
                    PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                     select  ?task ?name where {
                      <"""
                        + id_lpc
                        + """> lpwc:hasTask ?task.
                      ?task foaf:name ?name
                     }"""
                    )
                    ret = sparql.query()
                    d = ret.convert()
                    if len(d["results"]["bindings"]) > 1:
                        for val in d["results"]["bindings"]:
                            task = val["name"]["value"]
                            new_val = getValNormalized("SAT_TASK:", task)
                            if new_val.upper() not in tags:
                                # print("FOUND NEW TASK >",new_val)
                                p_update = True
                                if "tags" not in p_copy:
                                    p_copy["tags"] = []
                                p_copy["tags"].append({"tag": new_val})

                if not dict_found_tags["SAT_ARCHI:"]:
                    sparql.setReturnFormat("json")
                    sparql.setQuery(
                        """
                     PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                     select   ?method where {
                     <"""
                        + id_lpc
                        + """> lpwc:hasMethod ?m.
                     ?m foaf:name ?method
                     }"""
                    )
                    ret = sparql.query()
                    d = ret.convert()
                    if len(d["results"]["bindings"]) > 1:
                        for val in d["results"]["bindings"]:
                            method = val["method"]["value"]
                            if method.upper() in model_list:
                                new_val = getValNormalized("SAT_MODEL:", method)
                                if new_val.upper() not in tags:
                                    print("FOUND NEW MODEL >", new_val)
                                    p_update = True
                                    if "tags" not in p_copy:
                                        p_copy["tags"] = []
                                    p_copy["tags"].append({"tag": new_val})
                            else:
                                new_val = getValNormalized("SAT_ARCHI:", method)
                                if new_val.upper() not in tags:
                                    # print("FOUND NEW ARCHI >",new_val)
                                    p_update = True
                                    if "tags" not in p_copy:
                                        p_copy["tags"] = []
                                    p_copy["tags"].append({"tag": new_val})
                # METRIC FOR ALL
                # f(dict_found_tags["SAT_METRIC:"]==False):
                sparql.setReturnFormat("json")
                sparql.setQuery(
                    """
                 PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                 select  DISTINCT ?metric where {
                 <"""
                    + id_lpc
                    + """>  lpwc:hasEvaluation ?e.
                 ?e lpwc:hasEvaluationResult ?r.
                 ?r lpwc:metricName ?metric
                 }"""
                )
                ret = sparql.query()
                d = ret.convert()
                if len(d["results"]["bindings"]) > 1:
                    for val in d["results"]["bindings"]:
                        method = val["metric"]["value"]
                        new_val = getValNormalized("SAT_METRIC:", method)
                        if new_val.upper() not in tags:
                            print("NEW METRIC")
                            p_update = True
                            if "tags" not in p_copy:
                                p_copy["tags"] = []
                            p_copy["tags"].append({"tag": new_val})

                # if(dict_found_tags["SAT_DATASET:"]==False
                #  or dict_found_tags["SAT_LANG:"]==False):
                # DATASET FOR ALL
                sparql.setReturnFormat("json")
                sparql.setQuery(
                    """
                 PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                 select  DISTINCT ?title ?lang where {
                 <"""
                    + id_lpc
                    + """> lpwc:usesDataset ?d.
                 ?d dcterms:title ?title. ?d dcterms:language ?lang.
                }"""
                )
                ret = sparql.query()
                d = ret.convert()
                if len(d["results"]["bindings"]) > 1:
                    for val in d["results"]["bindings"]:
                        dataset = val["title"]["value"]
                        new_val = getValNormalized("SAT_DATASET:", dataset)
                        if new_val.upper() not in tags:
                            print("NEWDS")
                            p_update = True
                            if "tags" not in p_copy:
                                p_copy["tags"] = []
                            p_copy["tags"].append({"tag": new_val})
                        lang = val["lang"]["value"]
                        new_val = getValNormalized("SAT_LANG:", lang)
                        if new_val.upper() not in tags:
                            print("NEWLANG")
                            p_update = True
                            if "tags" not in p_copy:
                                p_copy["tags"] = []
                            p_copy["tags"].append({"tag": new_val})

                if (
                    "shortTitle" in p["data"] and len(p["data"]["shortTitle"]) < 2
                ) or "shortTitle" not in p["data"]:
                    sparql.setReturnFormat("json")
                    sparql.setQuery(
                        """
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
                        p_update = True
                        p_copy["shortTitle"] = name

                if (
                    "archive" in p["data"] and len(p["data"]["archive"]) < 5
                ) or "archive" not in p["data"]:
                    p_update = True
                    add = id_lpc.replace(
                        "https://linkedpaperswithcode.com/",
                        "https://paperswithcode.com/",
                    )
                    p_copy["archive"] = add

                if (
                    "archiveLocation" in p["data"]
                    and len(p["data"]["archiveLocation"]) == 7
                ) or "archiveLocation" not in p["data"]:
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
                        p_update = True
                        p_copy["archiveLocation"] = url

                ############## RESULTS
                # sparql.setReturnFormat("json")
                # sparql.setQuery('''
                #   PREFIX lpwc: <https://linkedpaperswithcode.com/property/>
                #     select DISTINCT ?task ?ds ?mname ?mval where {
                #         <'''+id_lpc+'''> lpwc:hasEvaluation ?e.
                #         ?e lpwc:hasDataset ?d.
                #         ?e lpwc:hasTask ?t.
                #         ?t foaf:name ?task.
                #         ?d dcterms:title ?ds.
                #         ?e lpwc:hasEvaluationResult ?res.
                #         ?res lpwc:metricName ?mname.
                #         ?res lpwc:metricValue ?mval.
                #     }
                #     ''')
                # ret = sparql.query()
                # d = ret.convert()
                # if(len(d["results"]["bindings"])>1):
                #     results=[]
                #     for val in d["results"]["bindings"]:
                #         task=val["task"]["value"]
                #         ds=val["ds"]["value"]
                #         result=val["mval"]["value"]
                #         metric=val["mname"]["value"]
                #         results.append({"task":task,"dataset":ds,"res":result,"metric":metric})
                #     p_update=True
                #     p_copy["callNumber"]=json.dumps(results)
                if p_update:
                    dict_to_upt[p["key"]] = p_copy
# except Exception as e:
#    print(e)


if pushToZotero:
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
