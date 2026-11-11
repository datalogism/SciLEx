#!/usr/bin/env python3
"""
Created on Tue Sep 19 15:50:20 2023

@author: cringwal
"""

import csv

import pandas as pd

############
# SCRIPT FOR COUNTING TAGS
############


task_dict = {}
method_dict = {}
tag_dict = {}

file_list = [
    "/user/cringwal/home/datasets2025.csv",
    "/user/cringwal/home/models2025.csv",
    "/user/cringwal/home/surveys2025.csv",
]
tags_list = []
list_tags = []
for file in file_list:
    print(file)
    # file="/user/cringwal/home/all_models2709.csv"
    df = pd.read_csv(file)
    print(df.columns)
    print(df["Manual Tags"])
    test = df["Manual Tags"].to_string().split(";")

    ############
    # SCRIPT FOR MANAGING TAGS CREATED : DELETION - ADD - TO KEEP
    ############
    print(list(df["Manual Tags"]))
    list_tags = list_tags + [
        tag_list.split(";") for tag_list in list(df["Manual Tags"])
    ]
item_dict = {}
for tags in list_tags:
    for item in tags:
        item_clean = item.strip().upper()
        if ":" in item_clean:
            if item_clean not in item_dict:
                key = item_clean.split(":")[0]
                val = item_clean.split(":")[1]
                item_dict[item_clean] = {"key": key, "val": val, "nb": 1}
            else:
                item_dict[item_clean]["nb"] += 1
print(item_dict)


print("NB TAGS >>>>>>>>", len(list(item_dict.keys())))

nb_sup1 = 0
nb_sup100 = 0
nb_sup1000 = 0
for tag in item_dict:
    if item_dict[tag]["nb"] > 1:
        nb_sup1 += 1
    if item_dict[tag]["nb"] > 100:
        nb_sup100 += 1
    if item_dict[tag]["nb"] > 1000:
        nb_sup1000 += 1
print("NB >1 >>>>>>>>", nb_sup1)
print("NB >100 >>>>>>>>", nb_sup100)
print("NB >1000 >>>>>>>>", nb_sup1000)

columns = ["key", "value", "nb"]
dict2 = [
    {"key": item_dict[k]["key"], "value": item_dict[k]["val"], "nb": item_dict[k]["nb"]}
    for k in item_dict
]
# Open a file in write mode.

out_put = "/user/cringwal/home/Desktop/tags_count_all2025.csv"

with open(out_put, "w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=columns)
    writer.writeheader()
    writer.writerows(dict2)
