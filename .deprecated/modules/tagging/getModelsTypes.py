#!/usr/bin/env python3
"""
Created on Tue Sep 19 15:50:20 2023

@author: cringwal
"""

import csv

import pandas as pd
import yaml

############
# SCRIPT FOR COUNTING TAGS REGARDING A CSV FILE
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]
    api_key = cfg["zotero"]["api_key"]

file = "/user/cringwal/home/all_models2709.csv"
df = pd.read_csv(file)
print(df.columns)
test = df["Manual Tags"].str.split(";", expand=True)
tags = test.values.tolist()
test2 = df["Automatic Tags"].str.split(";", expand=True)
tags2 = test2.values.tolist()
task_dict = {}
method_dict = {}
tag_dict = {}
for t in tags:
    for val in t:
        if val not in tag_dict:
            tag_dict[val] = 1
        else:
            tag_dict[val] += 1
        if "PWC" in str(val).upper():
            if "task" in val:
                if val not in task_dict:
                    task_dict[val] = 1
                else:
                    task_dict[val] += 1

            elif "method" in val:
                if val not in method_dict:
                    method_dict[val] = 1
                else:
                    method_dict[val] += 1

for t in tags2:
    for val in t:
        if val not in tag_dict:
            tag_dict[val] = 1
        else:
            tag_dict[val] += 1
        if "PWC" in str(val).upper():
            if "task" in val:
                if val not in task_dict:
                    task_dict[val] = 1
                else:
                    task_dict[val] += 1

            elif "method" in val:
                if val not in method_dict:
                    method_dict[val] = 1
                else:
                    method_dict[val] += 1


print("NB TAGS >>>>>>>>", len(list(tag_dict.keys())))

nb_sup1 = 0
nb_sup100 = 0
nb_sup1000 = 0
for tag in tag_dict:
    if tag_dict[tag] > 1:
        nb_sup1 += 1
    if tag_dict[tag] > 100:
        nb_sup100 += 1
    if tag_dict[tag] > 1000:
        nb_sup1000 += 1

print("NB >1 >>>>>>>>", nb_sup1)
print("NB >100 >>>>>>>>", nb_sup100)
print("NB >1000 >>>>>>>>", nb_sup1000)


columns = ["tag", "nb"]
dict2 = [{"tag": k, "nb": tag_dict[k]} for k in tag_dict]
# Open a file in write mode.
out_put = "/user/cringwal/home/tags_count.csv"

with open(out_put, "w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=columns)
    writer.writeheader()
    writer.writerows(dict2)
