# Desktop application

The SciLEx desktop application runs a literature review without the command line.
It works on the same files as the CLI: a review is a folder containing a `scilex.yml`,
and API keys live in `~/.config/scilex/keys.yml`. You can switch between the app and
the `scilex-*` commands at any time.

Screens of a review: ① Configure, ② Collect (**Extend collect** once the review has
papers), ③ Enrich, ④ Screen, ⑤ Analyses, ⑥ Annotate, ⑦ Export, plus API keys. Enrich,
Screen, Analyses and Export unlock once a collection has been aggregated (or imported
from Zotero).

**ORCID iD.** The app asks for your ORCID iD before anything else and stays locked
without one. It is checked locally (format and check digit); **Check on orcid.org**
shows the name registered for it. It is stored in `user.yml` next to the list of
reviews (your user configuration folder), shown on the home page (click it to change
it), and written as the creator of the knowledge graphs you export. `scilex-build-kg`
reads the same file, or takes `--orcid`.

## Install

Download the archive for your system from the
[latest release](https://github.com/Wimmics/SciLEx/releases/latest), then:

- **macOS** (`SciLEx-macos.dmg`): open the image and drag `SciLEx.app` to Applications.
  The app is not signed yet: the first time, right-click the app, choose **Open**, then
  **Open** again in the warning dialog. Later launches work normally.
- **Windows** (`SciLEx-windows.zip`): extract the folder and run `SciLEx.exe`.
  SmartScreen may warn about an unknown publisher: click **More info**, then **Run anyway**.
- **Linux** (`SciLEx-linux.tar.gz`, needs glibc 2.34+, e.g. Ubuntu 22.04 or later): extract
  it and run `SciLEx/SciLEx` (double-click it in the file manager, or run it from a terminal).
  If the window cannot open (no display, missing system library), the app says why in the
  terminal and opens in your web browser instead; every feature works there too.

Maintainers publish a release by pushing a `gui-v*` tag (for example
`git tag gui-v0.1.0 && git push origin gui-v0.1.0`): the "GUI build" workflow builds the
three archives, self-tests them and attaches them to the GitHub Release of that tag.

From a development checkout instead:

```bash
uv sync --extra gui
uv run scilex-gui            # native window
uv run scilex-gui --browser  # same UI in a browser tab (useful for debugging)
```

## First steps

1. **New review**: give a name, optionally a folder, and a starting point. Without a
   folder, the review goes to `~/SciLEx/<name>`; a relative folder such as `Test` also
   starts in `~/SciLEx` (an absolute path is used as is). The app writes `scilex.yml`
   there. Or **Open a folder** that already contains a `scilex.yml`.
   - **From scratch**: a blank `scilex.yml` or a template; collect in ② Collect.
   - **From Zotero** (needs the Zotero key and library id in the global
     **API keys**; the dialog says when they are missing and links to them):
     click **Load**, choose a library (yours, or any group the key can read), then the
     **whole library** or a collection, with or without its **sub-collections**. Choose
     **One review** (the collections a paper belongs to are kept in its
     `zotero_collections` column and become sub-corpora of the knowledge graph) or
     **One review per collection** (one sub-folder each). The papers become the review's
     `aggregated_results.csv`, so Enrich, Screen, Analyses and Annotate work at once.
     The keywords come from the `Collect_KW1:…`/`Collect_KW2:…` tags SciLEx writes when
     pushing, the years from the paper dates, and the annotation grid from the
     `DIMENSION:value` tags annotators added. An optional configuration file
     (`scilex.yml`, or a legacy `scilex.config.yml` with its `scilex.advanced.yml`) wins
     over these deductions; what it lacks is still deduced. The library and collection
     are remembered in `zotero_source.yml`: they are the review's Zotero source (see
     ⑦ Export).
2. **API keys** (once for all reviews), then **① Configure**, **② Collect**,
   optionally **③ Enrich**, then **④ Screen**, optionally **⑤ Analyses** and
   **⑥ Annotate**, and **⑦ Export**.

