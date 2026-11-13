# Survey bundle: what `survey.json` holds (draft)

The survey bundle is SciLEx's input to the scilex-lpwc-ap profile from iteration 5 on (ORSD SR1,
D29). It has two files:
- `<name>.bib`, the Zotero BibLaTeX export, as today;
- `survey.json`, everything else.

The authoritative JSON Schema will be the profile's `mappings/survey-bundle.schema.json`. This
page is the SciLEx-side draft it starts from: one section per review file, where SciLEx reads it,
and what the profile makes of it.

"Level" is the lowest disclosure level at which a section is exported (SR17):
- **P**: public;
- **T**: team;
- **F**: full.

A section above the dump's level is written as `{"status": "withheld"}`.

**Status (2026-11-12).** The profile has a reference writer, `scripts/survey_bundle.py`
(scilex-lpwc-ap). It writes `config`, `collect.queries`, `sources`, `aggregation`, `scores` and
`venues` from a collection folder. Only **`venues`** is mapped so far (profile iteration 7). The
JSON Schema (`mappings/survey-bundle.schema.json`) does not exist yet.

**Layout: flat parts, keyed by `paper`.** The reference writer and the profile's RML use one
top-level array per part, and each row carries the citation key in `paper`:
`"venues": [{"paper": "diet_digitization_2014", "journal": "Fontes artis musicae", "issn": "0015-6191"}]`.
The `papers[]` nesting below is the SciLEx-side draft. **Decided with SX-1 (2026-11-12): flat
parts.** morph-kgc iterates one JSONPath per logical source (`$.venues[*]`), and the manifest
(`parts`) then has one row count per array. The tables below keep their content; the parts
`scilex/kg/bundle.py` writes are listed in [Parts written](#parts-written-2026-11-12).

## Top level

| Key | Content | Source |
|---|---|---|
| `schemaVersion` | bundle schema version | constant, checked against the pinned profile |
| `review` | `name`, `slug`, `base` (SX-11), `owner` (ORCID IRI), `disclosure` | `review_state.yml`, `user.yml` |
| `generator` | SciLEx version, profile version IRI, `at` | `scilex.__version__`, `scilex/kg/ap/VERSION.json` |
| `parts` | manifest: per section `status` (present / absent / empty / withheld), `file`, `sha256`, `rows` | computed by `bundle.py` |

## Sections

| Section | Content | Source file(s) | Read by | Level | ORSD |
|---|---|---|---|---|---|
| `config.versions[]` | effective configuration per saved version: `sha256`, `at`, `values` (with `default: true/false`) | `scilex.yml`, `config_history/` (SX-7), `configure` events | `scilex.settings` (`config show`) | P | SR3, CFG1–CFG8 |
| `criteria.versions[]` | criteria per version: `id`, `kind`, `enabled`, `ec`, `ic`, `exception`, `params`, spared paper types | `criteria.yml`, `criteria_history/` (SX-8) | `gui/services/criteria.py` | P | SR4 |
| `grid` | dimensions: `tag`, `question`, paper types it applies to | `annotation_grid.csv` | `tagging/grid.py` | P | SR8, UCR18 |
| `subcorpora` | required names; Zotero collections with `role` (automatic / screened / extension *n* / agreement) and parent | `scilex.yml` `subcorpora`, `collection_roles.yml`, `extension_target.yml`, Zotero | `gui/services/collection_roles.py`, `consolidate.py` | P | SR7 |
| `papers[]` | `citation_key`, `paper_key`, `zotero_key` (SX-2); see below | corpus + the files below | `bundle.py` | P | SR5–SR16 |
| `members[]` | `id` (ORCID or Zotero user), `name`, `zotero_user`, `consent_public` (SX-6) | `members.yml` | `gui/services/members.py` | T (P: consenting ORCID iDs only) | SR8, SR17 |
| `agreement.studies[]` | `at`, sample, annotators, per-dimension measures, merge rule, codes per annotator, codes to adjudicate | `annotations/agreement/*.json` (SX-4), `agreement/<annotator>` collections | `gui/services/agreement.py` | T | SR9 |
| `annotation_history[]` | snapshots: `at`, papers, annotated, pending, codes, per dimension (+ codes, SX-20) | `annotation_history.jsonl` | `gui/services/journal.py` | P | SR11 |
| `journal[]` | events: `n` (line), `at`, `activity`, `agent`, `used`, `generated`, `status`, `inferred`, `params` (F only) | `workflow.jsonl` | `gui/services/journal.py` | P (without `params`) | SR10 |
| `zotero` | library type / id / collection, library version per sync | `zotero_source.yml`, `zotero_sync_state.json` | `gui/services/zotero_library.py` | P | SR10 |
| `queries[]` | keyword combination, year, API, count, date, run (SX-19) | collect state, `output/<name>/<API>/` | `collect_status.py` | P | SR12, UCR14 |
| `snowball` | direction, limits, seeds | `snowball.yml` | `gui/services/snowball_scope.py` | P | SR12, LR4 |
| `aggregation` | per-phase counts | `filtering_summary.json`, `aggregation_stats.csv` | `pipeline/report.py` | P | SR15 |
| `citation_snapshots[]` | id, source (Zotero snapshot / live), read date, number of links | `zotero_citations.json`, caches | `gui/services/zotero_citations.py` | P | SR13 |
| `enrichment_runs[]` | source, agent, at, columns written, papers updated | `job:analysis-*` events | `gui/services/journal.py` | P | SR14 |
| `keyword_suggestions[]` | suggested terms, cluster | `graph_analysis/keyword_suggestions.yml` | `suggest_keywords.py` | P | SR14, KR |
| `origin_kg` | IRI and version of the dump this review was created from | `kg_source.yml` | `gui/services/kg_import.py` | P | SR19 |
| `venues[]` | per paper: `journal` (venue name), `issn`, `conference`. **Mapped since profile iteration 7.** Needed while the Zotero push drops the venue name (SX-23); after the fix, it still records what the API returned. | corpus columns `journalAbbreviation` (holds the *full* name), `serie` (an ISSN for OpenAlex records), `conferenceName` | `scilex/Zotero/zotero_api.py` | P | VR2, VR8 |

### `papers[]` entries

| Key | Content | Source | Level |
|---|---|---|---|
| `first_seen`, `origin` | date and origin (Collect, Extend collect, Zotero / KG / BibTeX import, Snowball) | `paper_log.json`, `extension_origin` | P |
| `snowball_depth`, `queries` | depth; queries that found it (SX-19) | corpus, deduplication | P |
| `sources[]` | `{api, id}` | `archive`, `archiveID` | P |
| `search_terms`, `bonus_terms` | matched terms | `collect_keywords`, `bonus_keyword_tags` | P |
| `scores` | `relevance`, `quality`, with the activity that computed them | `relevance_score`, `quality_score` | P |
| `metrics` | `metric_*` values, `computed_at`, `snapshot` (SX-9) | corpus | P |
| `enrichment` | per source: values and the run that brought them (SX-18) | `lpwc_*`, `orkg_*`, `crossref_*`, `zenodo_*`, `code_license`, `code_repository`, `pwc_*` | P |
| `paper_types[]` | `{type, origin}` (SX-17) | `PAPER_TYPE:` tags, `paper_type_origin` | P |
| `excluded[]` | `{by: filter:<C> or agent, criteria_version, cause, at}` | `DELETED_BY:` tags (SX-3), criteria history | P (person causes: T) |
| `keep[]` | criteria it is an exception to | `KEEP:` tags | P |
| `screening` | `decision`, `at`, `by` (SX-5), `note` | `screening.csv` | P (`note`: T) |
| `assigned_to[]`, `validated_by[]` | agent ids | `ANNOT:`, `ANNOT_VALID_BY:` tags | P (ids per member consent) |
| `subcorpora[]` | collection paths | `zotero_collections` | P |

## What never goes in

`keys.yml`, `review_keys.yml`, VPN settings, `user.yml` beyond the ORCID iD, caches
(`*_cache.json`, `*.db`), GUI state (`gui_run_history.json`, `explore_selection.csv`), raw API
payloads (only their identity, ORSD D35), charts and figures. Every string goes through
`sanitize_secrets` (SX-14).

## Parts written (2026-11-12)

`scilex/kg/bundle.py` (`PARTS`). Every row of a paper part has `paper`, the citation key (a
paper without BibLaTeX entry: `sx-<sha1(paper_key)[:12]>`). Level = lowest disclosure level.

| Part | Row | Level |
|---|---|---|
| `papers` | `paper`, `paper_key`, `zotero_key`, `in_bibliography` | P |
| `config_versions` | `key` (12 hex), `sha256`, `at`, `version`, `previous` | P |
| `config_parameters` | `config`, `path`, `value` (text or JSON), `datatype`, `default` | P |
| `criteria_versions` | as `config_versions` | P |
| `criteria` | `version`, `id`, `kind`, `label`, `enabled`, `ec`, `ic`, `exception`, `params` (JSON) | P |
| `grid` | `dimension`, `question`, `paper_types` | P |
| `subcorpora` | `path`, `role`, `paper_type`, `zotero_key` | P |
| `members` | `id` (consent or pseudonym at P), `name` and `zotero_user` (T), `role`, `consent_public` | P |
| `screening` | `paper`, `decision`, `at`, `by`, `note` (T) | P |
| `excluded` | `paper`, `by` (`filter:<C>` or agent), `criterion`, `criteria_version`, `cause`, `kept` | P |
| `keep` | `paper`, `criterion` | P |
| `assignments` | `paper`, `agent`, `role` (`assigned` / `validated`) | P |
| `paper_types` | `paper`, `type`, `origin` | P |
| `agreement_studies` | `study`, `at`, `file`, `sample`, `annotators`, `merge_rule`, `to_adjudicate` | T |
| `agreement_measures` | `study`, `dimension`, `measure`, `distance`, `alpha`, `papers`, `values` | P |
| `agreement_codes` | `study`, `paper`, `annotator`, `dimension`, `value` | T |
| `journal` | `n`, `at`, `activity`, `agent`, `status`, `inferred`, `used` / `generated` (JSON), `params` (F), `message` | P |
| `annotation_history` | `snapshot`, the snapshot's counts (`by_dimension` as JSON) | P |
| `annotation_codes` | `snapshot`, `paper`, `code`, `change` (`added` / `removed`) | P |
| `paper_log` | `paper`, `first_seen`, `origin` | P |
| `snowball` | the settings of `snowball.yml` (an object) | P |
| `aggregation` | `stage`, `count` (or `at` for `run_date`) | P |
| `scores` | `paper`, `relevance`, `quality` | P |
| `venues` | `paper`, `journal`, `issn`, `series`, `conference` | P |
| `metrics` | `paper`, `metric`, `value`, `computed_at` | P |
| `enrichment` | `paper`, `column`, `value` | P |
| `zotero` | `library_type`, `library_id`, `collection_key`, `collection_name` | P |
| `origin_kg` | `kg_source.yml` without local paths | P |

Not written yet: `queries` / `sources` (SX-19), `citation_snapshots` (SX-9), per-value enrichment
runs (SX-18), `keyword_suggestions`.
