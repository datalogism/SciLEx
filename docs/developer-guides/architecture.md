# Architecture

SciLEx has three layers: a **core library** (collection, aggregation, enrichment,
analyses, exports) driven by `scilex.yml`; the **command line** (`scilex-*` entry
points, thin wrappers around the core); and the **desktop app** (`scilex.gui`, NiceGUI
in a native window), whose services call the same core. The user-facing view of each
part is in [Modules](../modules/index.md).

```
                         scilex.yml  +  keys.yml
                                 │  scilex/settings (schema, presets, loader)
              ┌──────────────────┼──────────────────────────┐
              ▼                  ▼                          ▼
        command line       core library               desktop app
        scilex-*      ──►  crawlers/ pipeline/   ◄──  gui/pages    (display only)
                           citations/ snowball/       gui/services (logic, no UI)
                           graph_analysis/ kg/        gui/components
                           Zotero/ rdf/ …
                                 │
                                 ▼
             review folder + output/<name>/   (plain files, see "Files of a review")
                                 │
                                 ▼
                Zotero group  ·  BibTeX / CSV / Turtle  ·  knowledge graph
```

## Core library

| Package / module | Module (docs) | Role |
|---|---|---|
| `settings/` | ① Configure | `scilex.yml` / `keys.yml`: pydantic schema (unknown keys rejected), presets, loader, legacy migration, `scilex config` |
| `crawlers/collectors/` | ② Collect | one collector per API, inheriting `API_collector` (`base.py`) |
| `crawlers/collector_collection.py` | ② Collect | jobs keywords × years × APIs, parallel runs, idempotent resume |
| `crawlers/adaptive_rate_limiter.py`, `circuit_breaker.py`, `key_pool.py`, `vpn/` | ② Collect | rate limits, failing APIs, key rotation, NordVPN rotation |
| `crawlers/aggregate.py`, `aggregate_parallel.py` | ② Collect | API formats → one Zotero-shaped format; parallel aggregation |
| `pipeline/` | ② Collect | filters, ranking, DOI recovery, open access, venue ranks, reports |
| `citations/` | ⑥ Enrich | citation counts and references (SQLite cache, fetchers) |
| `PapersWithCode/`, `enrich_with_pwc.py` | ⑥ Enrich | Papers with Code client and title matching |
| `linked_enrichment.py` | ⑥ Enrich | Crossref, Linked Papers With Code, ORKG |
| `keyword_annotation.py`, `paper_types.py`, `citation_metrics.py` | ⑥ Enrich | search-keyword tags, paper types, metrics |
| `snowball/`, `snowball_sampling.py`, `seed_papers.py` | ⑤ Extend | snowball sampling, seed papers |
| `keyword_suggestions/`, `suggest_keywords.py` | ⑤ Extend | keyword suggestions |
| `graph_analysis/`, `summarize/`, `report_charts.py` | ⑦ Analyses | citation graphs, communities, summaries, charts |
| `tag_analysis.py`, `tagging/`, `report_annotations.py`, `annotation_agreement.py` | ④ Annotate, ⑦ Analyses | annotation tags, grid, report, Krippendorff's alpha |
| `review_tags.py` | ④ Annotate | workflow tags (`ANNOT:`, `ANNOT_VALID_BY:`, `DELETED_BY:`, `KEEP:`…) |
| `Zotero/`, `push_to_zotero.py` | Zotero, ⑧ Export | Zotero API client, push |
| `export_to_bibtex.py`, `export_to_turtle.py`, `rdf/` | ⑧ Export | BibTeX and BIBO Turtle |
| `kg/`, `build_kg.py` | ⑧ Export | knowledge graph with the pinned scilex-lpwc-ap profile (`kg/ap/`) |
| `user_profile.py` | Workspace | the user's ORCID iD (`user.yml`) |

### Collection and aggregation

```
scilex.yml → jobs (keyword combination × year × API) → parallel collectors → JSON pages
JSON pages → format converters → deduplication (DOI, normalised title)
           → abstracts, citations, optional venue rank / open access / LLM score
           → item type → quality → abstract quality → citations → relevance ranking
           → output/<name>/aggregated_results.csv
```