Only one job (collection, export, analysis) runs at a time in the app.

## Overview

Opening a review shows its **Overview** first: the number of papers, of Zotero
collections (sub-corpora), the share already screened and the annotation state, then
charts of the papers per year, per source and per collection, the screening decisions,
the papers enriched per source, the papers coded per dimension, and the **annotation
history**.

Zotero keeps no history of tags, so the history is made of snapshots SciLEx records
each time it reads the annotations: when a review is imported from Zotero, when the
report is built in ⑥ Annotate, and at each knowledge-graph export. They are kept in
`annotation_history.jsonl` in the review folder (one line per snapshot) and listed under
the chart.

## ① Configure

Edits the review's `scilex.yml` without a text editor. The **Search** section holds the
name, the keyword groups (a paper must contain at least one term of *each* group), the
years, the sources and the maximum number of papers per query. Other sections (filters,
citations, ranking…) fold out, with help on hover and a badge showing where each value
comes from (file or preset). Errors are shown live and block saving. Only values that
differ from the defaults are written, and comments in the file are lost when saving from
the form. **Edit scilex.yml directly** opens the raw file (comments kept); use it to
repair a file the form cannot load.

- **Sources**: ORKG has no year filter on its side, so papers of other years are
  fetched, then dropped by the aggregation (and skipped by abstract enrichment).
- **Citations → Ask OpenCitations last**: the free OpenCitations index is queried for the
  papers no other source counted. It is the most complete source for DOIs but the
  slowest (3 requests/s); turn it off for faster aggregations (`citations.opencitations`).
- **Collection → VPN rotation (NordVPN)**: when a source keeps answering 429/409 after
  every retry (or a `Retry-After` longer than 10 minutes), SciLEx switches the NordVPN
  server, checks that the public IP changed and retries the same page. Choose the
  sources concerned (none = all), how the next server is picked (random country,
  quick connect, or a list of countries), the wait after connecting and a cap per run.
  **Check VPN** shows whether the NordVPN client is found and the current IP;
  **Test a rotation** switches server once (connections drop for a few seconds). Stored
  as the `collect.vpn` block of `scilex.yml`, as for the CLI.

## API keys

**Global keys** (**API keys** button of the home page) are the default of every review,
stored in one file whose path is shown (`$SCILEX_KEYS`, else
`~/.config/scilex/keys.yml`, readable by you only). If an older `scilex/api.config.yml`
holds keys this file lacks (Zotero, Springer…), the home page and this screen offer to
**Import** them; values already set are kept.

**A review's keys** (its **API keys** step) show the same form, with the global value
under each field. Leave a field empty to use the global value; fill it to use another
key, e-mail or Zotero library for this review only. Only the overridden fields are
written, to `review_keys.yml` in the review folder (keep it out of shared folders and
version control); emptying them all removes the file.

Type each key
(the eye icon shows it), add several for rotation if needed, click **Test** to check it,
then **Save**. Zotero, the Unpaywall and CrossRef e-mails and the rate limits
(**Advanced**) are set here too. An environment variable `SCILEX_<API>_<FIELD>` takes
precedence over the file; a warning says so.

## ② Collect

Check the summary line (APIs, years, keyword groups), then click **Run**. A table shows
each API's progress, papers, errors and state; the aggregation steps follow. **Only
papers since** (YYYY-MM-DD) collects recent papers only. If a collection was
interrupted, **Resume interrupted collection** continues where it stopped. At the end, a
summary (collected, after deduplication, kept) and the PRISMA and aggregation reports are
available. **Cancel** stops the collection at the next query; the aggregation cannot be
interrupted. Results go to `<folder>/output/<name>/aggregated_results.csv`, exactly as
with `scilex-collect` then `scilex-aggregate`.

### Extend collect

