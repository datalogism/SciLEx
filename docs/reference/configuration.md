# Configuration Reference

SciLEx is configured with two YAML files:

| File | Scope | Content |
|------|-------|---------|
| `scilex.yml` | One per review, in the working folder | Search terms, years, APIs, filters, ranking, enrichment, reports |
| `keys.yml` | Shared by all reviews, outside any project | API keys, Zotero and OpenRouter credentials, rate limits |

You only write what differs from the defaults. Unknown keys and invalid values stop the program with a
readable message (`filters.max_paper: unknown key. Did you mean ranking.max_papers?`).
Complete, commented templates are shipped at the repository root: `scilex.yml.example` and `keys.yml.example`.

## File discovery

`scilex.yml`:

1. `--config PATH`
2. `$SCILEX_CONFIG`
3. `./scilex.yml` (current working directory)
4. Legacy format (deprecated, see the section "Legacy format and migration" below)

`keys.yml`:

1. `--keys PATH`
2. `$SCILEX_KEYS`
3. `~/.config/scilex/keys.yml`
4. Legacy `scilex/api.config.yml` (deprecated, a warning is logged)

An explicit path (option or variable) that does not exist is an error. `--config` and `--keys` are accepted by
the pipeline commands (`scilex-collect`, `scilex-aggregate`, `scilex-enrich`, `scilex-push-zotero`,
`scilex-export-bibtex`, ...) and by `scilex config show|check`. For `scilex-init`, `--config` is the file to write.

## Environment variables

| Variable | Effect |
|----------|--------|
| `SCILEX_CONFIG` | Path to `scilex.yml` (set by `--config`) |
| `SCILEX_KEYS` | Path to `keys.yml` (set by `--keys`) |
| `SCILEX_<API>_<FIELD>` | Overrides one field of `keys.yml`, for example `SCILEX_SEMANTICSCHOLAR_API_KEY`, `SCILEX_OPENALEX_API_KEY` or `SCILEX_ZOTERO_USER_ID`. `<API>` is matched case-insensitively with the API names of `keys.yml`; the rest is the lower-cased field name. Environment values take precedence over the file and are plain strings (not key lists). |
| `OPENROUTER_API_KEY` | OpenRouter key for `llm_screening` (alternative to `openrouter.api_key`) |
| `SCILEX_PROFILES_DIR` | Folder of `scilex init` profiles (default `~/.config/scilex/profiles`) |
| `LOG_LEVEL`, `LOG_COLOR` | Logging verbosity (`DEBUG`, `INFO`, ...) and colored output |

## Precedence

For `scilex.yml` values, lowest to highest:

```text
code defaults  <  preset  <  scilex.yml  <  command-line options
```

For API keys: `keys.yml` < `SCILEX_<API>_<FIELD>` environment variables.
Run `scilex config show` to see, for each value, whether it comes from the default, the preset, the file or the CLI.

## `scilex.yml`

Top-level keys:

| Key | Type | Default | Role |
|-----|------|---------|------|
| `name` | string | required | Name of the review; results go to `<output_dir>/<name>` (formerly `collect_name`) |
| `output_dir` | string | `output` | Output folder, relative to the working folder |
| `preset` | `literature_review` or `bibliometrics` | none | Named bundle of defaults, see the "Presets" section |

### `search`: what to collect

| Key | Type | Default | Role |
|-----|------|---------|------|
| `keywords` | list of 1 or 2 lists of strings | required | One group: papers matching any term. Two groups: any term of group 1 AND any term of group 2. A flat list of strings is read as one group. |
| `bonus_keywords` | list of strings | `[]` | Terms that raise the relevance score (they do not filter) |
| `years` | list of ints, or `"YYYY-YYYY"` | required | Years to search |
| `apis` | list of strings | required | APIs to query: `SemanticScholar`, `OpenAlex`, `IEEE`, `Elsevier`, `Springer`, `Arxiv`, `HAL`, `DBLP`, `Istex`, `OpenAIRE`, `ORKG`, `PubMed`, `BioRxiv` |
| `max_articles_per_query` | int or null | null | Cap per query; null means no limit |
| `semantic_scholar_mode` | `regular` or `bulk` | `regular` | `bulk` is faster but needs Semantic Scholar approval |
| `since` | `YYYY-MM-DD` or null | null | Incremental re-collection: years become year(since) to the current year, with a native date filter where the API supports it (OpenAlex, Semantic Scholar, arXiv, PubMed) and a post-filter at aggregation otherwise. Output goes to `<name>_since_<date>/`, merged and deduplicated by `scilex-aggregate`. Also available as `scilex-collect --since`. |

