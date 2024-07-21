#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 30 16:06:58 2023

@author: cringwal
"""

import requests
from time import sleep
import random
import string
import json
import pandas as pd

def getWriteToken():
    
    return ''.join(random.choices(string.ascii_uppercase + string.ascii_lowercase, k=32))

import yaml


############ 
# SCRIPT FOR PUSHING A COLLECT TO ZOTERO
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml", "r") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir=cfg["collect"]["dir"]
    api_key=cfg["zotero"]["api_key"]

research_coll="knowledge_extraction_surveys"
collect_dir="/user/cringwal/home/Desktop/THESE YEAR1/SAT/"+research_coll
data = pd.read_csv(collect_dir+'/results_filtered.csv')


relevant_data=data[data["relevant"].fillna(-1).astype('int')==1]
templates_dict={}
collect_dir+"/"+research_coll
url="https://api.zotero.org/users/5689645"
libs="/collections/"
headers={'Zotero-API-Key':api_key}
current_col_key=None

while current_col_key is None :
    r_collections = requests.get(url+libs, headers=headers)
    
    if(r_collections.status_code ==  200 ):
        data_collections=r_collections.json()
        found_parent=False
        for d in data_collections:
            if(d["data"]["name"] == "StateOfArtStudy"):
                id_lib=d["data"]["key"]
                found_parent=True
                break
        
        found=False
        for d in data_collections:
            if(d["data"]["parentCollection"] == str(id_lib) and  d["data"]["name"]==research_coll):
                print("FOUND current Collection >", d["data"]["name"] )
                current_col_key=d["data"]["key"]
                break
        if current_col_key is None :
            ## CREATE COLLECTION
            #headers={'Zotero-Write-Token':"19a4f01ad623aa7214f82347e3711f56"}
            headers={'Zotero-API-Key':api_key,'Zotero-Write-Token':getWriteToken(),"Content-Type":"application/json"}
            body=json.dumps([{ "name" : research_coll, "parentCollection" : str(id_lib) }])
            req2 = requests.post(url+"/collections", headers=headers,data=body)
            
for index, row in relevant_data.iterrows():
    itemType=row["itemType"]
    if(itemType!="" and itemType!="NA" and pd.isna(itemType) == False):
        if(itemType not in templates_dict.keys()):                
            resp = requests.get("https://api.zotero.org/items/new?itemType="+itemType)
            template=resp.json()
            templates_dict[itemType]=template
        
        current_temp=templates_dict[itemType]
        current_temp["collections"]=[current_col_key]
        common_cols=["publisher","title","date","DOI","archive","url","rights","pages","journalAbbreviation","conferenceName","volume","issue"]
        for col in common_cols:    
            if(col in current_temp.keys() and col in row.keys()):
                current_temp[col]=str(row[col])
        
        current_temp["abstractNote"]=str(row["abstract"])
        if("archiveLocation" in current_temp.keys()):    
            current_temp["archiveLocation"]=str(row["archiveID"])
            
        template_authors=current_temp["creators"][0].copy()
        auth_list=[]
        if("authors" in row.keys()):
            if(row["authors"]!="" and row["authors"]!="NA" and pd.isna(row["authors"]) == False):
                authors=row["authors"].split(";")
                for auth in authors:
                    current_auth=template_authors.copy()
                    current_auth["firstName"]=auth
                    auth_list.append(current_auth)
                current_temp["creators"]=auth_list
            
        body = json.dumps([current_temp])
        headers={'Zotero-API-Key':api_key,'Zotero-Write-Token':getWriteToken(),"Content-Type":"application/json"}
        
        req2 = requests.post(url+"/items", headers=headers,data=body)



   