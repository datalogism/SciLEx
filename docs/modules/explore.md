# Explore

<img src="../_static/modules/explore.png" alt="Explore module" height="80">

Explore browses the papers of a review once it has some, at any step: the
**Explore** button at the top right of every review screen opens it full screen over
the current step (close it to come back; **Reload** reads the papers again). It reads
the corpus; the only things it writes are a few per-paper actions (validate, discard,
enrich one paper). Screening decisions are taken in [③ Screen](screen.md).

| Sub-module | What it does |
|---|---|
| <a href="#filters"><img src="../_static/modules/sub/explore-filters.png" height="30" alt="Filters"></a> | Narrow the corpus by any property |
| <a href="#break-down-by"><img src="../_static/modules/sub/explore-breakdown.png" height="30" alt="Break down by"></a> | Chart the selection by a property |
| <a href="#paper-notice"><img src="../_static/modules/sub/explore-notice.png" height="30" alt="Paper notice"></a> | Everything SciLEx knows about one paper |
| <a href="#enrich-one-paper"><img src="../_static/modules/sub/explore-enrich-one.png" height="30" alt="Enrich one paper"></a> | Run an enricher on one paper only |

## Filters

Filter by screening decision, a title/abstract search, and property filters: document
type, [paper type](enrich.md#paper-types), origin (Collect, Extend collect, Zotero,
knowledge graph or BibTeX import, Snowball), import date, source API, Zotero
collection, search keywords, tags, LPWC tasks and datasets, ORKG research problems and
fields, annotation status, annotator and validator (folded under **Filters**, above the
article list). Only the properties whose values
differ between papers are offered. Several values of one filter: any of them; several
filters: all of them. **(none)** selects the papers without a value. The count of
matching papers is shown.

The import date comes from `paper_log.json` (review folder), which records when and how
each paper first entered the review. Papers already there before this log existed show
*Before tracking*.

**Save selection** writes the matching papers, with every column, to
`output/<name>/explore_selection.csv`.

**Eligibility** filters on the [eligibility criteria](criteria.md): papers that meet
all the enabled criteria (exceptions count as met), those that fail one, those kept by
an exception, or those a given criterion excludes. The criteria are judged on the
whole corpus, as in [Test](criteria.md#test), whether or not they were applied yet; the
**Criteria** column lists the ones a paper does not meet (`*`: kept by an exception),
with the causes as tooltip.

## Break down by

Folded under the article list, draws the selection per value of any property (type, origin, collection, tags, LPWC
tasks…). Clicking a bar filters on that value.

## Paper notice

Selecting a paper opens its notice: authors, venue, type, DOI and links (web page, PDF,
Papers with Code, code repository, Linked Papers With Code, ORKG), origin and import
date, citation counts, abstract, search keywords, LPWC tasks and datasets, ORKG
research problems and fields, Zotero collections, sources, screening note, and:

- **badges**: paper type (tagged, or the default type), access, code, DOI;
- **Zotero links**: the item in the Zotero app, and on zotero.org for a group;
- **annotations**: the `DIMENSION:value` tags grouped by dimension (pending `?` values
  highlighted), who the paper is assigned to and who validated it;
- **eligibility**: each [criterion](criteria.md)'s verdict on the paper, and
  exceptions (`KEEP:<criterion>`) in one click.

Clicking a value filters on it; the arrows move to the previous or next paper.
**Validated by me** adds `ANNOT_VALID_BY:<your ORCID>`; **Discard** adds
`DELETED_BY:<your ORCID>` (the paper stays in the corpus but leaves the analyses,
counts and charts); both can be undone. The same notice opens when clicking a node of
the [citation graph](analyses.md#graph).

## Enrich one paper

The **Enrich** menu of the notice runs one enricher of [⑥ Enrich](enrich.md) on this
paper only: Crossref, Linked Papers With Code, ORKG, GitHub, Zenodo, paper type, short
title or search keywords.
Each runs exactly as in ⑥ Enrich (cached answers are reused); what it fills is written
into the review's results and shared through the Zotero sync.
