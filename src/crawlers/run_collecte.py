#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

from collectors  import *
from aggregate import *
import yaml


############ 
# SCRIPT FOR RUNNING COLLECT
############


# Get the current working directory
current_directory = os.getcwd()

# Construct the full path to the YAML file
yaml_file_path = os.path.join(current_directory, "src/scilex.config.yml")

# Load configuration from YAML file
with open(yaml_file_path, "r") as ymlfile:
    config = yaml.safe_load(ymlfile)

output_dir = config['output_dir']
collect = config['collect']
aggregate = config['aggregate']
years = config['years']
keywords = config['keywords']

# Use the configuration values
if collect:
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    path = output_dir

print(f"Collecting data to: {output_dir}")
print(f"Directory path: {path}")
print(f"Years: {years}")
print(f"Keywords: {keywords}")

for kwd in keywords:
    print("================BEGIN")
    print(">>>>>>>>>>kwd :",kwd)
    
    filter_params=Filter_param(years,kwd,"")

    print("-------dbpl")
    dbpl=DBLP_collector(filter_params,0,path)
    dbpl.runCollect()

    print("-------arxiv")
    arxiv=Arxiv_collector(filter_params,0,path)
    arxiv.runCollect()

    #WAITING STATUS
    print("-------ieee")
    ieee=IEEE_collector(filter_params,0,path)
    ieee.runCollect()

    print("-------elsevier")
    elsevier=Elsevier_collector(filter_params,0,path)
    elsevier.runCollect()

    # print("-------springer")
    # springer=Springer_collector(filter_params,0,path)
    # springer.runCollect()
    
    # for year in years:
        
    #     filter_params=Filter_param(year,kwd,"")
    #     print(">>>>>>>>>>year :",year)
        
        # print("-------semschol")
        # semschol=SemanticScholar_collector(filter_params,0,path)
        # semschol.runCollect()
        
        # print("-------ieee")
        # ieee=IEEE_collector(filter_params,0,path)
        # ieee.runCollect()
        
        # print("-------elsevier")
        # # try:
        # #     elsevier=Elsevier_collector(filter_params,0,path)
        # #     elsevier.runCollect()
        # # except:
        # #     print("API RATE PB")
            
        # print("-------springer")
        # try:
        #         springer=Springer_collector(filter_params,0,path)
        #         springer.runCollect()
        # except:
        #         print("API RATE PB")
                
        # print("-------openalex")
        # # openalex=OpenAlex_collector(filter_params,0,path)
        # # openalex.runCollect()
        
        # print("-------hal")
        # hal=HAL_collector(filter_params,0,path)
        # hal.runCollect()
        
        # print("-------istex")
        # istex=Istex_collector(filter_params,0,path)
        # istex.runCollect()
    
if aggregate:
    filter_ = ["relation"]

    # Check if collect_dir exists, otherwise create it
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    collect_dict = os.path.join(output_dir, "collect_dict.json") 
    ############################## BEGIN 
    if os.path.exists(collect_dict):
        with open(collect_dict) as json_file:
            data_coll = json.load(json_file)
    else:
        data_coll = {}

    all_data=[]
    for k in data_coll.keys():
        coll=data_coll[k]
        current_api=coll["API"]
        print(current_api,"-",k)

        current_API_dir=output_dir+"/"+coll["API"]
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


    df_clean.to_csv(output_dir+"/results_aggragated.csv",sep=";", quotechar='"',quoting=csv.QUOTE_NONNUMERIC)
