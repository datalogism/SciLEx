# Consolidate

<img src="../_static/modules/consolidate.png" alt="Consolidate module" height="80">

The aggregation deduplicates and filters the papers of the keyword collection only.
Papers added afterwards (new queries, Zotero, BibTeX, knowledge graph, snowballing) are
merged by exact DOI, or exact title and year, and the filters of `scilex.yml` never saw
them. **Consolidate** works on the whole corpus. **Preview** writes nothing; **Apply**
backs up the results first and runs as a job.

| Sub-module | What it does |
|---|---|
| <a href="#duplicates"><img src="../_static/modules/sub/consolidate-duplicates.png" height="30" alt="Duplicates"></a> | Cross-source duplicates, merged on your choice |
| <a href="#filters"><img src="../_static/modules/sub/consolidate-filters.png" height="30" alt="Filters"></a> | The filters of `scilex.yml` on the merged corpus |
| <a href="#sub-corpora"><img src="../_static/modules/sub/consolidate-subcorpora.png" height="30" alt="Sub-corpora"></a> | Every paper in a required sub-corpus |

## Duplicates

Same DOI, same title, or titles at least *Title similarity* % alike published at most a
year apart. With **Keep copies in different sub-corpora apart** (default), a paper
annotated once per Zotero collection on purpose (e.g. as a model and as a dataset) is
not grouped. Each group lists its copies, their sub-corpus and number of codes; tick
the groups to merge. Groups whose copies carry different `DIMENSION:value` codes are
not pre-ticked: one paper may describe several datasets.

The most complete copy is kept; it gains the sources, keywords, sub-corpora and empty
fields of the others, and the codes of dimensions it has not coded (its own codes win).
A screening decision moves to the kept copy; a disagreement goes in its note.

## Filters

Year range, item-type whitelist, required abstract / DOI / year, minimum number of
authors, abstract length (the item types of `always_keep` are spared the quality rules,
as in the aggregation). Only papers found by queries are filtered unless **Filter
imported papers too** is ticked; papers included in ③ Screen are never filtered.
Rejected papers are **discarded** (`DELETED_BY:filter:<reason>`, reversible),
**excluded in ③ Screen** with the reason in the note, or **removed** from the results.

For a formal, documented set of rules, prefer the
[eligibility criteria](criteria.md).

## Sub-corpora

With `subcorpora: required: [datasets, surveys, models]` in `scilex.yml` (or
*Sub-corpora* in ① Configure), every paper must be in a Zotero collection of one of
these names, or under one (`models / Website` counts as models). The papers in none
are listed with a suggestion (a collection whose name starts with it, e.g. the
`datasets 10/11/2026 15:35:35` collection a Zotero file import creates); **Classify**
adds them to the chosen collection, in Zotero for linked papers.

Linking a review with Zotero gives each row its own Zotero item, preferring items in
the required sub-corpora (so a paper kept as a model and as a dataset links to both
items, and copies made by a Zotero import are not used), and takes each paper's
sub-corpora from its item's collections.
