#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

import requests
from ratelimit import limits, RateLimitException, sleep_and_retry
from csv import writer
from datetime import date
import os
import json
import urllib.parse

import csv
from lxml import etree
import pandas as pd 
import numpy as np

import yaml


############ 
# FUNCTION FOR AGGREGATIONS OF DATA
############

def isNaN(num):
    return num != num

def getquality(df_row, column_names):
    quality = 0
    for col in column_names:
        if df_row[col] != "NA" and not isNaN(df_row[col]):
            quality += 1
    return quality

def filter_data(df_input, filter_):
    return df_input[df_input["abstract"].str.contains('triple', case=False, na=False)]

def deduplicate(df_input):
    df_output = df_input.copy()
    check_columns = ["DOI", "title"]
    column_names = list(df_output.columns.values)
    
    for col in check_columns:
        df2 = df_output[df_output[col] != "NA"]
        df2 = df2.groupby([col])[col].count()
        val_duplicate = df2[df2 > 1].index
        
        if len(val_duplicate) > 0:
            for val in val_duplicate:
                myDict = {key: [] for key in column_names}
                duplicates_temp = df_output[df_output[col] == val]
                quality_list = []
                
                for i in range(len(duplicates_temp)):  
                    idx = duplicates_temp.index[i]
                    qual = getquality(df_output.loc[idx], column_names)
                    quality_list.append(qual)
                    
                    for k in column_names:
                        value = df_output.loc[idx, k]
                        myDict[k].append("NA" if isNaN(value) else value)
                
                max_value = max(quality_list)
                index_value = quality_list.index(max_value)
                
                toAdd_temp = duplicates_temp.iloc[index_value].copy()
                
                for k in column_names:
                    if isNaN(toAdd_temp[k]):
                        toAdd_temp[k] = "NA"
                    if toAdd_temp[k] == "NA":
                        for val in myDict[k]:
                            if not isNaN(val) and val != "NA":
                                toAdd_temp[k] = val
                                break
                
                df_output = df_output.drop(duplicates_temp.index)
                df_output = pd.concat([df_output, toAdd_temp.to_frame().T], ignore_index=True)
                
    return df_output
            