Converters use the `MISSING_VALUE` sentinel for missing fields, never `None` or `""`.
Each filtering phase writes its counts to `filtering_summary.json`, which feeds the
PRISMA flow.

### Configuration

Priority of `scilex.yml` values: code defaults < preset < `scilex.yml` < command-line
options. `settings/loader.py` discovers and merges the files and `to_legacy()` converts
them to the internal `(main_config, api_config)` dictionaries used by `SciLExConfig` and
the pipeline. `settings/resolve.py` (`resolve_legacy_configs`) also falls back to the
legacy three-file configuration; `settings/migrate.py` converts it.

To add an option: add it to `settings/schema.py`, map it in `to_legacy()`, handle it in
`settings/migrate.py`, describe it in `gui/services/field_catalog.py` (Configure form),
and document it in `scilex.yml.example` and `docs/reference/configuration.md`.

## Desktop app (`scilex/gui`)

| Folder | Rule |
|---|---|
| `pages/` | one module per screen, **display only**; `render(ctx, review)` |
| `services/` | all the logic, **no UI code**, tested without a window |
| `components/` | reusable widgets (job panel, Zotero picker, paper details, sync badge…) |
| `app.py`, `native_window.py`, `self_test.py` | entry point, pywebview window, `--self-test` |
| `state.py` | `AppContext`: workspace, job runner, user profile |

The sidebar is declared in `components/stepper.py` (`PIPELINE_STEPS`): key, label,
Material icon, whether it needs results, and whether it hides once the review has papers.
Enrichers and analyses are declared once in `services/analyses.py` (`ANALYSES`, with
their group `enrich`, `analyse` or `extend`) and drawn as tabs by `pages/analyses.py`.

### Jobs and concurrency

`services/jobs.py` runs every costly action as a `Job` in a thread. Each job declares
the **resources** it uses (a review's results in read, row-write or rewrite mode, a
Zotero library, the collection slot); `conflicts()` decides which jobs wait for which.
`services/results_store.py` merges concurrent row writes to `aggregated_results.csv`, so
enrichers running together never erase each other's cells.

### Traceability

- `services/journal.py`: append-only `workflow.jsonl` per review (agent = ORCID iD),
  mappable to PROV-O ([provenance proposal](../kg/provenance-proposal.md));
- `services/paper_log.py`: when and how each paper entered the review;
- `services/run_history.py`: last completion of each action;
- `services/prisma.py`, `provenance.py`, `consistency.py`: the Overview, from those files.

### Zotero

`services/zotero_library.py` (libraries, groups, collections, review source),
`zotero_sync.py` (two-way sync with per-side baselines), `zotero_extend.py`,
`extension_collection.py` (one collection per extension), `agreement.py`,
`members.py`, `zotero_citations.py` (frozen citation snapshot).

Secrets: every text that can reach a knowledge graph or a Zotero note goes through
`crawlers.utils.sanitize_secrets`; no API key is ever written to a graph, an import or
the journal.

## Documentation

Sphinx with MyST Markdown (`docs/conf.py`). Module icons are generated from the app
icon by `docs/_tools/make_module_icons.py`; run it after adding a module and add the
module to its `MODULES` table, `docs/modules/` and the toctree of `docs/index.md`.

```bash
pip install -r docs/requirements.txt
sphinx-build docs docs/_build
```

## Testing

```bash
uv sync --extra dev --extra gui
uv run python -m pytest tests/                 # all tests
uv run python -m pytest tests/ -m "not live"   # offline only
uv run python -m pytest tests/gui/             # desktop app services and pages
```

`tests/conftest.py` isolates the developer's home (keys, reviews, user profile), so the
suite never reads your real configuration.

## Adding components

- **API collector**: see [Adding Collectors](adding-collectors.md).
- **Enricher or analysis**: write the core function, register an entry in
  `ANALYSES` (`services/analyses.py`) with its group, options and runner, declare its
  job resources, then document it in `docs/modules/`.
- **Pipeline step of the review**: a page in `pages/`, its logic in `services/`, a `Step`
  in `components/stepper.py`, then a module page and icon.
