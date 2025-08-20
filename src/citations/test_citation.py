#!/usr/bin/env python3
"""
Created on Thu Jun  1 16:00:56 2023

@author: cringwal
"""

import requests
import yaml
from ratelimit import limits, sleep_and_retry

############
# SCRIPT FOR GETTING ABSTRACT FROM linkedpaperswithcode
############


with open("/user/cringwal/home/Desktop/Scilex-main/src/scilex.config.yml") as ymlfile:
    cfg = yaml.load(ymlfile)
    api_key = cfg["zotero"]["api_key"]


url = "https://api.zotero.org/users/5689645"
libs = "/collections/"
headers = {"Zotero-API-Key": api_key}
api_crossref = "https://opencitations.net/index/coci/api/v1/citations/"


@sleep_and_retry
@limits(calls=10, period=1)
def getReferences(doi):
    print("REQUEST -doi :", doi)
    try:
        resp = requests.get(api_crossref + doi)
    except:
        print("PB AFTER REQUEST")
    return resp


doi = "10.3233/faia200755"
citations = getReferences(doi)
resp_cit = citations.json()
