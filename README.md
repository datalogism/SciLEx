![Scilex](img/projectLogoScilex.png)
# Scilex

The SciLEx (Science Literature Exploration) project is a basic python scriptbox made for :
* Request and run API crawler related to a research field
* Managing / Parsing / Deduplicating the collected papers
* Consolidate and Enrich a benchmark  
* Exploring the citations links and expanding a network of sci. papers

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

Working APIs:
* [ElsevierAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/ElsevierAPI.py)
* [HALAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/HALAPI.py)
* [IEEEAPI](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/IEEEAPI.py)
* [IstexAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/IstexAPI.py)
* [OpenAlexAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/OpenAlexAPI.py)
* [SemanticScholardAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/SemanticScholardAPI.py)
* [SpringerAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/SpringerAPI.py)
* [arxivAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/arxivAPI.py)
* [dblpAPI.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/dblpAPI.py)
* [scholar_test.py](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/scholar_test.py)

Not Finished:

* OKGK.py 
* wikipedia_article_scrapper.py

## Create a collect: :file_folder: /src/crawlers

* Declaration of collectors : [collectors.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/collectors.py) (could be extended)
* Aggregate functions and Zotero format constraining: [aggregate.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/aggregate.py)
* Run a collect : [run_collecte.py](https://github.com/datalogism/SciLEx/blob/main/src/crawlers/run_collecte.py)
> Choose your keywords and configure your filepaths


##  Zotero: :file_folder: /src/Zotero

- Push collect to Zotero : push_to_Zotero.py
- Add new papers : addLastPapers.py
- Get papers data from Zotero: getZotero.py

## Paper With Code: :file_folder: /src/PWC
- Push collect to Zotero : push_to_Zotero.py
- Add new papers : addLastPapers.py
- Get papers data from Zotero: getZotero.py
- 
## Citations : :file_folder: /src/citations
## Manage Tags: :file_folder: /src/PWC
## GetDOI and ORCID : :file_folder: /src/ORCID + /src/DOI
## Play with textual data : :file_folder: /src/text