Once the review has papers (collected, imported from Zotero or snowballed), the step
becomes **Extend collect**. Add keywords, years or sources in ① Configure: only the
queries not run yet are collected. Then:

- **Add new papers**: the papers of the review stay as they are (ranking and screening
  included); only papers it does not have yet (same DOI, or same title and year) are
  appended, with their origin in the `extension_origin` column.
- **Re-aggregate everything**: the whole collection is deduplicated, filtered and ranked
  again; papers that do not come from it (imported from Zotero, snowballed) are kept.
- **Start over**: deletes the raw results and collects every query again.

The previous results are saved in `output/<name>/previous_results/` first. Below, the
**Extend the corpus** tabs hold **Snowball** (papers often cited by, or citing, the
corpus; needs the citations of ③ Enrich) and **Keywords** (new search keywords from the
communities of ⑤ Analyses → Graph).

## ③ Enrich

Adds data from external sources. Run it before screening on every paper, or after it
with **Only the papers kept in ④ Screen** (included or maybe). One tab per source:

- **Citations**: references and citing papers (needed by Snowball and the Graph). Source:
  Semantic Scholar then Crossref then OpenCitations (default), Crossref + OpenCitations,
  or OpenCitations only (open data, no key).
- **Papers with Code**: tasks, methods, benchmarks and GitHub repositories.
- **Crossref** (by DOI): fills empty abstracts, venues, volumes, pages, dates,
  publishers, licences and ISSNs, and adds `crossref_type`, `crossref_cited_by` and
  `crossref_funders`. Existing values are never overwritten; set the CrossRef e-mail in
  API keys for the faster "polite" service.
- **Linked Papers With Code** (by arXiv id, else exact title): `lpwc_tasks`,
  `lpwc_methods`, `lpwc_datasets`, `lpwc_repositories`, `lpwc_conference`, `lpwc_paper`.