def SemanticScholartoZoteroFormat(row):
    #print(">>SemanticScholartoZoteroFormat")
    #bookSection?
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"}
    zotero_temp["archive"]="SemanticScholar"
    #### publicationTypes is a list Zotero only take one value
    
    if(row["publicationTypes"]!="" and row["publicationTypes"] is not None):
        if(len(row["publicationTypes"])==1):
            
            match row["publicationTypes"][0]:
                case 'JournalArticle':
                    zotero_temp["itemType"]="journalArticle"                
                case 'Conference':
                    zotero_temp["itemType"]='conferencePaper'            
                case 'Conferences':
                    zotero_temp["itemType"]='conferencePaper'
                case 'Book' :
                    zotero_temp["itemType"]= "book"
                case default:
                    pass
                    #print("NEED TO ADD FOLLOWING TYPE >",row["publicationTypes"][0])
                    
        if(len(row["publicationTypes"])>1):
           if('Book' in row["publicationTypes"]):
               zotero_temp["itemType"]= "book"
           elif('Conference' in row["publicationTypes"]):               
                zotero_temp["itemType"]='conferencePaper'
           elif('JournalArticle' in row["publicationTypes"]):               
                 zotero_temp["itemType"]='journalArticle'
           else:
               pass
               #print("NEED TO ADD FOLLOWING TYPES >",row["publicationTypes"])
                
    if(row["publicationVenue"]!="" and row["publicationVenue"] is not None ):
        if("type" in row["publicationVenue"].keys() and row["publicationVenue"]["type"]!=""):
            if(row["publicationVenue"]["type"]=="journal"):
                zotero_temp["itemType"]="journalArticle"                
                if(row["publicationVenue"]["name"]!=""):
                    zotero_temp["journalAbbreviation"]=row["publicationVenue"]["name"]
            if(row["publicationVenue"]["type"]=="conference"):
                zotero_temp["itemType"]="conferencePaper"                
                if(row["publicationVenue"]["name"]!=""):
                    zotero_temp["conferenceName"]=row["publicationVenue"]["name"]
        
            
            
    if(row["journal"]!="" and row["journal"] is not None ):
        if("pages" in row["journal"].keys() and row["journal"]["pages"]!=""):
            zotero_temp["pages"]=row["journal"]["pages"]
            if(zotero_temp["itemType"]=="book"):
                zotero_temp["itemType"]="bookSection"
            
        if("name" in row["journal"].keys() and row["journal"]["name"]!=""):
            zotero_temp["journalAbbreviation"]=row["journal"]["name"]
        if("volume" in row["journal"].keys() and row["journal"]["volume"]!=""):
            zotero_temp["volume"]=row["journal"]["volume"]
            
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"] 
    auth_list=[]
    for auth in row["authors"]:
        if(auth["name"]!="" and auth["name"] is not None):
            auth_list.append(auth["name"] )
    if(len(auth_list)>0):
        zotero_temp["authors"]=";".join(auth_list)
    
    if(row["abstract"]!="" and row["abstract"] is not None):
        zotero_temp["abstract"]=row["abstract"]
        
    if(row["paperId"]!="" and row["paperId"] is not None):
        zotero_temp["archiveID"]=row["paperId"]
        
    if(row["publicationDate"]!="" and row["publicationDate"] is not None):
        zotero_temp["date"]=row["publicationDate"]   
        
    if("DOI" in row["externalIds"].keys()):
        zotero_temp["DOI"]=row["externalIds"]["DOI"]
  
    if(row["url"]!="" and row["url"] is not None):
        zotero_temp["url"]=row["url"]   
    if(row["isOpenAccess"]!="" and row["isOpenAccess"] is not None):
        zotero_temp["rights"]=row["isOpenAccess"]     
    
    return zotero_temp

def IstextoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
    #Genre pas clair
    zotero_temp["archive"]="Istex"
    if(row["genre"]!="" and len(row["genre"])==1):
       match row["genre"][0]:
           case 'research-article':
               zotero_temp["itemType"]="journalArticle"
           case 'conference':
               zotero_temp["itemType"]="conferencePaper"
           case 'article':
               zotero_temp["itemType"]="bookSection"
           case default:
               pass
               #print("IStex NEED TO ADD FOLLOWING TYPE >",row["genre"][0])   
                
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"] 
    auth_list=[]
    for auth in row["author"]:
        if(auth["name"]!="" and auth["name"] is not None):
            auth_list.append(auth["name"] )
            
    if(len(auth_list)>0):
        zotero_temp["authors"]=";".join(auth_list)
    
    # NO ABSTRACT ?
    if("abstract" in row.keys() and row["abstract"]!="" and row["abstract"] is not None):
        zotero_temp["abstract"]=row["abstract"]
        
    if(row["arkIstex"]!="" and row["arkIstex"] is not None):
        zotero_temp["archiveID"]=row["arkIstex"]
        
    if(row["publicationDate"]!="" and row["publicationDate"] is not None):
        zotero_temp["date"]=row["publicationDate"]   
    
    if("doi" in row.keys()):
        if(len(row["doi"])>0):
            list_doi=[]
            for doi in row["doi"]:
                list_doi.append(doi)
            zotero_temp["DOI"]=";".join(list_doi)
            
    if("language" in row.keys()):
         if(len(row["language"])==1):
             zotero_temp["language"]=row["language"][0]
    if("series" in row.keys() and len(row["series"].keys())>0):
             zotero_temp["series"]=row["series"]["title"]
    if("host" in row.keys()):
         if("volume" in row["host"].keys()):
             zotero_temp["volume"]=row["host"]["volume"]
             
         if("issue" in row["host"].keys()):
             zotero_temp["issue"]=row["host"]["issue"]
             
         if("title" in row["host"].keys()):
             zotero_temp["journalAbbreviation"]=row["host"]["title"]
        
             
         if("pages" in row["host"].keys()):
             if(len(row["host"]["pages"].keys())>0 and "fist" in row["host"]["pages"].keys() and "last" in row["host"]["pages"].keys()  and row["host"]["pages"]["first"]!="" and row["host"]["pages"]["last"]!=""):
                 p=row["host"]["pages"]["first"]+"-"+row["host"]["pages"]["last"]
                 zotero_temp["pages"]=p
         if("publisherId" in row["host"].keys() and len(row["host"]["publisherId"])==1):
             zotero_temp["publisher"]=row["host"]["publisherId"][0]
    # NO URL ?
    if("url" in row.keys() and row["url"]!="" and row["url"] is not None):
        zotero_temp["url"]=row["url"]   
    
    if("accessCondition" in row.keys()):
        if(row["accessCondition"]!="" and row["accessCondition"] is not None):
            if(row["accessCondition"]["contentType"]!="" and row["accessCondition"]["contentType"] is not None):
                zotero_temp["rights"]=row["accessCondition"]["contentType"]   
        
    return zotero_temp

def ArxivtoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
    #Genre pas clair
    zotero_temp["archive"]="Arxiv" 
    zotero_temp["itemType"]="Manuscript"
    if(row["abstract"]!="" and row["abstract"] is not None):
        zotero_temp["abstract"]=row["abstract"]
    if(row["authors"]!="" and row["authors"] is not None):
        zotero_temp["authors"]=";".join(row["authors"])
    if(row["doi"]!="" and row["doi"] is not None):
        zotero_temp["DOI"]=row["doi"]
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"]
    if(row["id"]!="" and row["id"] is not None):
        zotero_temp["archiveID"]=row["id"]
    if(row["published"]!="" and row["published"] is not None):
        zotero_temp["date"]=row["published"]   
    if(row["journal"]!="" and row["journal"] is not None):
        zotero_temp["journalAbbreviation"]=row["journal"]
      
    return zotero_temp
    
    
def DBLPtoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
    zotero_temp["archiveID"]=row["@id"]
    row=row['info']
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"] 
    zotero_temp["archive"]="DBLP"
    zotero_temp["title"]=row["title"]
    zotero_temp["date"]=row["year"]
    auth_list=[]
    if("authors" in row.keys()):
        if( type(row["authors"]["author"]) is dict):
            auth_list.append(row["authors"]["author"]["text"] )
        else:
            for auth in row["authors"]["author"]:
                if(auth["text"]!="" and auth["text"] is not None):
                    auth_list.append(auth["text"] )
    #auth_list.append(row["authors"]["author"]["text"] )
    if(len(auth_list)>0):
        zotero_temp["authors"]=";".join(auth_list)
    if("doi" in row.keys()):
        zotero_temp["DOI"]=row["doi"]
    if("pages" in row.keys()):
        zotero_temp["pages"]=row["pages"]
    
    if("access" in row.keys()):
        if(row["access"]!="" and row["access"] is not None):
            zotero_temp["rights"]=row["access"]    
    zotero_temp["url"]=row["url"]   
    
    match row["type"]:
        case  'Journal Articles':
            zotero_temp["itemType"]="journalArticle"
            if("venue" in row.keys()):
                zotero_temp["journalAbbreviation"]=row["venue"]
        case 'Conference and Workshop Papers':
            zotero_temp["itemType"]="conferencePaper"
            if("venue" in row.keys()):
               zotero_temp["conferenceName"]=row["venue"]
        case  'Informal Publications':
            zotero_temp["itemType"]="Manuscript"
        case default:
            pass
            #print("NEED TO ADD FOLLOWING TYPE >",row["type"][0])
    return zotero_temp
    
def HALtoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
    zotero_temp["archiveID"]=row["halId_s"]
    zotero_temp["title"]=row["title_s"][0]
    if("abstract_s" in row.keys()):
        if(row["abstract_s"]!="" and row["abstract_s"] is not None):
            zotero_temp["abstract"]=row["abstract_s"][0]
        
    if("bookTitle_s" in row.keys()):
             zotero_temp["series"]=row["bookTitle_s"]
    
    if("doiId_id" in row.keys()):
             zotero_temp["DOI"]=row["doiId_id"]
    if("conferenceTitle_s" in row.keys()):
             zotero_temp["conferenceName"]=row["conferenceTitle_s"]
             
    
    if("journalTitle_t" in row.keys()):
             zotero_temp["journalAbbreviation"]=row["journalTitle_t"]
    



    zotero_temp["date"]=row["submittedDateY_i"]
    match row["docType_s"]:
        case  'ART':
            zotero_temp["itemType"]="journalArticle"
            if("venue" in row.keys()):
                zotero_temp["journalAbbreviation"]=row["venue"]
        case 'COMM':
            zotero_temp["itemType"]="conferencePaper"
        case 'PROCEEDINGS':
            zotero_temp["itemType"]="conferencePaper"
        case  'Informal Publications':
            zotero_temp["itemType"]="Manuscript"
        case default:
            pass
            #print("NEED TO ADD FOLLOWING TYPE >",row["docType_s"])    
    return zotero_temp
    
# Abstract must be recomposed...
def OpenAlextoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"}     
    
    zotero_temp["archive"]="OpenAlex"
    zotero_temp["archiveID"]=row["id"]
    zotero_temp["DOI"]=row["doi"]
    zotero_temp["title"]=row["title"]
    zotero_temp["date"]=row["publication_date"]
     
    if(row["open_access"]!="" and row["open_access"] is not None and "is_oa" in row["open_access"].keys()):
        zotero_temp["rights"]=row["open_access"]["is_oa"]
      
    auth_list=[]
    for auth in row["authorships"]:
        # Maybe not null !
        if("display_name" in auth["author"].keys()):
            if(auth["author"]["display_name"]!="" and auth["author"]["display_name"] is not None):
                auth_list.append(auth["author"]["display_name"] )
        if(len(auth_list)>0):
         zotero_temp["authors"]=";".join(auth_list)
    
    match row["type"]:
         case  'journal-article':
             zotero_temp["itemType"]="journalArticle"
         case  'book':
            zotero_temp["itemType"]="book"
         case  'book-chapter':
             zotero_temp["itemType"]="bookSection"
         case  'proceedings-article':
             zotero_temp["itemType"]="conferencePaper"
         case  'dissertation':
             pass
         case  'ebook platform':
             pass
         case  'posted-content':
             pass
         case  'repository':
             pass
        
         case default:
             pass
             #print("NEED TO ADD FOLLOWING TYPE >",row["type"])
             
    if("biblio" in row.keys()):
        if(row["biblio"]["volume"] and row["biblio"]["volume"]!=""):
            zotero_temp["volume"]=row["biblio"]["volume"]
        if(row["biblio"]["issue"] and row["biblio"]["issue"]!=""):
            zotero_temp["issue"]=row["biblio"]["issue"]
        if(row["biblio"]["first_page"] and row["biblio"]["first_page"]!="" and row["biblio"]["last_page"] and row["biblio"]["last_page"]!=""):
            zotero_temp["pages"]=row["biblio"]["first_page"]+"-"+row["biblio"]["last_page"]
            
    if("publisher" in row["host_venue"].keys()):
        row["publisher"]=row["host_venue"]["publisher"]
    if("display_name" in row["host_venue"].keys() and "type" in row["host_venue"].keys()):
        if(row["host_venue"]["type"]=="conference"):
            
           zotero_temp["itemType"]="conferencePaper"
           zotero_temp["conferenceName"]=row["host_venue"]["display_name"]
            
        elif(row["host_venue"]["type"]=="journal"):
            zotero_temp["journalAbbreviation"]=row["host_venue"]["display_name"]
            zotero_temp["itemType"]="journalArticle"
        else:
            pass
            #print("NEED TO ADD FOLLOWING TYPE >",row["host_venue"]["type"])
    return zotero_temp

def IEEEtoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
   
    zotero_temp["archive"]="IEEE"
    zotero_temp["archiveID"]=row["article_number"]
    
    if("publication_date" in row.keys() and row["publication_date"]!="" and row["publication_date"] is not None):
        zotero_temp["date"]=row["publication_date"]
    elif("publication_year" in row.keys() and row["publication_year"]!="" and row["publication_year"] is not None):
        zotero_temp["date"]=row["publication_year"]
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"]
    if(row["abstract"]!="" and row["abstract"] is not None):
        zotero_temp["abstract"]=row["abstract"]
    if(row["html_url"]!="" and row["html_url"] is not None):
        zotero_temp["url"]=row["html_url"]
    if(row["access_type"]!="" and row["access_type"] is not None):
        zotero_temp["rights"]=row["access_type"]    
    if("doi" in row.keys()):
        zotero_temp["DOI"]=row["doi"]    
    if("publisher" in row.keys()):
        zotero_temp["publisher"]=row["publisher"]
    if("volume" in row.keys()):
        if(row["volume"]!="" and row["volume"] is not None):
            zotero_temp["volume"]=row["volume"]
    if("issue" in row.keys() and row["issue"]!="" and row["issue"] is not None):
        zotero_temp["issue"]=row["issue"]
        
    if(row["publication_title"]!="" and row["publication_title"] is not None):
        zotero_temp["journalAbbreviation"]=row["publication_title"]
    auth_list=[]
    for auth in row["authors"]["authors"]:
        if(auth["full_name"]!="" and auth["full_name"] is not None):
             auth_list.append( auth["full_name"])
        if(len(auth_list)>0):
         zotero_temp["authors"]=";".join(auth_list)
    
    if(row["start_page"] and row["start_page"]!="" and row["end_page"] and row["end_page"]!=""):
        zotero_temp["pages"]=row["start_page"]+"-"+row["end_page"]
    match row["content_type"]:
         case  'Journals':
             zotero_temp["itemType"]="journalArticle"
         case  'Conferences':
            zotero_temp["itemType"]="conferencePaper"
        
         case default:
             pass
             #print("NEED TO ADD FOLLOWING TYPE >",row["content_type"])
     
    return zotero_temp


def SpringertoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
   
    zotero_temp["archive"]="Springer"
    zotero_temp["archiveID"]=row["identifier"]
    
    if("publicationDate" in row.keys() and row["publicationDate"]!="" and row["publicationDate"] is not None):
        zotero_temp["date"]=row["publicationDate"]
    if(row["title"]!="" and row["title"] is not None):
        zotero_temp["title"]=row["title"]
    if(row["abstract"]!="" and row["abstract"] is not None):
        zotero_temp["abstract"]=row["abstract"]
    #if(row["url"][""]!="" and row["html_url"] is not None):
     #   zotero_temp["url"]=row["html_url"]
    if(row["openaccess"]!="" and row["openaccess"] is not None):
        zotero_temp["rights"]=row["openaccess"]    
    if("doi" in row.keys()):
        zotero_temp["DOI"]=row["doi"]    
    if("publisher" in row.keys()):
        zotero_temp["publisher"]=row["publisher"]
    # if("volume" in row.keys()):
     #   if(row["volume"]!="" and row["volume"] is not None):
      #      zotero_temp["volume"]=row["volume"]
    #if("issue" in row.keys() and row["issue"]!="" and row["issue"] is not None):
     #   zotero_temp["issue"]=row["issue"]
        
    if(row["publicationName"]!="" and row["publicationName"] is not None):
        zotero_temp["journalAbbreviation"]=row["publicationName"]
    auth_list=[]
    for auth in row["creators"]:
        if(auth["creator"]!="" and auth["creator"] is not None):
             auth_list.append( auth["creator"])
        if(len(auth_list)>0):
         zotero_temp["authors"]=";".join(auth_list)
    
    if(row["startingPage"] and row["startingPage"]!="" and row["endingPage"] and row["endingPage"]!=""):
        zotero_temp["pages"]=row["startingPage"]+"-"+row["endingPage"]
    if("Conference" in  row["content_type"]):
       zotero_temp["itemType"]="conferencePaper"
    elif("Article" in  row["content_type"]):
        zotero_temp["itemType"]="journalArticle"
    elif("Chapter" in  row["content_type"]):
        zotero_temp["itemType"]="bookSection"
    else:
        pass
        #print("NEED TO ADD FOLLOWING TYPE >",row["content_type"])
         
    return zotero_temp

