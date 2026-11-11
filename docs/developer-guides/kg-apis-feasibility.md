# Feasibility of knowledge-graph APIs (issue #30)

Status: assessment only, no collector implemented. Checked October 2026.

| Source | Public API | Auth | What it would add | Verdict |
|--------|-----------|------|-------------------|---------|
| ORKG | REST `https://orkg.org/api/papers` | none | Already collected (`collectors/orkg.py`): keyword search on ~55k papers, ORKG id, DOI, venue, year. Not covered: structured contributions, comparisons, research fields | Covered |
| OpenAIRE | REST `https://api.openaire.eu/search/publications` | none | Already collected (`collectors/openaire.py`): keyword + year search over 200M+ open-access publications | Covered |
| OpenCitations Index | REST `https://api.opencitations.net/index/v2` (`/citations`, `/references`, `/citation-count`, `/reference-count` by `doi:`/`pmid:`/`omid:`), SPARQL endpoint, CC0 dumps | optional access token (header `authorization`) | Citation links (>2 billion, Crossref, DataCite, NIH-OCC, OpenAIRE, JaLC; arXiv 2408.02321). Not a paper-search API | Already used as the last tier of `scilex/citations/` (counts and references). No new collector needed. Possible later: use `/references` and `/citations` for snowballing (Lot C), within the 180 req/min/IP limit |
| AIDA | No REST API found. Knowledge graph (CC BY 4.0) as a dump and a triplestore/SPARQL; tags ~21M publications and patents with CSO topics, affiliation type (academia/industry) and 66 industrial sectors | none | Topic and industry-vs-academia annotations, not literature search. Built on Microsoft Academic Graph (frozen), so recent years are missing | Not recommended as a collector. At most an offline enrichment (CSO topics via the CSO Classifier) |

## Recommendation

- Close #30 as "assessed": ORKG and OpenAIRE are covered; OpenCitations Index is already the citation back-end; AIDA is a static annotated graph without a search API and its data stops with MAG.
- If a KG-based feature is wanted later, the better lever is CSO topic tagging of the aggregated papers (offline, optional), tracked as a separate enhancement.
- Facts about AIDA come from its publications and project pages; its SPARQL endpoint URL and uptime were not verified.
