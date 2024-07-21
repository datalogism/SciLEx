#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
"""
import sys
sys.path.append("/user/cringwal/home/Desktop/Scilex-main/src/")
from collectors  import *
from aggregate import *
import yaml


############ 
# SCRIPT FOR RUNNING COLLECT
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml", "r") as ymlfile:
    cfg = yaml.load(ymlfile)
    base_dir=cfg["collect"]["base_dir"]


 
collect_name="before_2023"

#collect_name="knowledge_acquisition_surveys"
#collect_name="structured_data_extraction_surveys"
#collect_name="complex_network_extraction_surveys"
#collect_name="close_relation_extraction_surveys"
collect=False
aggregate=True
if(collect==True):
    years=[2018,2019,2020,2022,2021]
    keywords=["'relation extraction'"]
    
    if not os.path.isdir(base_dir+collect_name):
        os.makedirs(base_dir+collect_name)
        
    path=base_dir+collect_name
    for kwd in keywords:
        print("================BEGIN")
        print(">>>>>>>>>>kwd :",kwd)
        
        filter_params=Filter_param("2010",kwd,"")
        # no year
        print("-------dbpl")
        dbpl=DBLP_collector(filter_params,0,path)
        dbpl.runCollect()
        print("-------arxiv")
        arxiv=Arxiv_collector(filter_params,0,path)
        arxiv.runCollect()
        
        for year in years:
            
            filter_params=Filter_param(year,kwd,"")
            print(">>>>>>>>>>year :",year)
            
            print("-------semschol")
            semschol=SemanticScholar_collector(filter_params,0,path)
            semschol.runCollect()
            
            print("-------ieee")
            ieee=IEEE_collector(filter_params,0,path)
            ieee.runCollect()
            
            print("-------elsevier")
            # try:
            #     elsevier=Elsevier_collector(filter_params,0,path)
            #     elsevier.runCollect()
            # except:
            #     print("API RATE PB")
                
            print("-------springer")
            try:
                 springer=Springer_collector(filter_params,0,path)
                 springer.runCollect()
            except:
                 print("API RATE PB")
                 
            print("-------openalex")
            # openalex=OpenAlex_collector(filter_params,0,path)
            # openalex.runCollect()
            
            print("-------hal")
            hal=HAL_collector(filter_params,0,path)
            hal.runCollect()
            
            print("-------istex")
            istex=Istex_collector(filter_params,0,path)
            istex.runCollect()
        
if(aggregate==True):
    collect_dir=base_dir+collect_name
    collect_dict=collect_dir+"/collect_dict.json"
    filter_=["relation"]
    ############################## BEGIN 
    with open(collect_dict) as json_file:
        data_coll = json.load(json_file)
    
    all_data=[]
    for k in data_coll.keys():
        coll=data_coll[k]
        current_api=coll["API"]
        print(current_api,"-",k)
    
        current_API_dir=collect_dir+"/"+coll["API"]
        current_collect_dir=current_API_dir+"/"+str(k)
        
        if  int(coll["complete"])==1:
            try:
                for path in os.listdir(current_collect_dir):
                    # check if current path is a file
                    if os.path.isfile(os.path.join(current_collect_dir, path)):
                            with open(os.path.join(current_collect_dir, path)) as json_file:
                                    current_page_data = json.load(json_file)
                                    
                            for row in current_page_data["results"]:
                                 if(current_api+'toZoteroFormat' in dir()):
                                # try:
                                     res=eval(current_api+'toZoteroFormat(row)')
                                # except:
                                 #    print("fonction is not existing for > ",current_api)
                                     all_data.append(res)
                                 else:
                                     print("function not yet implemented")
            except:
                print("dir not exist")
                     
                    
    df = pd.DataFrame(all_data)
    df_clean=deduplicate(df)
    #df_clean=filter_data(df_clean,filter_)
    df_clean.reset_index()
    
    
    df_clean.to_csv(collect_dir+"/results_aggragated.csv",sep=";", quotechar='"',quoting=csv.QUOTE_NONNUMERIC)