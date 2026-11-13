# ③ Screen

<img src="../_static/modules/screen.png" alt="Screen module" height="80">

Screen lists the papers by relevance score and records one decision per paper:
**Include**, **Exclude** or **Maybe**, with an optional note.

| Sub-module | What it does |
|---|---|
| <a href="#decisions"><img src="../_static/modules/sub/screen-decisions.png" height="30" alt="Decisions"></a> | Read, decide, note, with keyboard shortcuts |
| <a href="#filters"><img src="../_static/modules/sub/screen-filters.png" height="30" alt="Filters"></a> | Narrow the list before screening |

## Decisions

Select a paper to read its abstract, open its DOI and see the verdict of each
[eligibility criterion](criteria.md), then click **Include**, **Exclude** or **Maybe**,
or press **I**, **E**, **M**; the arrows (or **J**/**K**) move between papers. A note can
go with each decision (a note typed without a decision is not kept).

Decisions are saved at once to `output/<name>/screening.csv` and survive a new
aggregation; decisions on papers that disappeared are listed as *orphans* and can be
forgotten. The [Zotero sync](zotero.md#sync) shares them as `SCREEN:Include`,
`SCREEN:Exclude` and `SCREEN:Maybe` tags.

[⑥ Enrich](enrich.md) and [⑧ Export](export.md) can be limited to the papers kept
here (included or maybe).

### Paper type

The detail panel shows the paper type: **Benchmark**, **Review or State of the art**,
**Dataset** or **Model or Method**. A paper can have several types (a method paper that
also releases a dataset): click a type, or press **1** to **4**, to switch it on or off.
Each type is a `PAPER_TYPE:<type>` tag, shared through Zotero. Until a person or
⑥ Enrich > Paper types sets one, the default type, guessed from the title and abstract,
is shown outlined, and the first click replaces it. The grid has a **Paper type** column
and the filters a **Paper type** filter. In charts and comparisons, a paper with several
types counts for each; the network colours a node by its first type.

### Several papers at once

Tick papers with the grid's checkboxes (the header box ticks every paper of the
filtered list), then **Validate**, **Unvalidate**, **Delete** or **Restore** them at once.
These actions add or remove the `ANNOT_VALID_BY:<your ORCID>` and `DELETED_BY:<your ORCID>`
tags, like the buttons of an [Explore](explore.md) notice: a deleted paper stays in the
corpus but leaves the analyses. The **Status** column shows the result. Clicking a row,
not its checkbox, opens the paper in the detail panel.

## Filters

Under the search box, the same filters as [Explore](explore.md#filters): document type,
paper type, origin, import date, source API, Zotero collection, search keywords, tags,
LPWC tasks and datasets, ORKG research problems and fields, annotation status,
annotator and validator. Several values of one filter: any of them; several filters:
all of them. **(none)** selects the papers without a value.

When the review has [eligibility criteria](criteria.md), the toolbar also has Explore's
**Eligibility** filter: papers meeting all criteria, failing one, kept by an exception, or
excluded by a given criterion. The **Criteria** column lists the criteria a paper does
not meet (`*`: kept by an exception; hover for the cause).