### `collect`: rare collection options

| Key | Type | Default | Role |
|-----|------|---------|------|
| `enabled` | bool | `true` | `false` skips collection and only aggregates existing data |
| `vpn` | mapping or null | null | VPN rotation block (see `scilex/vpn/rotator.py`) |

### `filters`: quality filters applied during aggregation

| Key | Type | Default | Role |
|-----|------|---------|------|
| `item_types` | list or null | null | null keeps every type; otherwise a whitelist (for example `[journalArticle, conferencePaper]`) |
| `always_keep` | list | `[journalArticle, conferencePaper]` | Types never removed by the quality filters; an empty list disables the bypass |
| `require` | list among `abstract`, `doi`, `year`, `open_access` | `[abstract, year]` | Fields a paper must have |
| `min_authors` | int >= 0 | `2` | Minimum number of authors |
| `abstract_words` | `[min, max]` | `[50, 1000]` | Accepted abstract length in words |
| `abstract_quality` | int 0-100 or null | null | Minimum abstract quality score; null disables the validation |
| `check_year_range` | bool | `true` | Drop papers whose year is outside `search.years` |
| `citations` | bool | `true` | Time-aware citation filter (for example at least 1 citation after 18 months) |

### `citations`

| Key | Type | Default | Role |
|-----|------|---------|------|
| `fetch` | bool | `true` | Fetch citation counts during aggregation (`scilex-aggregate --skip-citations` disables it for one run) |
| `fallbacks` | list among `semantic_scholar`, `openalex` | both | Extra sources used when the main resolution (cache, Semantic Scholar, CrossRef, OpenCitations) misses |
| `discrepancy_threshold` | float >= 0 | `0.5` | Relative gap between sources above which a warning is logged |

### `ranking`

| Key | Type | Default | Role |
|-----|------|---------|------|
| `enabled` | bool | `true` | Compute the composite 0-10 relevance score and sort |
| `max_papers` | int >= 1 or null | `1000` | Keep the top N papers; null keeps all |
| `weights` | mapping | `keywords: 0.45`, `quality: 0.25`, `itemtype: 0.20`, `citations: 0.10` | Score weights; only these four names are accepted, values must be >= 0 |
| `itemtype_weights` | mapping type to bool | `{}` | Partial override of the types that earn full item-type points (defaults: `journalArticle`, `conferencePaper`, `bookSection`, `book`) |
| `venue_ranking` | bool | `false` | Add a `venue_rank` column (CORE/SJR) and blend it 50/50 with the item-type score |

### `llm_screening`: optional LLM relevance scoring

Runs after the quality filters and before citations. Needs `openrouter.api_key` in `keys.yml` (or `OPENROUTER_API_KEY`).
Results are cached in `<output_dir>/<name>/llm_relevance_cache.json`.

| Key | Type | Default | Role |
|-----|------|---------|------|
| `enabled` | bool | `false` | Activate the step |
| `topic` | string | `""` | Description of the research topic; required when enabled |
| `model` | string | `deepseek/deepseek-v4-flash` | OpenRouter model |
| `threshold` | float or null | null | Drop papers whose `llm_relevance_score` is below this value |
| `max_papers` | int >= 1 | `500` | Cap on papers (not already cached) sent to the model |
| `workers` | int 1-64 | `16` | Concurrent OpenRouter requests |
| `price_input_per_m` | float >= 0 | `0.091` | USD per million input tokens, used for the cost estimate |
| `price_output_per_m` | float >= 0 | `0.182` | USD per million output tokens |

### `report`

| Key | Type | Default | Role |
|-----|------|---------|------|
| `quality_report` | bool | `true` | Write the filtering quality report |
| `track_duplicates` | bool | `true` | Keep track of which APIs found each paper |
| `prisma` | bool | `true` | Write `prisma_report.md` (PRISMA 2020 flow with a Mermaid diagram) at the end of `scilex-aggregate` |

