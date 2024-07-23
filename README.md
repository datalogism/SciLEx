![Scilex](img/projectLogoScilex.png)
# Scilex

The SciLEx (Science Literature Exploration) project is a basic python toolbox made for :
* Request and run API crawler related to a research field
* Managing / Parsing / Deduplicating the collected papers
* Consolidate and Enrich a benchmark  
* Exploring the citation  obtained and expanding a network of sci. papers

I developed ScilEx scripts in the context of a systematic review conducted during my Phd, and introduced in :  
> Celian Ringwald. Learning Pattern-Based Extractors from Natural Language and Knowledge Graphs: Applying Large Language Models to Wikipedia and Linked Open Data. AAAI-24 - 38th AAAI Conference on Artificial Intelligence, Feb 2024, Vancouver, France. pp.23411-23412, ⟨10.1609/aaai.v38i21.30406⟩. ⟨hal-04526050⟩
---
## SciLEx Framework

1. Crawl of already existing *surveys* on topic and push it on Zotero
2. Extract *models*, *dataset* from PaperWithCode and push it on Zotero
3. Get DOIs and obtain the citation network
4. Distill it with Zotero API / Annotate it on Zotero and distill your annotations
![Framework](img/Framework.png)
---

## First steps
* [Install Zotero and Zotero Connector](https://www.zotero.org/download/)
* [Create a Zotero API key](https://www.zotero.org/support/dev/web_api/v3/start)
* Creating API tokens for Elsevier/IEEE/Springer/SemanticScholar
* fill [https://github.com/datalogism/SciLEx/blob/main/src/scilex.config.yml](https://github.com/datalogism/SciLEx/blob/main/src/scilex.config.yml) with your API credits

## Testing APIs :file_folder: /src/API_tests/ 

* ElsevierAPI.py
* HALAPI.py
* IEEEAPI
* IstexAPI.py
* OKGK.py [not finished]
* OpenAlexAPI.py
* SemanticScholardAPI.py
* SpringerAPI.py
* arxivAPI.py
* dblpAPI.py
* scholar_test.py
* wikipedia_article_scrapper.py- [not finished]

## Create a collect: :file_folder: /src/crawlers

* Collectors (could be extended): [https://github.com/datalogism/SciLEx/blob/main/src/crawlers/collectors.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/collectors.py)
* Aggregate functions and Zotero format constraining: [https://github.com/datalogism/SciLEx/blob/main/src/crawlers/aggregate.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/aggregate.py)
* Run a collect : [https://github.com/datalogism/SciLEx/blob/main/src/crawlers/run_collecte.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/run_collecte.py)
> Choose your keywords and configure your filepaths


## Push results on Zotero: :file_folder: /src/Zotero

- addLastPapers.py
- getZotero.py
- push_to_Zotero.py

## Paper With Code: :file_folder: /src/PWC
## Citations : :file_folder: /src/citations
## Manage Tags: :file_folder: /src/PWC
## GetDOI and ORCID : :file_folder: /src/ORCID + /src/DOI
## Play with textual data : :file_folder: /src/text

