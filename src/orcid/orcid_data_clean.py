# -*- coding: utf-8 -*-
"""
Created on Tue May 17 10:42:30 2022

@author: Celian
"""
import json

import orcid
import requests


collect_dir='/user/cringwal/home/Desktop/THESE_YEAR1/SAT/Models-Dataset-Surveys/230523/ORCID_surveys/'
with open(collect_dir+'dict_orcid_all_checked_raw.json', 'r') as f:
  data = json.load(f)

tab_id_keywords=[]
tab_lifepath=[]

for k in data.keys():
    for k2 in data[k].keys():
         if(k2 == 'kwd'):
             if("keyword" in data[k][k2].keys()):
                 for kwd in data[k][k2]["keyword"]:
                    content=data[k][k2]
                    kwd_list=kwd["content"].split(",")
                    for kwd_token in kwd_list:
                        clean=kwd_token.strip().lower()
                        tab_id_keywords.append([k,clean])
                        #if(clean not in keywords_ids.keys()):
                         #   keywords_ids[clean]=[]
                        #keywords_ids[clean].append(k)
                        
                        
         if(k2 == 'educations'):
            
             if("education-summary" in data[k][k2].keys()):
                 for edu in data[k][k2]["education-summary"]:
                         #,'place':""
                    tempo={"start":"","end":"","role":"","org":"","city":"","country":"","dpt":"","type":"educ"}
                    if('department-name' in edu.keys()):
                        tempo['dpt']=edu['department-name']
                    if('role-title' in edu.keys()):
                        role=edu['role-title']
                        tempo["role"]=role
                    if('start-date' in edu.keys()):
                        start=edu['start-date']
                        if start:
                            if( 'year' in start.keys()):
                                tempo["start"]=start["year"]["value"]
                    if('end-date' in edu.keys()):
                        end=edu['end-date']
                        if(end):
                            if('year' in end.keys()):
                                tempo["end"]=end["year"]["value"]
                    if('organization' in edu.keys()):
                        org=edu["organization"]
                        if("name" in org.keys()):
                            tempo["org"]=org["name"]
                        if('address' in org.keys()):
                            tempo["city"]=org["address"]["city"]
                            tempo["country"]=org["address"]["country"]
                   # if(k not in id_lifepath.keys()):    
                    #    id_lifepath[k]=[]
                    tab_lifepath.append([k]+list(tempo.values()))
                    
         if(k2 == "employments"):
                 if("employment-summary" in data[k][k2].keys()):
                     for employ in data[k][k2]["employment-summary"]:
                         #,'place':""
                         tempo={"start":"","end":"","role":"","org":"","city":"","country":"","dpt":"","type":"work"}
                         if('department-name' in employ.keys()):
                             tempo['dpt']=employ['department-name']
                             if('role-title' in employ.keys()):
                                 role=employ['role-title']
                                 tempo["role"]=role
                             if('start-date' in employ.keys()):
                                 start=employ['start-date']
                                 if start:
                                    if( 'year' in start.keys()):
                                         tempo["start"]=start["year"]["value"]
                             if('end-date' in employ.keys()):
                                 end=employ['end-date']
                                 if(end):
                                     if('year' in end.keys()):
                                         tempo["end"]=end["year"]["value"]
                             if('organization' in employ.keys()):
                                 org=employ["organization"]
                                 if("name" in org.keys()):
                                     tempo["org"]=org["name"]
                                 if('address' in org.keys()):
                                     tempo["city"]=org["address"]["city"]
                                     tempo["country"]=org["address"]["country"]
                             
                             tab_lifepath.append([k]+list(tempo.values()))
        
         if(k2 == "address"):         
             print(data[k][k2])

import csv
import pandas as pd
orcid_keywords = pd.DataFrame(tab_id_keywords,columns = ['orcid', 'kwd'])
orcid_lifepath = pd.DataFrame(tab_lifepath,columns = ['orcid', 'start','end','role','org','city',"country","dpt","type"])
orcid_keywords.to_csv(collect_dir+'/keywords_all__checked_orcid.csv', index=False, sep='\t', encoding='utf-8')
orcid_lifepath.to_csv(collect_dir+'/lifepath_all__checked_orcid.csv', index=False)