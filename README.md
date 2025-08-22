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

## :electric_plug: Deploy and use Scilex for the first time

 👉 Please read our quick tutorial [here](https://github.com/datalogism/SciLEx/blob/main/Tuto_firstContact.md) 🏃‍♂️🏃

-----
##  :open_file_folder: ScriptBox Content:

Many scripts where developed and not yet integrated, if you are intested please take a look in the following directories:

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

## API integrated 
|                    | SemanticScholar  | OpenAlex                   | Istex | IEEE                       | HAL                                               | Elsevier | DBLP | Arxiv | Springer |
|--------------------|------------------|----------------------------|-------|----------------------------|---------------------------------------------------|----------|------|-------|----------|
| requiere API key ? | optional         | NA                         |       | X                          | NA                                                | X        |      |       | X        |
| Rate limit         | 100 req/sec      | 10/seq - 100000/days       |       | 10/sec –  200/days         |                                                   |          |      | 3/seq | 8/seq    |
| Year               | X                | X                          | X     | X                          | X                                                 | X        |      |       | X        |
| Abstract content   | X                |                            | X     | X                          |                                                   |          |      |       |          |
| Title content      | X                |                            | X     | X                          | X                                                 |          |      |       | X        |
| Document type      | X                | X                          | ?     | X                          | X                                                 |          |      |       | X        |
| Classification ?   | fieldOfStudy     | conceptID, Wikidataconcept |       | IEEE thesaurus, indexterms | acm\_classif, HAL classif, keyword, JELclassif... |          |      |       | keywords |
| title              | X                |                            | X     | X                          | X                                                 | X        | X    | X     | X        |
| abstract           | X                |                            | X     | X                          | X                                                 |          |      | X     | X        |
| DOi                | X                | X                          | X     | X                          |                                                   | X        | X    | X     | X        |
| citations metrics  | X                | X                          |       | X                          |                                                   | X        |      |       |          |
| publication data   | X                | X                          | X     | X                          |                                                   | X        | X    |       | X        |
| isOpen             | X                | X                          | X     | X                          |                                                   | X        | X    |       | X        |
| journal            | X                | X                          | X     | X                          |                                                   |          | X    | X     | X        |
| conference         | X                | X                          | X     | X                          |                                                   |          | X    | X     | X        |
| authors            | name,  author id | name, orcid, inst          |       | X                          | X                                                 | X        | X    | X     | X        |
| publicationType    | X                | X                          | X     | X                          | X                                                 | X        | X    |       | X        |
| referenced\_works  |                  | X                          | X     |                            |                                                   |          |      |       |          |
| related\_works     |                  | X                          |       |                            |                                                   |          |      |       |          |
| keywords           |                  | X                          | X     | X                          | X                                                 |          |      | X     |          |
| related entities   |                  | X                          | X     |                            |                                                   |          |      |       |          |
| qualityIndicators  |                  |                            | X     |                            |                                                   |          |      |       |          |
| enrichments        |                  |                            | X     | X                          |                                                   |          |      |       |          |
| fieldOfstudy       | X                |                            | X     |                            |                                                   |          |      |       | X        |
