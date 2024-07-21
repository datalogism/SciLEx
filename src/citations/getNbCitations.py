#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct 11 10:29:29 2023

@author: cringwal
"""
import pandas as pd
import json
############ 
# SCRIPT FOR COUNTING CITATIONS FOR EACH PAPERS
############


file='/user/cringwal/home/all_models301023_2.csv'
df = pd.read_csv(file)

nb_citations=[]
nb_cited=[]
for index, row in df.iterrows():
    citations=row["Extra"]
    if(citations!="" and citations is not None and str(citations)!="nan"):
        try:
            e=json.loads(citations.replace("'",'"'))
            print(e["citing"])
            nb_citations.append(len(e["citing"]))
            nb_cited.append(len(e["cited"]))
        except:
            nb_citations.append(0)
            nb_cited.append(0)
            
    else:
        nb_citations.append(0)
        nb_cited.append(0)
        
    
    
df["NbCitations"]= nb_citations
df["NbRef"]=nb_cited

df.to_csv('/user/cringwal/home/all_models301023_citations_2.csv')