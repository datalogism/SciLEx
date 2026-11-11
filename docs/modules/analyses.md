# ⑦ Analyses

<img src="../_static/modules/analyses.png" alt="Analyses module" height="80">

One tab per analysis. Each tab describes the analysis, offers its main options and a
**Run** button; progress and logs are shown live. Results (images, Markdown reports,
tables) are read from the collection folder and shown again when the tab opens.
**Cancel** stops an analysis at the end of its current step. Discarded papers
(`DELETED_BY:` tags) are left out of every analysis.

| Sub-module | What it does | Command line |
|---|---|---|
| <a href="#charts"><img src="../_static/modules/sub/analyses-charts.png" height="30" alt="Charts"></a> | Sources, publication types, years, keywords | `scilex-report` |
| <a href="#graph"><img src="../_static/modules/sub/analyses-graph.png" height="30" alt="Graph"></a> | Citation graphs and communities | `scilex-analyze` |
| <a href="#accessibility"><img src="../_static/modules/sub/analyses-accessibility.png" height="30" alt="Accessibility"></a> | Access, DOI, code and citation coverage | — |
| <a href="#annotations"><img src="../_static/modules/sub/analyses-annotations.png" height="30" alt="Annotations"></a> | The `DIMENSION:value` codes: coverage, merges, crossings | — |
| <a href="#summaries"><img src="../_static/modules/sub/analyses-summaries.png" height="30" alt="Summaries"></a> | Statistical report of each community | `scilex-summarize` |

## Compare by

Every tab can compare the papers by **paper type** (Benchmark, Review, Dataset, Model —
the `PAPER_TYPE` tag, else the [default type](enrich.md#paper-types)) or by **Zotero
collection** (sub-corpus; a paper in several collections counts in each), up to 12
groups per chart. The Graph colours its nodes the same way (**Colour by**).

## Charts

Charts of the corpus: papers per source, publication type, year and keyword, with the
chosen comparison. Written to the collection's `chart_aggregated_papers/` folder.

## Graph

Builds citation graphs (needs [⑥ Enrich → Citations](enrich.md#citations)) and
detects communities of related papers (written to `graph_analysis/`). The result is an interactive network: nodes
coloured by community, paper type or collection; clicking a node opens the full
[paper notice](explore.md#paper-notice) (Zotero links, annotations, badges). The
communities feed [Summaries](#summaries) and
[Keyword suggestions](extend.md#keyword-suggestions).

## Accessibility

Studies the accessibility of each paper (open with a PDF, open, restricted, unknown)
and the rates of papers having a DOI, a code repository (GitHub…), citation data, and
being cited in the citation network (by any paper, by a paper of the corpus), for the
whole corpus or compared per collection or paper type. No network needed. Tables:
`coverage_per_paper.csv`, `coverage_rates.csv`.

## Annotations

Analyses the `DIMENSION:value` annotation tags: coverage of each dimension, frequent
values per year, close spellings to merge, and dimensions crossed two by two (empty
cells are gaps of the corpus). Accept merges, cross the dimensions you choose and
clean the spellings in Zotero (a Zotero write job). Workflow, screening and metric tags
written by SciLEx are never counted as codes.

## Summaries

Writes a Markdown report of the communities found by the Graph (run it first): for
each one its size, year range, frequent keywords and main authors, with a Mermaid
mind map of the clusters.

Snowballing and keyword suggestions, which change the corpus or the search, live in
[⑤ Extend](extend.md).