- **ORKG** (by DOI, else exact title): `orkg_paper`, `orkg_research_fields`,
  `orkg_research_problems` (of the paper's contributions).

Answers are cached in the collection folder (`<source>_cache.json`), so a rerun only asks
for papers not looked up yet.

## ④ Screen

Lists the aggregated papers by relevance score. Select a paper to read its abstract and
open its DOI, then click **Include**, **Exclude** or **Maybe**, or press **I**, **E**,
**M**; the arrows (or **J**/**K**) move between papers. A note can go with each decision.
Decisions are saved at once to `output/<name>/screening.csv` and survive a new
aggregation; decisions on papers that disappeared are listed as *orphans* and can be
forgotten. A note typed without a decision is not kept.

## ⑤ Analyses

Tabs: charts, citation graph and community summaries. Each tab describes the analysis,
offers its main options and a **Run** button; progress and logs are shown live. Results
(images, Markdown reports, tables) are read from the collection folder and shown again
when the tab opens. The graph needs the citation data of ③ Enrich → Citations; summaries
(and the keyword suggestions of Extend collect) need the graph to have run first.
**Cancel** stops an analysis at the end of its current step. **Run** buttons are disabled
while another job is running.

Snowball (in ② Extend collect) adds the new papers to `aggregated_results.csv` itself
(column `snowball_depth`), so Zotero and the exports include them; the original file is
kept once as `aggregated_results_pre_snowball.csv`. Untick **Add to the collection** to
write `aggregated_results_snowball.csv` instead (`scilex-snowball --separate-file` on the
command line). **Re-aggregate everything** keeps the snowballed papers.

## ⑥ Annotate

Prepares and follows the manual annotation of the papers in Zotero.

- **Annotation grid**: one row per dimension (`SAT_TASK`, `SAT_DATASET`…), the question
  annotators answer, and the paper types it applies to (datasets, surveys, models).
  Start from the SciLEx grid, import a CSV (a `tag` column, and `X` in the type
  columns), or **Deduce from Zotero annotations** (the `DIMENSION:value` tags of the
  chosen collection). Saved as `annotation_grid.csv` in the review folder.
- **Add the grid to the Zotero papers**: choose the collection and the dimensions (all,
  or those of one paper type), click **Preview changes**, then **Apply in Zotero**. Each
  paper gets `DIMENSION:?` for every dimension it has no value for, and existing values
  are normalized (`DIMENSION:DeepLearning`). Other tags are kept unless you untick the
  option. A paper edited in Zotero between preview and apply is skipped: preview again.
- **Annotation report**: counts the annotation tags by dimension, the most used tags,
  and who last edited each paper; the tables are also written to
  `output/<name>/annotations/`. Same as `python -m scilex.report_annotations`.

Annotate reads the review's own Zotero library (see ⑦ Export).

## ⑦ Export

**Zotero library of this review**: each review has its own Zotero source. Click
**Change** to choose a library (yours or a group), then a collection (with or without its
sub-collections) or the whole library. It is saved in `zotero_source.yml` and used by the
Zotero push, ⑥ Annotate and the knowledge graph. Without one, the library of the API keys
and a collection named after the review are used.

Choose the papers: only those marked *included* while screening, or all of them. Formats:

- **BibTeX**, **CSV** (`;`-separated, with the screening decision and note), **RDF/Turtle**
  (SciLEx's own BIBO vocabulary).
- **Zotero**: pushes the papers to the review's collection (or a collection named after
  the review in the chosen library); duplicates skipped. Disabled until the Zotero key and
  library id are set in **API keys**.
- **Knowledge graph (scilex-lpwc-ap)**: exports every paper of the review's Zotero source
  as BibLaTeX (tags with the annotations, Extra with the citation lists) and maps it with
  the [scilex-lpwc-ap](https://codeberg.org/cringwald/scilex-lpwc-ap) application profile
  (OpenCitations/SPAR + Linked Papers With Code). The coding dimensions come from the
  review's `annotation_grid.csv`, sub-collections become sub-corpora (`dcat:Dataset`), and
  your ORCID iD is the creator. The graph is checked against the profile's SHACL shapes.
  Written to `output/<name>/kg/` (`<name>.ttl`, the `.bib` it came from,
  `<name>.shacl.ttl/.txt`). Same as `scilex-build-kg`.

File exports go to the review's `exports/` folder, with the scope and a timestamp in
their name; the path is shown at the end with a button to reveal it, and previous exports
are listed.

### The application profile

SciLEx ships a pinned copy of the profile in `scilex/kg/ap/` (`VERSION.json` says which
commit). Maintainers refresh it with `python -m scilex.kg.sync_profile` (latest release,
else newest tag, else the default branch; `--check` only compares; `--local DIR` installs
from a local checkout, unpushed iterations included), review the diff, and run
`pytest tests/test_kg.py`.

From iteration 3 on, the profile's mapping is a set of templates (`{{BASE}}`, `{{JSON}}`,
`{{TITLE}}`…) driven by a *collection profile*. SciLEx fills the templates and generates
the collection profile of each review: its annotation-grid dimensions (deduced from the
`DIMENSION:value` tags when there is no grid) plus SciLEx's own tags (`Collect_KW*`,
`QUALI_SCORE`, `REL_SCORE`, `CITAT`, `HavePDF`…). The base IRI is
`https://w3id.org/scilex/data/<review-slug>/`. For iteration 1 profiles, SciLEx rewrites
the sample review's values instead. Either way it stops with an error if a profile
version no longer has the shape it expects.

## Troubleshooting

- Check an installation without opening a window: run the executable with `--self-test`
  (for example `SciLEx.app/Contents/MacOS/SciLEx --self-test` on macOS).
- Logs are written to `scilex-gui.log` in your user log folder
  (`~/Library/Logs/scilex` on macOS, `%LOCALAPPDATA%\scilex\Logs` on Windows,
  `~/.local/state/scilex/log` on Linux).
- Unexpected errors show a dialog with **Copy diagnostics**: paste it into a GitHub issue.
