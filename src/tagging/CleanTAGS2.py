#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Nov 29 15:50:09 2023

@author: cringwal
"""


from SPARQLWrapper import SPARQLWrapper, XML
import requests
import json



import yaml


############ 
# SCRIPT FOR REPLACING TAGS DEPENDING OF CHANGES DEFINED IN A FILE 
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml", "r") as ymlfile:
    cfg = yaml.load(ymlfile)
    collect_dir=cfg["collect"]["dir"]
    api_key=cfg["zotero"]["api_key"]
    
    
def getitemData(item_key):
    print("HEY")
    libs="/collections/"
    url="https://api.zotero.org/groups/5259782/"+libs
    headers={'Zotero-API-Key':api_key}
    test = requests.get(url+"/items/"+item_key+"?format=json", headers=headers)
    print(">",test)
    resp=test.json()
    return resp

def patch_withdata(item_key,data_dict):
    print("----patch >",item_key)
    libs="/collections/"
    url="https://api.zotero.org/groups/5259782/"+libs
    data=getitemData(item_key)
    last_v=data["version"]
    headers={'Zotero-API-Key':api_key,'If-Unmodified-Since-Version':str(last_v)}
    body = json.dumps(data_dict)
    resp=requests.patch(url+"/items/"+item_key, data=body,  headers=headers)
    return resp.status_code

def getValNormalized(val):
    val_2=''.join(x for x in val.title() if not x.isspace())
    return val_2

import pandas as pd
file="/user/cringwal/home/Desktop/THESE/SURVEY/TAG_LIST_FINAL.csv"
df = pd.read_csv(file)
tags_tofill_bytype={"models":[],"surveys":[],"datasets":[]}
for index, row in df.iterrows():
    if("X" in str(row["models"]).upper()):
        tags_tofill_bytype["models"].append(row["tag"].upper())
    
    if("X" in str(row["surveys"]).upper()):
        tags_tofill_bytype["surveys"].append(row["tag"].upper())
    
    if("X" in str(row["datasets"]).upper()):
        tags_tofill_bytype["datasets"].append(row["tag"].upper())
        
getDataInit=True
getDataToUpdate=True

if getDataInit==True:
    papers_to_update={}
    libs="/collections/"
    url="https://api.zotero.org/groups/5259782/"
    headers={'Zotero-API-Key':api_key}
    r_collections = requests.get(url+libs+"?limit=100", headers=headers)
    if(r_collections.status_code ==  200 ):
        data_collections=r_collections.json()
        data_lib=None
        id_lib=None
        lib_list=[]
        for d in data_collections: 
            if("subset" not in d["data"]["name"] and len(d["data"]["name"])>2):
                lib_list.append(d)
                
        dict_papers={}
        for lib in lib_list:
            name_lib=lib["data"]["name"]   
            papers_to_update[name_lib]={}
            print(name_lib) 
            nb_items=lib["meta"]["numItems"]
            key=lib["key"]
            start=0
            r_items = requests.get(url+libs+key+"/items?limit=100&start="+str(start), headers=headers)
            if(r_items.status_code ==  200 ):
                
                dict_papers[key]={"key":key,"nbItems":nb_items,"name":name_lib,"items":[]}
                dict_papers[key]["items"]=r_items.json()
                nb_res=int(r_items.headers["Total-Results"])
                
                while(nb_res>start+100):
                    if(start!=0):
                        r_items = requests.get(url+libs+key+"/items?limit=100&start="+str(start), headers=headers)
                        if(r_items.status_code ==  200 ):
                            dict_papers[key]["items"]=dict_papers[key]["items"]+r_items.json()
                    start+= 100
                    for paper in dict_papers[key]["items"]:
                        
                        if(paper["data"]['itemType']!="attachment" and "title" in paper["data"].keys()):
                            tags=paper["data"]["tags"]
                            tags_corr=[]
                            for tagggg in tags:
                                item=tagggg["tag"]
                                if("?" not in item):
                                    tag_part=item.split(":")
                                    dim=tag_part[0].upper()
                                    if(dim in tags_tofill_bytype[name_lib]):
                                        val=getValNormalized(tag_part[1])
                                        new=dim+":"+val
                                        new=new.strip()
                                        if(new not in tags_corr):
                                            tags_corr.append(new)
                                        
                            
                            for todo in tags_tofill_bytype[name_lib]:
                                
                                found=False
                                for tag_in in tags_corr:
                                    if(todo in tag_in):
                                        found=True
                                if found == False:
                                   tags_corr.append( todo+":?")
                            
                            if(len(tags_corr)>0):
                               papers_to_update[name_lib][paper["key"]]=tags_corr 
                               
            
if getDataToUpdate==True:       
    for lib in papers_to_update.keys():
        print(lib)
        if(lib != "models"):
            for zid in papers_to_update[lib].keys():
                print(papers_to_update[lib][zid])
                data= getitemData(zid)
                changes={"tags":[]}
                for TAG in papers_to_update[lib][zid]:
                    changes["tags"].append({"tag": TAG}) 
                if(len(changes["tags"])>0):
                    print(changes["tags"])
                    try:
                        patch_withdata(zid,changes)
                    except:
                        print("PB")