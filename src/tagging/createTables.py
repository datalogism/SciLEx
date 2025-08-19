#!/usr/bin/env python3
"""
Created on Tue Sep 19 15:50:20 2023

@author: cringwal
"""

############
# SCRIPT FOR COUNTING TAGS
############
import json

import pandas as pd

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
    key_list = []
    item_dict = {}
    for tags in list_tags:
        for item in tags:
            item_clean = item.strip().upper()
            if (":" in item_clean) and (item_clean not in item_dict):
                key = item_clean.split(":")[0]
                key_list.append(key)
    list_columns = [
        "Item Type",
        "Publication Year",
        "Author",
        "Title",
        "Publication Title",
        "Short Title",
        "Conference Name",
        "Archive Location",
        "Rights",
    ]
    tables_res = []
    for _index, row in df.iterrows():
        tempo = {}
        for col in list_columns:
            tempo[col] = row[col]
        tempo["nb_citations"] = 0
        if str(row["Extra"]) != "nan" and "citing" in row.Extra:
            cit = json.loads(row.Extra.replace("'", '"'))
            tempo["nb_citations"] = len(cit["citing"])
        tags = row["Manual Tags"].split(";")
        for key in key_list:
            temp_list = []
            if key in row["Manual Tags"]:
                for t in tags:
                    if key in t:
                        splitted = t.split(":")
                        if len(splitted) > 1:
                            temp_list.append(splitted[1])
            tempo[key] = ",".join(temp_list)
        tables_res.append(tempo)
        print(tempo)
    df2 = pd.DataFrame.from_dict(tables_res)
    df2.to_csv(file.replace(".csv", "table_recap.csv"))
