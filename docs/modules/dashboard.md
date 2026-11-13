# Dashboard

The Dashboard shows the statistics, charts and citation network of one review, all
linked together. Filtering in one view filters every other: drag over a range of
years, click the bars of any chart (several values of one chart mean any of them;
several charts mean all of them), or keep one paper and its neighbours in the network.
The active filters are shown as chips above the tabs; click a chip to remove it.

Click a paper (a network node or a row of the list) to open its full
[notice](explore.md#paper-notice) on the right, with the same actions as in Explore.
Previous / next go through the papers the filters leave.

| Tab | What it shows |
|---|---|
| Statistics | Papers shown, papers meeting the [criteria](criteria.md), included papers, median citations, years and links. Charts: publication year (brush), citation bands, paper type, document type, origin, source API, Zotero collection, keywords, tags, LPWC / ORKG terms, screening decision, eligibility and criteria not met |
| Network | Citation links between corpus papers (from [Enrich › Citations](enrich.md#citations)); colour by any property, size by PageRank, citations or citations from the corpus; papers filtered out are faded or hidden |
| Papers | The papers the filters leave, sorted by relevance, citations, PageRank or year |

The charts are drawn with [D3](https://d3js.org) and filtered with
[crossfilter](https://crossfilter.github.io/crossfilter/), both shipped with SciLEx,
so the Dashboard also works offline.
