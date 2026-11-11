# Modules at a glance

SciLEx is organised in **modules**, one per step of a systematic literature review.
Each module is a screen of the desktop app (the numbers ① to ⑧ are the numbered
steps of its sidebar) and, for most of them, a `scilex-*` command. Every module is
presented with the SciLEx flint, the stone and its "S" from the application icon;
its sub-modules carry a lighter flint.

<img src="../_static/modules/map.png" alt="Map of the SciLEx modules" width="100%">

## The review workflow

```
                      ┌────────────── Workspace ──────────────┐
                      │ reviews · ORCID · API keys · jobs     │
                      └───────────────────┬───────────────────┘
                                          │ open a review
                                          ▼
   Overview ◄─────────── Explore (read-only, at any step) ──────────► paper notice
      │
      ▼
 ① Configure ──► ② Collect ──► Eligibility criteria ──► ③ Screen ──► ④ Annotate
                     ▲                                                   │
                     │  (once the review has papers)                     │
                     └──── ⑤ Extend ──► Consolidate ──► ⑥ Enrich ──► ⑦ Analyses ──► ⑧ Export
                                                                                     │
                       Zotero group · sync · tags  ◄─────────────────────────────────┘
```

A review can also start from an existing Zotero library, a SciLEx knowledge graph
or (as an extension) a BibTeX file: then ② Collect is skipped and the review opens
with papers. ⑥ Enrich can run before ③ Screen (on every paper) or after it (on the
papers kept).

## Modules

| Module | Purpose | Command line |
|---|---|---|
| <a href="workspace.html"><img src="../_static/modules/workspace.png" height="40" alt="Workspace"></a> | Reviews, ORCID iD, API keys, running jobs | `scilex init`, `scilex config` |
| <a href="overview.html"><img src="../_static/modules/overview.png" height="40" alt="Overview"></a> | State of a review: PRISMA flow, provenance, history | — |
| <a href="explore.html"><img src="../_static/modules/explore.png" height="40" alt="Explore"></a> | Browse, filter and read every paper | — |
| <a href="configure.html"><img src="../_static/modules/configure.png" height="40" alt="Configure"></a> | Edit `scilex.yml`: search, filters, citations, VPN | `scilex config check/show` |
| <a href="collect.html"><img src="../_static/modules/collect.png" height="40" alt="Collect"></a> | Query 14 APIs, deduplicate, filter, rank | `scilex-collect`, `scilex-aggregate` |
| <a href="criteria.html"><img src="../_static/modules/criteria.png" height="40" alt="Criteria"></a> | Eligibility criteria as testable rules | — |
| <a href="screen.html"><img src="../_static/modules/screen.png" height="40" alt="Screen"></a> | Include / exclude / maybe decisions | — |
| <a href="annotate.html"><img src="../_static/modules/annotate.png" height="40" alt="Annotate"></a> | Annotation grid, annotators, agreement | `python -m scilex.report_annotations` |
| <a href="extend.html"><img src="../_static/modules/extend.png" height="40" alt="Extend"></a> | Add papers: new collect, snowballing, BibTeX, Zotero | `scilex-snowball`, `scilex-seed`, `scilex-suggest-keywords` |
| <a href="consolidate.html"><img src="../_static/modules/consolidate.png" height="40" alt="Consolidate"></a> | Deduplicate and filter the extended corpus | — |
| <a href="enrich.html"><img src="../_static/modules/enrich.png" height="40" alt="Enrich"></a> | Citations, PwC, Crossref, LPWC, ORKG, types, metrics | `scilex-enrich`, `scilex-enrich-citations` |
| <a href="analyses.html"><img src="../_static/modules/analyses.png" height="40" alt="Analyses"></a> | Charts, citation graph, accessibility, annotations | `scilex-report`, `scilex-analyze`, `scilex-summarize` |
| <a href="export.html"><img src="../_static/modules/export.png" height="40" alt="Export"></a> | BibTeX, CSV, Turtle, Zotero, knowledge graph | `scilex-export-bibtex`, `scilex-push-zotero`, `scilex-export-turtle`, `scilex-build-kg` |
| <a href="zotero.html"><img src="../_static/modules/zotero.png" height="40" alt="Zotero"></a> | Group per review, members, two-way sync, tags | `scilex-push-zotero` |

The icons are drawn from the application icon by `docs/_tools/make_module_icons.py`;
run it again after adding or renaming a module.
