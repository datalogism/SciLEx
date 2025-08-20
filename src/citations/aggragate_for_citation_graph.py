#!/usr/bin/env python3
"""
Created on Wed Mar  1 17:23:22 2023

@author: cringwal
"""

import json

import pandas as pd
import yaml

############
# SCRIPT FOR AGGREGATING A CITATION NETWORK FROM CSV EXPORT ZOTERO OF EACH LIB
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir = cfg["collect"]["dir"]

surveys = pd.read_csv(collect_dir + "/surveys220323.csv")
models = pd.read_csv(collect_dir + "/models220323.csv")
dataset = pd.read_csv(collect_dir + "/dataset220323.csv")
surveys["orig"] = "surveys"
models["orig"] = "models"
dataset["orig"] = "dataset"

all_data = pd.concat([surveys, models, dataset])
nb_papers = all_data.shape[0]
nb_no_doi = len(all_data[all_data.DOI.isnull()])
nb_no_citation = len(all_data[all_data.Extra.str.contains("['", regex=False)])

all_data["gephi_label"] = ""
for i, row in all_data.iterrows():
    if str(row.Author) != "nan" and row.Author[0] == ",":
        temp = row.Author[2 : len(row.Author)]
        # all_data.at[row.Index, 'Author'] = temp
        all_data._set_value(i, "Author", temp)

    if (
        str(row.Author) != "nan"
        and str(row.Author) != ""
        and str(row["Publication Year"]) != "nan"
        and str(row["Publication Year"]) != ""
    ):
        temp = row.Author.split(",")[0] + "_" + str(row["Publication Year"])
        temp = temp.replace(".0", "")
        if temp.split("_")[0] != "":
            # all_data.at[row.Index 'gephi_label'] = temp
            all_data._set_value(i, "gephi_label", temp)


deduplicated = all_data.DOI.duplicated().sum()
DOI_referenced = all_data.DOI.unique()
count_new = 0
nodes = pd.DataFrame(columns=["Id", "Label", "origin", "Year"])
edges = pd.DataFrame(columns=["Source", "Target"])
for i, row in all_data.iterrows():
    if str(row.Extra) != "nan" and "['" in row.Extra:
        citations = json.loads(row.Extra.replace("'", '"'))
        for cit in citations:
            edges = edges.append({"Source": row.DOI, "Target": cit}, ignore_index=True)
            if cit not in DOI_referenced:
                new = {
                    "Id": cit,
                    "Label": "new_" + str(count_new),
                    "origin": "new paper",
                    "Year": str(row["Publication Year"]).replace(".0", ""),
                }
                nodes = nodes.append(new, ignore_index=True)

                if "dtype" in str(new):
                    print("1", new)
                count_new += 1
            elif cit in DOI_referenced and str(row.DOI) != "nan" and str(row.DOI) != "":
                temp = all_data[cit == all_data.DOI]
                new2 = {
                    "Id": temp["DOI"].values[0],
                    "Label": temp["gephi_label"].values[0],
                    "origin": str(temp["orig"].values[0]),
                    "Year": str(row["Publication Year"]).replace(".0", ""),
                }
                if "dtype" in str(new2):
                    print("2", new2)
                    temp2 = temp
                    print(temp2)
                    break
                nodes = nodes.append(new, ignore_index=True)

for i, row in all_data.iterrows():
    if str(row.DOI) != "nan" and str(row.DOI) != "":
        if row.DOI not in nodes.Id.explode().unique():
            if row.DOI != "" and row.DOI != "nan" and "/" in row.DOI:
                new = {
                    "Id": str(row.DOI),
                    "Label": str(row.gephi_label),
                    "origin": str(row.orig),
                    "Year": str(row["Publication Year"]).replace(".0", ""),
                }
                if "dtype" in str(new):
                    print("3", new)
                nodes = nodes.append(new, ignore_index=True)
nodes["End_Date"] = "2023"
nodes.to_csv(
    collect_dir + "/nodes220323_2.csv", index=False, sep="\t", encoding="utf-8"
)
edges.to_csv(collect_dir + "/edges220323_2.csv", index=False)
