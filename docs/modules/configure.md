# ① Configure

<img src="../_static/modules/configure.png" alt="Configure module" height="80">

Configure edits the review's `scilex.yml` without a text editor. The same file drives
the command line (`scilex-collect`, `scilex-aggregate`…), so both always agree.

| Sub-module | What it does |
|---|---|
| <a href="#search"><img src="../_static/modules/sub/configure-search.png" height="30" alt="Search"></a> | Name, keyword groups, years, sources |
| <a href="#filters"><img src="../_static/modules/sub/configure-filters.png" height="30" alt="Filters"></a> | Quality filters, ranking, sub-corpora |
| <a href="#citations"><img src="../_static/modules/sub/configure-citations.png" height="30" alt="Citations"></a> | Citation lookups during aggregation |
| <a href="#vpn-rotation"><img src="../_static/modules/sub/configure-vpn.png" height="30" alt="VPN rotation"></a> | Switch NordVPN server when a source blocks |

The form shows errors live and blocks saving while there are some. Each field has help
on hover and a badge showing where its value comes from (file, preset or default). Only
values that differ from the defaults are written; comments in the file are lost when
saving from the form. **Edit scilex.yml directly** opens the raw file (comments kept);
use it to repair a file the form cannot load.

From the command line, `scilex config check` validates the files, `scilex config show`
prints the effective values and their origin. Typos are reported with a suggestion
(`filters.max_paper: unknown key. Did you mean ranking.max_papers?`). See the
[configuration reference](../reference/configuration.md).

## Search

The name of the review, the **keyword groups** (a paper must contain at least one term
of *each* group), the years, the sources (APIs) and the maximum number of papers per
query. ORKG has no year filter on its side: papers of other years are fetched, then
dropped by the aggregation.

## Filters

Folded sections hold the quality filters of the aggregation (item types, required
abstract / DOI / year, minimum number of authors, abstract length, open access), the
citation thresholds, the ranking (bonus keywords, maximum number of papers), the
optional LLM screening and enrichment steps, and the **sub-corpora**
(`subcorpora: required: [datasets, surveys, models]`): Zotero collections every paper
must belong to, checked by [Consolidate](consolidate.md#sub-corpora). See the
[filtering pipeline](../user-guides/advanced-filtering.md).

## Citations

**Ask OpenCitations last**: the free OpenCitations index is queried for the papers no
other source counted. It is the most complete source for DOIs but the slowest
(3 requests/s); turn it off for faster aggregations (`citations.opencitations`).

## VPN rotation

**Collection → VPN rotation (NordVPN)**: when a source keeps answering 429/409 after
every retry (or a `Retry-After` longer than 10 minutes), SciLEx switches the NordVPN
server, checks that the public IP changed and retries the same page. Choose the
sources concerned (none = all), how the next server is picked (random country, quick
connect, or a list of countries), the wait after connecting and a cap per run.
**Check VPN** shows whether the NordVPN client is found and the current IP; **Test a
rotation** switches server once (connections drop for a few seconds). Stored as the
`collect.vpn` block of `scilex.yml`, used by the CLI too.
