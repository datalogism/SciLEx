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

## Filters

Under the search box, the same filters as [Explore](explore.md#filters): document type,
paper type, origin, import date, source API, Zotero collection, search keywords, tags,
LPWC tasks and datasets, ORKG research problems and fields, annotation status,
annotator and validator. Several values of one filter: any of them; several filters:
all of them. **(none)** selects the papers without a value.
