#!/usr/bin/env python3
"""
Created on Tue Nov 21 15:43:06 2023

@author: cringwal
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Nov 21 15:15:23 2023

@author: cringwal
"""

import requests
from SPARQLWrapper import SPARQLWrapper

sparql = SPARQLWrapper("https://orkg.org/triplestore")


import yaml

############
# SCRIPT FOR GETTING ORKG DATA
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

getDataInit = True
getDOIData = True
pushToZotero = False
url = "https://api.zotero.org/groups/5259782/"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}


if getDataInit:
    keep_citation_data = False
    papers_by_coll = {}

    r_collections = requests.get(url + libs + "?limit=100", headers=headers)
    if r_collections.status_code == 200:
        data_collections = r_collections.json()
        data_lib = None
        id_lib = None
        lib_list = []
        for d in data_collections:
            lib_list.append(d)
            papers_by_coll[d["data"]["name"]] = {}

        for lib in lib_list:
            dict_papers = {}
            name = lib["data"]["name"]
            print(name)
            nb_items = lib["meta"]["numItems"]
            key = lib["key"]
            print(key)
            dict_papers = {"key": key, "nbItems": nb_items, "name": name, "items": []}
            start = 0
            r_items = requests.get(
                url + libs + key + "/items?limit=100&start=" + str(start),
                headers=headers,
            )
            if r_items.status_code == 200:
                dict_papers["items"] = r_items.json()
                nb_res = int(r_items.headers["Total-Results"])

                while nb_res > start + 100:
                    if start != 0:
                        r_items = requests.get(
                            url + libs + key + "/items?limit=100&start=" + str(start),
                            headers=headers,
                        )
                        if r_items.status_code == 200:
                            dict_papers["items"] = dict_papers["items"] + r_items.json()
                    start += 100
            papers_by_coll[name] = dict_papers


list_found = []
nb_all = 0
for p in papers_by_coll["models"]["items"]:
    if p["data"]["itemType"] != "attachment" and "DOI" in p["data"]:
        # print(p)
        title = p["data"]["title"]
        DOI = p["data"]["DOI"]
        if str(DOI) not in ["", "nan", "NAN", "NA"]:
            nb_all += 1

            sparql.setQuery(
                '''
            PREFIX orkgr: <http://orkg.org/orkg/resource/>
            PREFIX orkgc: <http://orkg.org/orkg/class/>
            PREFIX orkgp: <http://orkg.org/orkg/predicate/> 
            select distinct ?paper ?DOI where {
            ?paper orkgp:P26 ?DOI.
            FILTER (?DOI="'''
                + DOI
                + """"^^xsd:string)
            } LIMIT 100
            """
            )

            try:
                sparql.setReturnFormat("json")
                ret = sparql.query()
                d = ret.convert()
                print(title)
                print(d["results"]["bindings"])
                if len(d["results"]["bindings"]) == 1:
                    list_found += d["results"]["bindings"]
            except Exception as e:
                print(e)
