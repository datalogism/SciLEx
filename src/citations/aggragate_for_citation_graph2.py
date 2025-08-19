#!/usr/bin/env python3
"""
Created on Thu May  4 10:44:22 2023

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


def check_existance(dict_of_values, df):
    v = df.iloc[:, 0] == df.iloc[:, 0]
    for key, value in dict_of_values.items():
        v &= df[key] == value
    return v.any()


surveys = pd.read_csv(collect_dir + "surveys2025.csv")
models = pd.read_csv(collect_dir + "models2025.csv")
dataset = pd.read_csv(collect_dir + "datasets2025.csv")
surveys["orig"] = "surveys"
models["orig"] = "models"
dataset["orig"] = "dataset"

all_data = pd.concat([surveys, models, dataset], ignore_index=True)
all_data.columns = all_data.columns.str.replace(" ", "_")
all_data["code"] = "False"
all_data["bench"] = "False"
# all_data['title'] = str('none')
all_data["gephi_label"] = ""
all_data.reset_index()
nb_papers = all_data.shape[0]
nb_no_doi = len(all_data[all_data.DOI.isnull()])
nb_no_citation = len(all_data[all_data.Extra.str.contains("['", regex=False)])

all_data["index_col"] = all_data.index
all_data2 = all_data.copy()
for row in all_data2.itertuples():
    # print(getattr(row, "index_col"))
    renamed = False
    if str(row.Manual_Tags) != "nan" and "PWC:havecode" in row.Manual_Tags:
        # print("code")
        all_data.at[row.index_col, "code"] = "True"

    if str(row.Manual_Tags) != "nan" and "PWC:isbenchmarked" in row.Manual_Tags:
        print("benchmarked")

        all_data.at[row.index_col, "bench"] = "True"

    if str(row.Author) != "nan" and str(row.Author)[0] == ",":
        temp = row.Author[2 : len(row.Author)]
        # all_data.at[row.Index, 'Author'] = temp

        all_data.at[row.index_col, "Author"] = temp

        # ""
        # "PWC:"

    if str(row.Short_Title) not in ["nan", "", "NA"]:
        label_t = str(row.Short_Title)
        if "," in str(row.Short_Title):
            label_t = str(row.Short_Title).split(", ")[0]
        temp = label_t.replace("  ", "")
        temp = temp + "_" + str(row.Publication_Year)
        temp = temp.replace(".0", "")
        all_data.at[row.index_col, "gephi_label"] = temp

    elif str(row.Author) not in ["nan", "", "NA"] and str(row.Publication_Year) not in [
        "nan",
        "",
        "NA",
    ]:
        temp = [
            txt.strip()
            for txt in str(row.Author).replace(";", ",").replace("  ", "").split(",")
            if txt != " " and txt != ""
        ]
        temp = temp[0].split(" ")[0] if " " in temp[0] else temp[0]
        # temp="_".join(row.Author.replace(";",",").split(",")[0].split(" "))

        temp = temp + "_" + str(row.Publication_Year)
        temp = temp.replace(".0", "")

        # if(temp.split("_")[0]!=""):
        #     #all_data.at[row.Index 'gephi_label'] = temp
        all_data.at[row.index_col, "gephi_label"] = temp
        # else:
        #     print(row.Author)
        #     print(temp)

    else:
        print(">>>>>>>>>>>>>>>>> PB :")
        print(row.Title)
        print(row.orig)
    # if(renamed==False):
    #     print(row.Author)
    #     print(row.orig)


deduplicated = all_data.DOI.duplicated().sum()
DOI_referenced = all_data.DOI.unique()
count_new = 0
nodes = pd.DataFrame(
    columns=["Id", "Label", "origin", "Year", "code", "bench", "typeofpaper", "source"]
)
edges = pd.DataFrame(columns=["Source", "Target"])
added_node = []
for _i, row in all_data.iterrows():
    if str(row.Extra) != "nan" and "citing" in row.Extra and "cited" in row.Extra:
        citations = json.loads(row.Extra.replace("'", '"'))

        for citing in citations["citing"]:
            added = False
            if citing not in DOI_referenced:
                added = True
                new = {
                    "Id": citing,
                    "Label": "new_" + str(count_new),
                    "origin": "new paper",
                    "Year": str(row["Publication_Year"]).replace(".0", ""),
                    "code": "none",
                    "bench": "none",
                    "typeofpaper": "none",
                    # "title":"none",
                    "source": "none",
                }
                if citing not in added_node:
                    nodes = nodes.append(new, ignore_index=True)
                    added_node.append(citing)
                count_new += 1
            elif (
                citing in DOI_referenced
                and str(row.DOI) != "nan"
                and str(row.DOI) != ""
                and str(row.DOI) != "None"
                and str(row.DOI) != "not found"
            ):
                temp = all_data[citing == all_data.DOI]
                added = True
                new2 = {
                    "Id": temp["DOI"].values[0],
                    "Label": temp["gephi_label"].values[0],
                    "origin": str(temp["orig"].values[0]),
                    "Year": str(row["Publication_Year"]).replace(".0", ""),
                    "code": str(temp["code"].values[0]),
                    "bench": str(temp["bench"].values[0]),
                    "typeofpaper": str(temp["Item_Type"].values[0]),
                    # "title":temp["Title"].values[0],
                    "source": str(temp["Archive"].values[0]),
                }

                if citing not in added_node:
                    print(new2["Label"])
                    print(new2["origin"])
                    nodes = nodes.append(new2, ignore_index=True)
                    added_node.append(citing)

            current = {"Source": row.DOI, "Target": citing}
            if not check_existance(current, edges) and citing != row.DOI and added:
                edges = edges.append(current, ignore_index=True)

        for cited in citations["cited"]:
            added = False
            if cited not in DOI_referenced:
                new = {
                    "Id": cited,
                    "Label": "new_" + str(count_new),
                    "origin": "new paper",
                    "Year": str(row["Publication_Year"]).replace(".0", ""),
                    "code": "none",
                    "bench": "none",
                    "typeofpaper": "none",
                    "title": "none",
                    "source": "none",
                }

                added = True
                if cited not in added_node:
                    nodes = nodes.append(new, ignore_index=True)
                    added_node.append(cited)
                count_new += 1
            elif (
                cited in DOI_referenced
                and str(row.DOI) != "nan"
                and str(row.DOI) != ""
                and str(row.DOI) != "None"
                and str(row.DOI) != "not found"
            ):
                temp = all_data[cited == all_data.DOI]

                added = True
                new2 = {
                    "Id": temp["DOI"].values[0],
                    # "title":temp["Title"].values[0],
                    "Label": temp["gephi_label"].values[0],
                    "origin": str(temp["orig"].values[0]),
                    "Year": str(row["Publication_Year"]).replace(".0", ""),
                    "code": str(temp["code"].values[0]),
                    "bench": str(temp["bench"].values[0]),
                    "typeofpaper": str(temp["Item_Type"].values[0]),
                    "source": str(temp["Archive"].values[0]),
                }

                if cited not in added_node:
                    print(new2["Label"])
                    print(new2["origin"])
                    nodes = nodes.append(new2, ignore_index=True)
                    added_node.append(cited)

            current = {"Source": cited, "Target": row.DOI}
            if not check_existance(current, edges) and cited != row.DOI and added:
                edges = edges.append(current, ignore_index=True)

for _i, row in all_data.iterrows():
    if str(row.DOI) != "nan" and str(row.DOI) != "":
        if row.DOI not in nodes.Id.explode().unique():
            if row.DOI != "" and row.DOI != "nan" and "/" in row.DOI:
                new = {
                    "Id": str(row.DOI),
                    "Label": str(row.gephi_label),
                    "origin": str(row["orig"]),
                    "Year": str(row["Publication_Year"]).replace(".0", ""),
                    "code": str(row["code"]),
                    "bench": str(row["bench"]),
                    "typeofpaper": str(row["Item_Type"]),
                    # "title":temp["Title"].values[0],
                    "source": str(row["Archive"]),
                }
                if str(row.DOI) not in added_node:
                    print(new["Label"])
                    print(new["origin"])
                    nodes = nodes.append(new, ignore_index=True)
                    added_node.append(str(row.DOI))

nodes["End_Date"] = "2023"
nodes.to_csv(collect_dir + "/nodes230523.csv", index=False, sep="\t", encoding="utf-8")
edges.to_csv(collect_dir + "/edges230523.csv", index=False)
