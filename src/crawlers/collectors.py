#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 25 09:07:19 2023

@author: cringwal
"""

############## TO DO 
# https://doaj.org/api/docs
# https://api.base-search.net/ 
# https://www.doabooks.org/en/article/api-search-doab
# https://core.ac.uk/services/api
# https://graph.openaire.eu/develop/
# + Springer

import requests
from ratelimit import limits, RateLimitException, sleep_and_retry
from csv import writer
from datetime import date
import os
import json
import urllib.parse
from lxml import etree



import yaml
############ 
# CLASS USED FOR PARAMETRIZE CRAWLERS
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml", "r") as ymlfile:
    cfg = yaml.load(ymlfile)
    sem_scholar_api=cfg["sem_scholar"]["api_key"]
    springer_api=cfg["springer"]["api_key"]
    elsevier_api=cfg["elsevier"]["api_key"]
    ieee_api=cfg["ieee"]["api_key"]
    openalex_mail=cfg["email"]

class Filter_param:
    def __init__(self, year, keywords, focus):
        # In second
        self.year = year
        self.keywords = keywords
        self.focus=focus
        
    def get_dict_param(self):
        return(Filter_param.__dict__)
    def get_year(self):
        return self.year
    def get_keywords(self):
        return self.keywords
   # def get_focus(self):
   #     return self.focus
        
        

class API_collector:
    def __init__(self, filter_param, save, data_path):
        # In second
        self.filter_param = filter_param
        self.save= save     
        self.rate_limit = 10
        self.datadir=data_path
        self.collectId=0
        self.lastpage=0
        self.big_collect=0
        self.max_by_page=100
        self.api_url=""
        self.complete=0
        
    def set_collectId(self, collectId):
        self.collectId = collectId
    def set_lastpage(self, lastpage):
        self.lastpage = lastpage
    def set_complete(self, complete):
        self.complete = complete
        
    def get_collectId(self):
        return self.collectId   
    def get_lastpage(self):
        return self.lastpage
    def get_api_name(self):
        return self.api_name
    def get_keywords(self):
        return self.filter_param.get_keywords()
    def get_year(self):
        return self.filter_param.get_year()
    def get_dataDir(self):
        return self.datadir
    def get_apiDir(self):
        return self.get_dataDir()+"/"+self.get_api_name()
    def get_collectDir(self):
        return self.get_apiDir()+"/"+str(self.get_collectId())
    def get_fileCollect(self):
        return self.get_dataDir()+"/collect_dict.json"
    def get_url(self):
         return self.api_url
    def get_apikey(self):
          return self.api_key
    def get_configurated_url(self):
        return self.get_url()
    def get_max_by_page(self):
        return self.max_by_page
    def get_ratelimit(self):
        return self.rate_limit
    
    def api_call_decorator(self,configurated_url):
        print("REQUEST")
        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            print("REQUEST")
            try:
                resp = requests.get(configurated_url)
            except:
                print("PB AFTER REQUEST")
            return resp
        return access_rate_limited_decorated(configurated_url)
    
    def toZotero():
        pass
    
    def get_configurated_url(self):
        return self.get_url()
    
    def getCollectId(self):
        try:
            with open(self.get_fileCollect()) as json_file:
                data_coll = json.load(json_file) 
            print("LOAD FILE")
        except:
            print("EMPTY FILE")
            data_coll = {}
            
        
        id_collect=self.get_collectId()
        found=False
        max_id=-1
        for k in data_coll.keys():
            if(data_coll[k]["API"]==self.get_api_name() and data_coll[k]["kwd"]==self.get_keywords() and data_coll[k]["year"]==str(self.get_year())):
                self.set_collectId(k)
                self.set_lastpage(data_coll[k]["last_page"])
                self.set_complete(data_coll[k]["complete"])
                found=True
                print("FOUND")
                break
            max_id=max(int(k),max_id)
        print("max_id",max_id)
        if(found==False):
            
            print("NOT FOUND")
            if(max_id!=-1):
                print("max_id!=-1")
                print("new id ?" ,str(max_id+1))
                self.set_collectId(str(max_id+1))
                print("new id ?" ,self.get_collectId())
                data_coll[str(self.get_collectId())]={"API":self.get_api_name(),"kwd":self.get_keywords(),"year":str(self.get_year()),"last_page":0,"complete":0}
            if(max_id==-1):
                print("max_id=-1")
                data_coll["0"]={"API":self.get_api_name(),"kwd":self.get_keywords(),"year":str(self.get_year()),"last_page":0,"complete":0}
        
            with open(self.get_fileCollect(), 'w') as json_file:
                json.dump(data_coll, json_file)
        
    def createCollectDir(self):
        if not os.path.isdir(self.get_apiDir()):
            os.makedirs(self.get_apiDir())
        if not os.path.isdir(self.get_collectDir()):
            os.makedirs(self.get_collectDir())
            
    def savePageResults(self,global_data,page):
        
        self.createCollectDir()
        print(self.get_collectDir()+"/page_"+str(page))
        with open(self.get_collectDir()+"/page_"+str(page), 'w', encoding='utf8') as json_file:
            json.dump(global_data, json_file)
        with open(self.get_fileCollect()) as json_file:
            data_coll = json.load(json_file)
        data_coll[str(self.get_collectId())]["last_page"]=page
        with open(self.get_fileCollect(), 'w') as json_file:
            json.dump(data_coll, json_file)
                
    def parsePageResults(response,page):
        page_with_results =response.json()
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        # loop through partial list of results
        results = page_with_results['data']
        for result in results:
            page_data["results"].append(result)
            SemanticScholartoZoteroFormat(result)
        total=int(page_with_results["total"])
        page_data["total"]=total
        
        return page_data

    def flagAsComplete(self):
        with open(self.get_fileCollect()) as json_file:
            data_coll = json.load(json_file)
        data_coll[str(self.get_collectId())]["complete"]=1
        with open(self.get_fileCollect(), 'w') as json_file:
            json.dump(data_coll, json_file)
    
    def add_offset_param(self,page):
        return self.get_configurated_url().format((page-1)*self.get_max_by_page())
        
    def get_offset(self, page):
        return (page-1)*self.get_max_by_page()
    def runCollect(self):
        
        self.getCollectId()
        
        if(self.complete==1):
            print("COLLECT ALREADY COMPLETED")
        else:
            page = int(self.get_lastpage())+1
            has_more_pages = True
            
            if(self.big_collect == 0):
                fewer_than_10k_results = True
            else:
                fewer_than_10k_results = False
                
            
            while has_more_pages and fewer_than_10k_results:
                offset=self.get_offset(page)
                url = self.get_configurated_url().format(offset)
                print('\n' + url)
                
                
                response=self.api_call_decorator(url)
                try: 
                    page_data=self.parsePageResults(response,page)
                    
                    
                    self.savePageResults(page_data,page)
                    
                    self.set_lastpage(int(page)+1)
                    
                    
                    has_more_pages = len(page_data["results"]) == self.get_max_by_page()
                    
                    page=self.get_lastpage()
                    
                    fewer_than_10k_results = page_data["total"]  <= 10000
                    print(">>>>>",str(offset),"/",page_data["total"])
                    
                    if(fewer_than_10k_results == False):
                        print("QUERY TOO LARGE MUST BE REVIEWED")
                except:
                    print("PB with results")
                    has_more_pages=False
            
            if(has_more_pages == False):
                print("NO MORE PAGE")
                self.flagAsComplete()
            else:
                time_needed= page_data["total"]/self.get_max_by_page()/60/60
                print("TOTAL EXTRACTION WILL NEED >",time_needed,"minutes")
                

## OK 
class SemanticScholar_collector(API_collector):
    
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
  
        self.rate_limit = 100
        self.max_by_page = 100
        self.api_name = "SemanticScholar"
        self.api_key = sem_scholar_api
        self.api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        
    def api_call_decorator(self,configurated_url):
        @sleep_and_retry
        @limits(calls=self.get_ratelimit(), period=1)
        def access_rate_limited_decorated(configurated_url):
            resp = requests.get(configurated_url, headers={'x-api-key':  self.get_apikey()})
            return resp
        
        return access_rate_limited_decorated(configurated_url)
            
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        page_with_results =response.json()
       
        # loop through partial list of results
        try:
            total=page_with_results["total"]
            page_data["total"]=int(total)
            if(page_data["total"]>0):
                results = page_with_results['data']
                for result in results:
                    page_data["results"].append(resueedback on the Anthology?
        except:
            print(response.status_code)
        
        return page_data
    
    def get_configurated_url(self):
        #kw=self.get_keywords().replace("AND ","").replace("'","")
        keywords=urllib.parse.quote(self.get_keywords())
        return self.get_url()+"?query="+keywords+"&fieldsOfStudy=Computer Science,Linguistics,Mathematics&fields=title,abstract,url,venue,publicationVenue,citationCount,externalIds,referenceCount,s2FieldsOfStudy,publicationTypes,publicationDate,isOpenAccess,openAccessPdf,authors,journal,fieldsOfStudy&year="+str(self.get_year())+"&limit="+str(self.get_max_by_page())+"&offset={}"

### IS WORKING ?
class IEEE_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.api_name="IEEE"
        self.rate_limit = 100
        self.max_by_page = 200
        self.api_key=ieee_api
        self.api_url="http://ieeexploreapi.ieee.org/api/v1/search/articles"
        
    def get_configurated_url(self):
        # PUB YEAR ?
        keywords=urllib.parse.quote(self.get_keywords())
        return self.get_url()+"?apikey="+self.get_apikey()+"&format=json&max_records="+str(self.get_max_by_page())+"&sort_order=asc&sort_field=article_number&article_title="+keywords+"&publication_year="+str(self.get_year())+"&start_record={}"
   
    # REALLY NEEDED ?
    # def api_call_decorator(self,configurated_url):
    #     @sleep_and_retry
    #     @limits(calls=self.get_ratelimit(), period=1)
    #     def access_rate_limited_decorated(configurated_url):
    #         resp = requests.get(configurated_url, headers={'x-api-key':  self.get_apikey()})
    #         return resp
        
    #     return access_rate_limited_decorated(configurated_url)
            
    
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
      
        page_with_results =response.json()
        # loop through partial list of results
        total=page_with_results["total_records"]
        page_data["total"]=int(total)
        if(page_data["total"]>0):
            results = page_with_results['articles']
            for result in results:
                page_data["results"].append(result)
        
        return page_data
## OK 
class Elsevier_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 8
        self.max_by_page = 100
        self.api_name="Elsevier"
        self.api_key=elsevier_api
        self.api_url="https://api.elsevier.com/content/search/scopus"
        
   
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
      
        page_with_results =response.json()
        
        # loop through partial list of results
        results = page_with_results['search-results']
        total=results["opensearch:totalResults"]
        page_data["total_nb"]=int(total)
        if(page_data["total_nb"]>0):
            for result in results["entry"]:
                page_data["results"].append(result)
            
        
        return page_data
    
    def get_configurated_url(self):
        keywords=urllib.parse.quote(self.get_keywords()+" AND PUBYEAR = "+str(self.get_year()))
        return self.get_url()+"?query="+keywords+"&count="+str(self.get_max_by_page())+"&apiKey="+str(self.get_apikey())+"&limit="+str(self.get_max_by_page())+"&start={}"

# FILTER BY YEAR ? OK
class DBLP_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 10
        self.max_by_page = 1000
        self.filter_param.year=""
        self.api_name="DBLP"
        self.api_url="https://dblp.org/search/publ/api"
        
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
      
        page_with_results =response.json()
         
        # loop through partial list of results
        results = page_with_results['result']
        total=results["hits"]["@total"]
        page_data["total"]=int(total)
        print("TOTAL >",page_data["total"])
        if(page_data["total"]>0):
            for result in results["hits"]["hit"]:
                page_data["results"].append(result)
            
        return page_data
    
    def get_configurated_url(self):
        return self.get_url()+"?q="+self.get_keywords()+"&format=json&h="+str(self.get_max_by_page())+"&f={}"

class OpenAlex_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 10
        self.max_by_page = 200
        self.api_name = "OpenAlex"
        self.api_url = "https://api.openalex.org/works"
        
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        page_with_results =response.json()
       
        # loop through partial list of results
        results = page_with_results['results']
        for result in results:
            page_data["results"].append(result)
        total=page_with_results["meta"]["count"]
        page_data["total"]=int(total)
        
        return page_data
    #FILTERED BY ABTRACT
    def get_configurated_url(self):
        return self.get_url()+"?filter=publication_year:"+str(self.get_year())+",fulltext.search:"+self.get_keywords()+"&per-page="+str(self.get_max_by_page())+"&mailto="+openalex_mail+"&page={}"
    
    def get_offset(self, page):
        return page
    
class HAL_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 10
        self.max_by_page = 500
        self.api_name = "HAL"
        self.api_url = "http://api.archives-ouvertes.fr/search/"
        
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        page_with_results =response.json()
       
        # loop through partial list of results
        results =  page_with_results['response']
        
        for result in results["docs"]:
            page_data["results"].append(result)
            
        total=results["numFound"]
        page_data["total"]=int(total)
        
        return page_data
    
    def get_configurated_url(self):
        return self.get_url()+"?q="+self.get_keywords()+"&fl=title_s,abstract_s,label_s,arxivId_s,audience_s,authFullNameIdHal_fs,bookTitle_s,classification_s,conferenceTitle_s,docType_s,doiId_id,files_s,halId_s,jel_t,journalDoiRoot_s,journalTitle_t,keyword_s,type_s,submittedDateY_i&fq=submittedDateY_i:"+str(self.get_year())+"&rows="+str(self.get_max_by_page())+"&start={}"

class Arxiv_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.filter_param.year=""
        self.rate_limit = 3
        self.max_by_page = 500
        self.api_name = "Arxiv"
        self.api_url = "http://export.arxiv.org/api/query"
        
     
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
        page_with_results =response.content
        tree = etree.fromstring(page_with_results)
        entries = tree.xpath('*[local-name()="entry"]')
       
        # loop through partial list of results
        for entry in entries :
            current={}
            current["id"]=entry.xpath('*[local-name()="id"]')[0].text 
            current["updated"]=entry.xpath('*[local-name()="updated"]')[0].text 
            current["published"]=entry.xpath('*[local-name()="published"]')[0].text 
            current["title"]=entry.xpath('*[local-name()="title"]')[0].text 
            current["abstract"]=entry.xpath('*[local-name()="summary"]')[0].text 
            authors=entry.xpath('*[local-name()="author"]')
            current["doi"]=""
            current["journal"]=""
            auth_list=[]
            for auth in authors:
                auth_list.append(auth.xpath('*[local-name()="name"]')[0].text)
            current["authors"]=auth_list
            
            try: 
                current["pdf"]=entry.xpath('*[local-name()="link" and @title="pdf"]')[0].text 
            except:
                pass
                #print("NO pdf")
            try: 
                current["doi"]=entry.xpath('*[local-name()="doi"]')[0].text 
            except:
                try: 
                    current["doi"]=entry.xpath('*[local-name()="link" and @title="doi"]')[0].text 
                except:
                    pass
                   # print("NO doi")
                
            try: 
                 current["comment"]=entry.xpath('*[local-name()="comment"]')[0].text 
            except:
                pass
                #print("NO comment")
            #cuurent["url"]=entry.xpath('*[local-name()=" arxiv:comment"]')[0].text 
            try: 
                current["journal"]=entry.xpath('*[local-name()="journal_ref"]')[0].text 
            except:
                pass
                #print("NO journal")
            try:
                main_cat=entry.xpath('*[local-name()="primary_category"]')[0].attrib['term']
            except:
                pass
                #print("NO main categories")
            try:
                categories=entry.xpath('*[local-name()="category"]')
                cat_list=[]
                for cat in categories:
                    cat_list.append(cat.attrib['term'])
                current["categories"]=cat_list
            except:
                pass
                #print("NO categories")    
            page_data["results"].append(current)
        total_raw = tree.xpath('*[local-name()="totalResults"]')
        total=int(total_raw[0].text)
        page_data["total"]=int(total)
        
        return page_data
    
    def get_configurated_url(self):
       return self.get_url()+"?search_query="+self.get_keywords()+"&sortBy=lastUpdatedDate&max_results="+str(self.get_max_by_page())+"&start={}"

class Istex_collector(API_collector): 
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
         super().__init__(filter_param, save, data_path)
         self.rate_limit = 3
         self.max_by_page = 500
         self.api_name = "Istex"
         self.api_url = "https://api.istex.fr/document/"
         
    def parsePageResults(self,response,page):
         page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
         page_with_results =response.json()
         #print(page_with_results)
         # loop through partial list of results
         results =  page_with_results
         
         for result in results["hits"]:
             page_data["results"].append(result)
             
         total=results["total"]
         page_data["total"]=int(total)
         
         return page_data
     
    def get_configurated_url(self):
        #kwd=" AND ".join(self.get_keywords().split(" "))
        kwd=self.get_keywords()
        kwd2="(publicationDate:"+str(self.get_year())+" AND title:("+kwd+") OR abstract:("+kwd+"))"
        return self.get_url()+"?q="+kwd2+"&output=*&size"+str(self.get_max_by_page())+"&from={}"

class Springer_collector(API_collector):
    """store file metadata"""
    def __init__(self, filter_param, save, data_path):
        super().__init__(filter_param, save, data_path)
        self.rate_limit = 8
        self.max_by_page = 100
        self.api_name="Springer"
        self.api_key=springer_api
        self.api_url="http://api.springernature.com/meta/v2/json"
        
   
    def parsePageResults(self,response,page):
        page_data = {"date_search":str(date.today()), "id_collect": self.get_collectId(), "page": page,"total":0,"results":[]}
      
        page_with_results =response.json()
        
        # loop through partial list of results
        results = page_with_results['records']
        
        total=page_with_results["result"]["total"]
        page_data["total_nb"]=int(total)
        if(page_data["total_nb"]>0):
            for result in results["entry"]:
                page_data["results"].append(result)
            
        
        return page_data
    
    def get_configurated_url(self):
        
        return self.get_url()+"?q=year:"+str(self.get_year())+" AND "+self.get_keywords()+"&p="+str(self.get_max_by_page())+"&api_key="++str(self.get_apikey())+"&s={}"
    