### `enrichment`: optional steps

| Key | Type | Default | Role |
|-----|------|---------|------|
| `paperswithcode` | bool or mapping | `false` | `true` enables [Papers with Code](https://paperswithcode.co) enrichment (tasks, methods, benchmarks, GitHub repositories; anonymous API, no key). A mapping accepts `enabled` (`false`), `fuzzy_match_threshold` (`85`, 0-100), `cache_path` (`output/pwc_cache.db`), `cache_ttl_days` (`30`) and `workers` (`4`, 1-32, papers searched concurrently; `scilex-enrich --workers` overrides it). `huggingface` is a deprecated alias: it is still accepted with a warning and translated (`use_papers_api` is ignored); setting both is an error. |
| `recover_dois` | bool | `false` | Recover missing DOIs through CrossRef (title and first author) |
| `doi_recovery_min_similarity` | float 0-1 | `0.9` | Minimum title similarity to accept a recovered DOI |
| `unpaywall` | bool | `false` | Add the `oa_type` column through Unpaywall (needs `Unpaywall.email` in `keys.yml`) |
| `author_hindex` | bool | `false` | Add `first_author_hindex` and `last_author_hindex` through Semantic Scholar |

## Presets

A preset overrides some code defaults; `scilex.yml` then overrides the preset. Without a preset the code defaults apply unchanged.

| Preset | Values |
|--------|--------|
| `literature_review` | `filters.require: [abstract, year]`, `filters.citations: true`, `filters.abstract_quality: 60` |
| `bibliometrics` | `filters.require: []`, `filters.citations: false`, `filters.abstract_quality: null`, `ranking.max_papers: null` |

## `keys.yml`

One mapping per API, plus `rate_limits`. Keep only the APIs you use. Arxiv, HAL, DBLP and Istex need no key.
Do not commit this file: keep it in `~/.config/scilex/`.

| Section | Fields | Notes |
|---------|--------|-------|
| `SemanticScholar` | `api_key` | Optional, recommended |
| `OpenAlex` | `api_key` | Optional |
| `IEEE` | `api_key` | Required to use IEEE |
| `Elsevier` | `api_key`, `inst_token` | `inst_token` (optional) is a single institutional token |
| `Springer` | `api_key` | One key for both endpoints, or a mapping `meta_api_key` / `openaccess_api_key` |
| `PubMed` | `api_key` | Optional: 10 requests/s instead of 3 |
| `CrossRef` | `mailto` | Polite pool, faster batch lookups |
| `Unpaywall` | `email` | Required by `enrichment.unpaywall` |
| `HuggingFace` | `token` | Deprecated and unused (still accepted) |
| `openrouter` | `api_key` | For `llm_screening`; `OPENROUTER_API_KEY` also works |
| `Zotero` | `api_key`, `user_id`, `user_mode` (`user` or `group`) | For `scilex-push-zotero` |
| `ORCID` | `client_id`, `client_secret`, `dir` | Optional |
| `rate_limits` | `<API>: requests per second` | Overrides the built-in defaults (for example `SemanticScholar: 1.0`, `OpenAlex: 10.0`, `Arxiv: 0.33`) |

### Key lists (rotation)

`api_key` accepts one string or a list of strings:

```yaml
SemanticScholar:
  api_key: ["key1", "key2"]
```

Keys are used round-robin, one per request. On HTTP 429 a key is set aside for 60 seconds; on 401 or 403 for one hour.
The Springer mapping form and `Elsevier.inst_token` are not rotated.

## Commands

| Command | Role |
|---------|------|
| `scilex init` or `scilex-init` | Create `./scilex.yml` from a template (`--template NAME`), by interactive questions on a terminal, or as a commented skeleton. When no `keys.yml` exists, it prints where to create it from `keys.yml.example`. |
| `scilex-init --list-templates` | List templates (`computer-science`, `machine-learning`, `bioinformatics`, `clinical-medicine`, `social-sciences`) and saved profiles |
| `scilex-init --save-profile NAME` | Save the current `scilex.yml` as `~/.config/scilex/profiles/NAME.yml` (folder set by `SCILEX_PROFILES_DIR`) |
| `scilex-init --force` | Overwrite an existing file |
| `scilex config show` | Effective configuration, with the origin of each value (secrets are masked) |
| `scilex config check` | Validate both files without running anything; exit code 0 when valid |
| `scilex config migrate [--from DIR] [--write] [--force]` | Convert the legacy files to `scilex.yml`. Prints the result unless `--write` is given; `--from` is the folder holding the legacy files (default: the `scilex` package); `--force` overwrites an existing `./scilex.yml`. |

`python -m scilex collect|aggregate|status|enrich|export-bibtex|push-zotero|init|config` are equivalent to the
`scilex-*` commands.

## Legacy format and migration

Before this layout, configuration lived in three files inside the package: `scilex/scilex.config.yml`,
`scilex/scilex.advanced.yml` and `scilex/api.config.yml`. They are still read when no `scilex.yml` is found
(or when `--config` points to a file containing `collect_name`), with a warning. Convert them with
`scilex config migrate --write`, then move the keys to `~/.config/scilex/keys.yml`. `scilex.advanced.yml` no
longer exists as a file: everything lives in `scilex.yml`, in the relevant section.

`--resume` and `--collection` keep reading `config_used.yml` (an internal snapshot, not meant to be edited).
Templates and profiles saved in the old format are converted when read.

### Old name to new name

| Legacy (`scilex.config.yml` / `scilex.advanced.yml`) | `scilex.yml` |
|---|---|
| `collect_name` | `name` |
| `output_dir` | `output_dir` |
| `keywords`, `bonus_keywords`, `years`, `apis` | `search.keywords`, `search.bonus_keywords`, `search.years`, `search.apis` |
| `max_articles_per_query` (`-1` = no limit) | `search.max_articles_per_query` (null = no limit) |
| `semantic_scholar_mode` | `search.semantic_scholar_mode` |
| `since` | `search.since` |
| `collect: false` | `collect.enabled: false` |
| `vpn` | `collect.vpn` |
| `enable_itemtype_filter` + `allowed_item_types` | `filters.item_types` (null when disabled) |
| `enable_itemtype_bypass` + `bypass_item_types` | `filters.always_keep` (empty when disabled) |
| `require_abstract`, `require_doi`, `require_year`, `require_open_access` | `filters.require` |
| `min_author_count` | `filters.min_authors` |
| `min_abstract_words`, `max_abstract_words` | `filters.abstract_words` |
| `validate_abstracts` + `min_abstract_quality_score` | `filters.abstract_quality` (null when disabled) |
| `validate_year_range` | `filters.check_year_range` |
| `apply_citation_filter` | `filters.citations` |
| `aggregate_get_citations` | `citations.fetch` |
| `use_semantic_scholar_citations`, `use_openalex_citations` | `citations.fallbacks` |
| `canonical_citation_discrepancy_threshold` | `citations.discrepancy_threshold` |
| `apply_relevance_ranking` | `ranking.enabled` |
| `max_papers` | `ranking.max_papers` |
| `relevance_weights` | `ranking.weights` |
| `itemtype_relevance_weights` | `ranking.itemtype_weights` |
| `use_venue_ranking` | `ranking.venue_ranking` |
| `llm_screening` | `llm_screening` |
| `hf_enrichment` / `pwc_enrichment` (a missing block meant enabled) | `enrichment.paperswithcode` |
| `recover_missing_dois`, `doi_recovery_min_similarity` | `enrichment.recover_dois`, `enrichment.doi_recovery_min_similarity` |
| `enrich_unpaywall` | `enrichment.unpaywall` |
| `enrich_author_hindex` | `enrichment.author_hindex` |
| `unpaywall_email` | `Unpaywall.email` in `keys.yml` (not migrated automatically) |
| `generate_quality_report` | `report.quality_report` |
| `track_duplicate_sources` | `report.track_duplicates` |
| `generate_prisma_report` | `report.prisma` |
| `scilex/api.config.yml` | `~/.config/scilex/keys.yml` (same per-API structure) |
| `scilex/scilex.advanced.yml` | removed: use the sections of `scilex.yml` |
