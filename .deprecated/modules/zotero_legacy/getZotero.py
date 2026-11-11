"""
Created on Tue Nov 23 20:14:03 2021

@author: Celian
"""

from time import sleep

import requests
import yaml

############
# SCRIPT FOR GETTING ZOTERO DATA
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

#url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
r_collections = requests.get(url + libs, headers=headers)
if r_collections.status_code == 200:
    data_collections = r_collections.json()

    data_lib = None
    for d in data_collections:
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
        dict_papers[key] = {"key": key, "nbItems": nb_items, "name": name, "items": []}
        r_items = requests.get(url + libs + key + "/items?limit=100", headers=headers)
        if r_items.status_code == 200:
            dict_papers[key]["items"] = r_items.json()
        sleep(3)