def ElseviertoZoteroFormat(row):
    zotero_temp={"title":"NA","publisher":"NA","itemType":"NA","authors":"NA","language":"NA","abstract":"NA","archiveID":"NA","archive":"NA","date":"NA","DOI":"NA","url":"NA","rights":"NA","pages":"NA","journalAbbreviation":"NA","volume":"NA","serie":"NA","issue":"NA"} 
   
    zotero_temp["archive"]="Elsevier"
    if("source-id" in row.keys()) :
        zotero_temp["archiveID"]=row["source-id"]
    
    if("prism:coverDate" in row.keys() and row["prism:coverDate"]!="" and row["prism:coverDate"] is not None):
        zotero_temp["date"]=row["prism:coverDate"]
    if("dc:title" in row.keys() and row["dc:title"]!="" and row["dc:title"] is not None):
        zotero_temp["title"]=row["dc:title"]
  #  if(row["abstract"]!="" and row["abstract"] is not None):
   #     zotero_temp["abstract"]=row["abstract"]
    if(row["prism:url"]!="" and row["prism:url"] is not None):
        zotero_temp["url"]=row["prism:url"]
    if(row["openaccess"]!="" and row["openaccess"] is not None):
        zotero_temp["rights"]=row["openaccess"]    
    if("prism:doi" in row.keys()):
        zotero_temp["DOI"]=row["prism:doi"]    
    if("publisher" in row.keys()):
        zotero_temp["publisher"]=row["publisher"]
    if("prism:volume" in row.keys()):
        if(row["prism:volume"]!="" and row["prism:volume"] is not None):
            zotero_temp["volume"]=row["prism:volume"]
    if("prism:issueIdentifier" in row.keys() and row["prism:issueIdentifier"]!="" and row["prism:issueIdentifier"] is not None):
        zotero_temp["issue"]=row["prism:issueIdentifier"]
        
    if("prism:publicationName" in row.keys() and row["prism:publicationName"]!="" and row["prism:publicationName"] is not None):
        zotero_temp["journalAbbreviation"]=row["prism:publicationName"]
    #auth_list=[]
    #for auth in row["creators"]:
    #    if(auth["creator"]!="" and auth["creator"] is not None):
    #         auth_list.append( auth["creator"])
    #    if(len(auth_list)>0):
    #     zotero_temp["authors"]=";".join(auth_list)
    if("dc:creator" in row.keys()):
        if(row["dc:creator"] and row["dc:creator"]!="" ):
            zotero_temp["authors"]=row["dc:creator"]
    if(row["prism:pageRange"] and row["prism:pageRange"]!="" ):
        zotero_temp["pages"]=row["prism:pageRange"]
    
    if("subtypeDescription" in row.keys() and row["subtypeDescription"] is not None and row["subtypeDescription"]!=""):
        if("Conference" in  row["subtypeDescription"]):
           zotero_temp["itemType"]="conferencePaper"
        elif("Article" in  row["subtypeDescription"]):
            zotero_temp["itemType"]="journalArticle"
        elif("Chapter" in  row["subtypeDescription"]):
            zotero_temp["itemType"]="bookSection"
        else:
            pass
            #print("NEED TO ADD FOLLOWING TYPE >",row["subtypeDescription"])
             
    return zotero_temp

                
               
         
