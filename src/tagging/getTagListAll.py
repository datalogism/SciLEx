#!/usr/bin/env python3
"""
Created on Tue Sep 19 15:50:20 2023

@author: cringwal
"""

import csv

import pandas as pd

############
# SCRIPT FOR GETTING STATS ON TAGS
############

task_dict = {}
method_dict = {}
tag_dict = {}

file_list = [
    "/user/cringwal/home/all_dataset301023.csv",
    "/user/cringwal/home/all_surveys301023.csv",
    "/user/cringwal/home/all_models301023.csv",
]
tags_list = []
for file in file_list:
    print(file)
    # file="/user/cringwal/home/all_models2709.csv"
    df = pd.read_csv(file)
    print(df.columns)
    test = df["Manual Tags"].str.split(";", expand=True)
    tags_list = tags_list + test.values.tolist()
    test2 = df["Automatic Tags"].str.split(";", expand=True)
    tags_list = tags_list + test2.values.tolist()


##### DEPRECIATED
# for t in tags:
#     for val in t :
#         if(val not in tag_dict.keys()):
#             tag_dict[val]=1
#         else:
#             tag_dict[val]+=1
#         if("PWC" in str(val).upper() ):
#             if("task" in val):
#                 if(val not in task_dict.keys()):
#                     task_dict[val]=1
#                     getDataInit=True
#                     attachTag=False
#                     file='/user/cringwal/home/tags_count.csv'
#                     df = pd.read_csv(file)
#                 else:
#                     task_dict[val]+=1

#             elif("method" in val):
#                 if(val not in method_dict.keys()):
#                     method_dict[val]=1
#                 else:
#                     method_dict[val]+=1
for tags in tags_list:
    for val in tags:
        if val not in tag_dict:
            tag_dict[val] = 1
        else:
            tag_dict[val] += 1
        # if("PWC" in str(val).upper() ):
        #     if("task" in val):
        #         if(val not in task_dict.keys()):
        #             task_dict[val]=1
        #         else:
        #             task_dict[val]+=1

        #     elif("method" in val):
        #         if(val not in method_dict.keys()):
        #             method_dict[val]=1
        #         else:
        #             method_dict[val]+=1

tag_list_level1 = {}
tag_list_level0 = {}
for k in tag_dict:
    if str(k) != "None" and str(k) != "nan" and "SAT_" in k.upper():
        dual = k.split(":")
        val = dual[0].strip().upper()
        if val not in tag_list_level1:
            tag_list_level1[val] = tag_dict[k]
        else:
            tag_list_level1[val] += tag_dict[k]
        tag_list_level0[k] = {"level1": val, "nb": tag_dict[k]}


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

# Open a file in write mode.


columns = ["tag", "nb", "level1"]
dict1 = [
    {"tag": k, "level1": tag_list_level0[k]["level1"], "nb": tag_list_level0[k]["nb"]}
    for k in tag_list_level0
]

out_put = "/user/cringwal/home/tag_list_level2.csv"

with open(out_put, "w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=columns)
    writer.writeheader()
    writer.writerows(dict1)


columns = ["tag", "nb"]
dict2 = [{"tag": k, "nb": tag_list_level1[k]} for k in tag_list_level1]
out_put = "/user/cringwal/home/tag_list_level1.csv"

with open(out_put, "w") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=columns)
    writer.writeheader()
    writer.writerows(dict2)
