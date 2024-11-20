![Scilex](img/projectLogoScilex.png)
# SciLEx

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

## :electric_plug: First steps
:heavy_plus_sign: [Install Zotero and Zotero Connector](https://www.zotero.org/download/)

:heavy_plus_sign: [Create a Zotero API key](https://www.zotero.org/support/dev/web_api/v3/start)

:heavy_plus_sign: Create an account for following APIs:
* [SemanticScholar](https://www.semanticscholar.org/product/api/tutorial)
* [Springer](https://dev.springernature.com/)
* [IEEE](https://developer.ieee.org/)
* [Elsevier](https://dev.elsevier.com/)

 
 :heavy_plus_sign: :bangbang: **ADD ALL OF YOUR CREDITS** IN [scilex.config.yml](https://github.com/datalogism/SciLEx/blob/main/src/scilex.config.yml)  :clipboard:

-----
##  :open_file_folder: ScriptBox Content:

*  :clipboard: [Testing APIs scripts](https://github.com/datalogism/SciLEx/blob/main/src/API_tests/) : test and check API services
*  :clipboard: [Collect scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/crawlers) : run a collect > aggregate it and define new collectors 
*  :clipboard: [Zotero scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/Zotero) : extract or push papers data in the lib 
*  :wrench: [Paper With Code scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/PWC) : extract or push papers data in the lib 
*  :wrench: [Citations scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/citations) : extract or push papers data in the lib 
* :wrench: [DOI and ORCID scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/citations) : extract or push papers data in the lib 
* :wrench:[Textmining scripts]( 
https://github.com/datalogism/SciLEx/tree/main/src/text) : extract or push papers data in the lib 

## 🤓 How to contribute to SciLEX ? 

- By extending the API integrated to SciLex
- By Improving the metainformation integration
- By extending it to analytics and vizualisation tools 

Concretely all of theses questions could be leveraged and organize via issues.
