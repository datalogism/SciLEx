# ⑥ Enrich

<img src="../_static/modules/enrich.png" alt="Enrich module" height="80">

Enrich adds data from external sources (and a few local computations) to the papers.
Run it before [③ Screen](screen.md) on every paper, or after it with **Only the papers
kept in ③ Screen** (included or maybe). One tab per source; answers are cached in the
collection folder (`<source>_cache.json`), so a rerun only asks for papers not looked
up yet. Existing values are never overwritten, and enrichers running together each
write only the cells they changed.

| Sub-module | What it adds | Network |
|---|---|---|
| <a href="#citations"><img src="../_static/modules/sub/enrich-citations.png" height="30" alt="Citations"></a> | References and citing papers | Semantic Scholar, Crossref, OpenCitations |
| <a href="#papers-with-code"><img src="../_static/modules/sub/enrich-pwc.png" height="30" alt="Papers with Code"></a> | Tasks, methods, benchmarks, GitHub repositories | paperswithcode.co |
| <a href="#crossref"><img src="../_static/modules/sub/enrich-crossref.png" height="30" alt="Crossref"></a> | Abstracts, venues, dates, licences, funders | Crossref |
| <a href="#linked-papers-with-code"><img src="../_static/modules/sub/enrich-lpwc.png" height="30" alt="Linked Papers With Code"></a> | Tasks, methods, datasets, repositories, conference | LPWC |
| <a href="#orkg"><img src="../_static/modules/sub/enrich-orkg.png" height="30" alt="ORKG"></a> | Research fields and problems | ORKG |
| <a href="#search-keywords"><img src="../_static/modules/sub/enrich-search-keywords.png" height="30" alt="Search keywords"></a> | `Collect_KW<n>:` and `BK:` tags | none |
| <a href="#paper-types"><img src="../_static/modules/sub/enrich-paper-types.png" height="30" alt="Paper types"></a> | `PAPER_TYPE:` tag | none |
| <a href="#citation-metrics"><img src="../_static/modules/sub/enrich-metrics.png" height="30" alt="Citation metrics"></a> | `metric_*` columns and metric tags | none |

**Order.** Fetch abstracts first (Crossref, or the abstract step of the aggregation):
search keywords, paper types and the eligibility criteria read the abstracts, and the
page warns when many are missing. Citations come before Citation metrics, Snowballing
and the Graph.

A single paper can be enriched from its notice in [Explore](explore.md#enrich-one-paper).

## Citations

References and citing papers of the corpus, needed by
[Snowballing](extend.md#snowballing), the [Graph](analyses.md#graph) and the citation
metrics. Source: Semantic Scholar then Crossref then OpenCitations (default), Crossref +
OpenCitations, or OpenCitations only (open data, no key). Slow without a Semantic
Scholar key. Same as `scilex-enrich-citations`.

A fourth source, **Zotero snapshot**, reads instead the citation notes that earlier
pushes wrote in the review's Zotero library and freezes them
(`zotero_citations.json`), so the metrics are computed on a stable network.
Results go to `citations_cache.json` and `citers_cache.json` in the collection folder.

## Papers with Code

Tasks, methods, evaluated benchmarks, the official GitHub repository and its stars,
from [paperswithcode.co](https://paperswithcode.co) (anonymous API, no key). Same as
`scilex-enrich`.

## Crossref

By DOI: fills empty abstracts, venues, volumes, pages, dates, publishers, licences and
ISSNs, and adds `crossref_type`, `crossref_cited_by` and `crossref_funders`. Set the
Crossref e-mail in [API keys](workspace.md#api-keys) for the faster "polite" service.

## Linked Papers With Code

By arXiv id, else exact title: `lpwc_tasks`, `lpwc_methods`, `lpwc_datasets`,
`lpwc_repositories`, `lpwc_conference`, `lpwc_paper` — the terms the
[knowledge graph](export.md#knowledge-graph) links to.

## ORKG

By DOI, else exact title: `orkg_paper`, `orkg_research_fields`,
`orkg_research_problems` (of the paper's contributions) from the Open Research
Knowledge Graph.

## Search keywords

Tags each paper with the keywords of `scilex.yml` found in its title or abstract:
`Collect_KW<n>:keyword` in `collect_keywords` (group *n*, exact phrase, any case) and
`BK:keyword` in `bonus_keyword_tags` (bonus keywords, all meaningful words present).
Collected papers only carry the keywords of the queries that found them; this gives
keywords to papers imported from Zotero, a knowledge graph or BibTeX, or added by
snowballing. Existing tags are kept; the summary lists the keywords found in no paper.

## Paper types

Every paper gets one type, as a `PAPER_TYPE:<type>` tag:

| Type | Cue words (title decisive, abstract only when repeated) |
|---|---|
| Review or State of the art | survey, review, overview, state of the art, taxonomy, tutorial… |
| Benchmark | benchmark, leaderboard, shared task, comparative study… |
| Dataset | dataset, corpus, treebank, knowledge base, test collection… |
| Model or Method | no cue: the common case |

A type already set (by a person, in Zotero or SciLEx) is never overwritten. The
analyses and charts compare papers by this type, and eligibility criteria can spare a
type.

## Citation metrics

Computed once from the citation network (ideally the frozen Zotero snapshot) and kept
with each paper: `metric_citations`, `metric_references`, `metric_citations_year`,
`metric_cited_in_corpus`, `metric_cites_in_corpus`, `metric_pagerank`,
`metric_quality`, `metric_venue_rank`, `metric_computed_at`. The matching tags, in the
`DIMENSION:value` style of the grid, are shared by the Zotero sync: `CITATIONS:10^2`
(100–999), `REFERENCES`, `CITATIONS_PER_YEAR`, `CITED_IN_CORPUS`,
`PAGERANK:top1%/5%/10%/25%/other`, `QUALITY:<tens>`, `VENUE_RANK`. Earlier metric tags
are replaced at each computation; discarded papers are left out.
