# ⑤ Extend

<img src="../_static/modules/extend.png" alt="Extend module" height="80">

Extend adds papers to a review that already has some (collected, imported from Zotero
or a knowledge graph). One tab per way of extending the corpus; a dot on each tab
shows when it last ran.

| Sub-module | What it does |
|---|---|
| <a href="#new-collect"><img src="../_static/modules/sub/extend-new-collect.png" height="30" alt="New collect"></a> | Run the queries of `scilex.yml` not run yet |
| <a href="#snowballing"><img src="../_static/modules/sub/extend-snowball.png" height="30" alt="Snowballing"></a> | Papers often cited by, or citing, the corpus |
| <a href="#keyword-suggestions"><img src="../_static/modules/sub/extend-keywords.png" height="30" alt="Keyword suggestions"></a> | New search keywords from the paper clusters |
| <a href="#bibtex-import"><img src="../_static/modules/sub/extend-bibtex.png" height="30" alt="BibTeX import"></a> | The entries of a `.bib` file |
| <a href="#zotero"><img src="../_static/modules/sub/extend-zotero.png" height="30" alt="Zotero"></a> | Another Zotero library or collection |

## One Zotero collection per extension

Every extension that adds papers gets its own collection in the review's
[Zotero group](zotero.md#zotero-group), under the review's collection when it uses
one: `Extension <n> · <how> · <date>`. The new papers are pushed into it and get it as
sub-corpus (`zotero_collections`), so each extension stays visible, comparable and
reversible in Zotero.

The card **Zotero collection of the new papers**, above the tabs, applies to every tab:
**Create a new collection** (default, optionally named) or **Add them to an existing
collection**. The choice is saved in `extension_target.yml` so background jobs follow
it, and goes back to a new collection each time the page opens. Without a group, or
when Zotero cannot be reached, the extension is kept: only the collection is missing,
and the message says why.

Before a new collect, the previous results are saved in
`output/<name>/previous_results/`; imports and snowballing back up
`aggregated_results.csv` too. Each added paper records its origin in the
`extension_origin` column and in `paper_log.json`.

## New collect

The Collect step of a review with papers. Add keywords, years or sources in
[① Configure](configure.md): only the queries not run yet are collected. Then:

- **Add new papers**: the papers of the review stay as they are (ranking and screening
  included); only papers it does not have yet (same DOI, or same title and year) are
  appended.
- **Re-aggregate everything**: the whole collection is deduplicated, filtered and
  ranked again; papers that do not come from it (Zotero, BibTeX, snowballed) are kept.
- **Start over**: deletes the raw results and collects every query again.

## Snowballing

Finds papers outside the corpus that are often cited by, or cite, the corpus papers
(needs [⑥ Enrich → Citations](enrich.md#citations)). The new papers are added to
`aggregated_results.csv` (column `snowball_depth`), so Zotero and the exports include
them; the original file is kept once as `aggregated_results_pre_snowball.csv`. Untick
**Add to the collection** to write `aggregated_results_snowball.csv` instead.

```bash
scilex-snowball                 # --separate-file to keep a separate file
scilex-seed --dois 10.1/abc …   # start from seed papers (DOIs, a DOI file or BibTeX)
```

## Keyword suggestions

Suggests new search keywords from frequent terms in the communities found by
[⑦ Analyses → Graph](analyses.md#graph) (run it first). Add the ones you keep in
① Configure, then run a New collect. Same as `scilex-suggest-keywords`.

## BibTeX import

Adds the entries of a `.bib` file (exported from Zotero, Google Scholar, DBLP…) with
`archive` = `BibTeX`. Papers the review already has (same DOI, else same title and
year) and entries without a title are skipped, so a file can be imported again after
adding entries to it. The `keywords` become tags and LaTeX accents are decoded.
Imported papers are kept by a re-aggregation.

## Zotero

Adds the papers of a Zotero library (yours or a group) or of a collection, with or
without its sub-collections (kept as sub-corpora). Zotero is not a keyword search, so
it is a source of Extend rather than of Collect. Papers the review already has are not
added again; they get the Zotero tags and sub-corpora they lack (nothing is removed).
With **Make it the review's Zotero library**, the choice becomes the review's Zotero
source and every paper is matched with its Zotero item; otherwise the papers are added
without a link.

After an extension, run [Consolidate](consolidate.md): the aggregation filters only
saw the papers of the keyword collection.
