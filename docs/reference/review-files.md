# Files of a review

A review is a folder. Everything SciLEx knows about it is a plain file in that folder,
in its results folder (`output/<name>/`, the *collection folder*) or in your user
configuration folder. Nothing is hidden in a database, so a review can be copied,
versioned or inspected by hand.

## User configuration folder

| File | Content |
|---|---|
| `~/.config/scilex/keys.yml` (or `$SCILEX_KEYS`) | global API keys, readable by you only |
| `user.yml` | your ORCID iD |
| `gui_reviews.yml` | the reviews the desktop app knows |

## Review folder

| File | Content | Module |
|---|---|---|
| `scilex.yml` | search, filters, citations, ranking, sub-corpora, VPN | [① Configure](../modules/configure.md) |
| `review_keys.yml` | API keys overridden for this review (keep it private) | [Workspace](../modules/workspace.md#api-keys) |
| `review_state.yml` | the review's results folder, kept across renames | [Workspace](../modules/workspace.md#reviews) |
| `zotero_source.yml` | the review's Zotero library (group) and collection | [Zotero](../modules/zotero.md#zotero-group) |
| `zotero_sync_state.json` | sync baselines of both sides | [Zotero](../modules/zotero.md#sync) |
| `zotero_citations.json` | frozen citation snapshot from Zotero | [⑥ Enrich](../modules/enrich.md#citations) |
| `extension_target.yml` | Zotero collection of the next extensions | [⑤ Extend](../modules/extend.md) |
| `criteria.yml` | eligibility criteria | [Criteria](../modules/criteria.md) |
| `annotation_grid.csv` | annotation dimensions | [④ Annotate](../modules/annotate.md#annotation-grid) |
| `members.yml` | annotators: names, ORCID iDs | [④ Annotate](../modules/annotate.md#annotators) |
| `workflow.jsonl` | append-only journal of every event | [Overview](../modules/overview.md#history) |
| `annotation_history.jsonl` | annotation snapshots | [Overview](../modules/overview.md#review-card) |
| `paper_log.json` | when and how each paper entered the review | [Explore](../modules/explore.md#filters) |
| `gui_run_history.json` | last completion of each costly action | [Workspace](../modules/workspace.md#running-jobs) |
| `kg_source.yml`, `kg/` | the knowledge graph a review was created from | [Workspace](../modules/workspace.md#reviews) |
| `exports/` | BibTeX, CSV and Turtle exports | [⑧ Export](../modules/export.md) |

## Collection folder (`output/<name>/`)

| File | Content |
|---|---|
| raw API answers (one folder per API and query) | ② Collect |
| `config_used.yml` | the configuration of the collection |
| `aggregated_results.csv` | **the corpus**: one row per paper, every column |
| `filtering_summary.json`, `aggregation_stats.csv` | counts of each filtering phase (PRISMA) |
| `screening.csv` | screening decisions and notes |
| `citations_cache.json`, `citers_cache.json` | references and citing papers |
| `<source>_cache.json` | answers of each enricher |
| `aggregated_results_pre_snowball.csv`, `aggregated_results_snowball.csv` | snowballing backup or separate result |
| `previous_results/` | results saved before a new collect |
| `explore_selection.csv` | Explore → Save selection |
| `prisma_flow.svg`, `prisma_flow.png` | Overview → PRISMA flow export |
| `chart_aggregated_papers/` | Charts |
| `graph_analysis/` | Graph, Summaries and keyword suggestions (`keyword_suggestions.md/.yml`) |
| `coverage_per_paper.csv`, `coverage_rates.csv` | Accessibility analysis |
| `annotations/` | annotation report tables |
| `kg/` | knowledge graph: `<name>.ttl`, `.bib`, SHACL report |
