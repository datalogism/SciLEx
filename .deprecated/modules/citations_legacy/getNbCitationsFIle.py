#!/usr/bin/env python3
"""
Created on Wed Oct 11 10:29:29 2023

@author: cringwal
"""

import pandas as pd

import scilex.citations.citations_tools as cit_tools

############
# SCRIPT FOR COUNTING CITATIONS FOR EACH PAPERS
############


file = "/user/cringwal/home/Desktop/surveys.csv"
df = pd.read_csv(file)

nb_citations = []
nb_cited = []
for _index, row in df.iterrows():
    doi = row["DOI"]
    from scilex.constants import is_valid

    if is_valid(doi):
        citations = cit_tools.getRefandCitFormatted(str(doi))
        e = cit_tools.countCitations(citations)
        nb_citations.append(e["nb_citations"])
        nb_cited.append(e["nb_cited"])

    else:
        nb_citations.append(0)
        nb_cited.append(0)


df["NbCitations"] = nb_citations
df["NbRef"] = nb_cited

df.to_csv("/user/cringwal/home/Desktop/surveys_citations.csv")
