# SciLEx developments for the complete knowledge-graph dump

Each development has an id (`SX-n`), the profile requirements it serves (scilex-lpwc-ap,
iteration 5 ORSD: `SR` = §5septies, `D` = decisions, others from earlier sections), the code it
touches, and how it is tested. Status values: `todo`, `doing`, `done`. SX-22 and SX-23 come
from profile iterations 6–8 (see [README.md](README.md)). Status on 2026-11-12, after the first
implementation pass: see [Progress](#progress-2026-11-12).

## Summary

| Id | Development | Serves | Status |
|---|---|---|---|
| SX-1 | Write the survey bundle (`survey.json`) | SR1, SR2 | done |
| SX-2 | One join key between results rows, Zotero items and citation keys | SR1, SR5, SR6, SR12 | done |
| SX-3 | Keep discarded papers and agreement copies in the export, flagged | SR5, SR9, D31 | done |
| SX-4 | Persist agreement studies (sample, measures, merge) | SR9, AR5, AR6, UCR19 | done |
| SX-5 | Record who made each screening decision | SR6, D37 | done |
| SX-6 | Disclosure levels and member consent | SR17, D36 | done |
| SX-7 | Keep every saved version of the effective configuration | SR3, CFG1, CFG2 | done |
| SX-8 | Keep every saved version of the eligibility criteria | SR4, UCR17 | done |
| SX-9 | Tie metrics to their citation snapshot | SR13, LR10 | todo |
| SX-10 | Restore a review from a dump | SR19 | todo |
| SX-11 | Stable base IRI and activity IRIs per review | SR20, LR8, D-i4-1 | done |
| SX-12 | Pin the profile's iteration 4, then 5; KG tests on a review fixture | NFR6, NFR8 | doing |
| SX-13 | Remove post-mapping triples from `build.py` | SR1, D30 | done |
| SX-14 | Secret scan of the bundle and the graph | SR18, CFG7 | done |
| SX-15 | PRISMA parity test (Overview vs. SPARQL) | SR15, GCQ73 | todo |
| SX-16 | TriG output with one named graph per part, and the manifest | SR2, D34 | todo |
| SX-17 | Record the origin of each paper type | SR16, CR4 | done |
| SX-18 | Per-paper enrichment provenance | SR14, AR9, AR11 | todo |
| SX-19 | Query-level acquisition (keyword combination × year × API) | SR12, UCR14, LR2 | todo |
| SX-20 | Store the codes in each annotation snapshot | SR11 | done |
| SX-21 | Read Zotero item dates and tag authors | SR5, SR8, D10 | todo |
| SX-22 | Grid declaration in the generated collection profile (value types, hierarchy, rules) | UCR3, UCR4, UCR20, D38 | doing |
| SX-23 | Zotero push: venue name, ISSN and series in the right Zotero fields | VR2, VR8, VR9 | done |

## Details

### SX-1 — Write the survey bundle

New `scilex/kg/bundle.py`: `write_bundle(review, disclosure) -> Path`. It writes
`output/<name>/kg/bundle/survey.json`, next to the BibLaTeX export, and validates it against the
pinned `scilex/kg/ap/mappings/survey-bundle.schema.json`. `jsonschema` is not a SciLEx dependency
yet; add it to the `kg` extra in `pyproject.toml`. Sections and sources: [survey-bundle.md](survey-bundle.md). Each section
records its source file, SHA-256, row count and status: `present`, `absent` (step never run),
`empty` or `withheld` (disclosure). This gives the profile its manifest (SR2).
`scilex-build-kg` and `kg_export.py` call it before the mapping and pass its path as a new
placeholder (`{{SURVEY}}`, to declare in the profile's `MANIFEST.json`).
Since profile iteration 7, the profile maps the `venues` section (`rml/survey-venues.rml.ttl`). It
runs `rml/*survey*.rml.ttl` only for a collection profile that names a bundle (key `"survey"`).
Start from the profile's reference writer `scripts/survey_bundle.py` and its flat-part layout
([survey-bundle.md](survey-bundle.md)).
**Test:** a fixture review folder in `tests/fixtures/review_full/` with every file of
`docs/reference/review-files.md`. The bundle validates, and every section is `present`.

### SX-2 — One join key

Today the review files use three keys for one paper:
- `screening.csv` and `paper_log.json` use `paper_key` (`doi:<doi>`, else `title:<normalised>`,
  `scilex/gui/services/screening.py`);
- the corpus uses its row and the Zotero item key;
- the knowledge graph uses the BibLaTeX citation key (`br/<key>`).

The bundle needs one key per paper, plus the others as aliases. Add `paper_key` and
`zotero_key` to every paper entry of the bundle. The citation key is read from the BibLaTeX
export (Better BibTeX / Zotero) and matched through the Zotero item key. Papers without a Zotero
item (review not linked) get a key derived from `paper_key`.
**Test:** every screening decision and paper-log entry of the fixture lands on exactly one
paper of the graph.

### SX-3 — Keep discarded papers and agreement copies, flagged

`build.py` leaves out `DELETED_BY:` papers and `AGREEMENT_COPY:` items (`1e58b6c3`). Instead:
- discarded papers go into the bundle with `excluded: [{by, cause, at}]`, where `by` is
  `filter:<criterion>` or an agent id. `KEEP:<C>` tags go in `keep: [C…]`;
- agreement copies are **not** papers. Their codes go into `agreement.studies[].codes` as
  `{paper (original key), annotator, dimension, value}`.

The Overview, analyses and charts keep filtering discarded papers out; only the export changes.
**Test:** the fixture has 2 discarded papers and 1 study with 2 copies. The graph has 2
exclusions and per-annotator codes on the originals, and no paper made from a copy.

### SX-4 — Persist agreement studies

`scilex/gui/services/agreement.py` computes Krippendorff's α (MASI) and merges codes, but writes
neither the result nor the merge outcome. Write `output/<name>/annotations/agreement/<at>.json`
with:
- the sample (original paper keys) and the annotators (ids);
- per dimension: α, distance, number of papers and annotators;
- the merge rule (all / majority) and the codes left to adjudicate.

Journal events `agreement-copies`, `agreement-computed` and `agreement-merged` point to that file
(`generated.file`).
**Test:** a computed study gives a file and an event; the bundle carries both.

### SX-5 — Who made each screening decision

Add `decided_by` (ORCID iD of the app user, `journal.current_agent()`) to `screening.csv`
(`FIELDS` in `screening.py`). Old rows keep an empty value, which becomes an unknown agent (D37).
The Zotero sync keeps `SCREEN:` tags as they are.
**Test:** a decision made in ③ Screen has the user's ORCID iD; an old file still loads.

### SX-6 — Disclosure levels and member consent

- `members.yml`: a `consent_public` flag per member, set in ④ Annotate → Annotators.
- Export → Knowledge graph and `scilex-build-kg --disclosure public|team|full`. The default is
  `public` for a file meant to be shared.

Withheld at public level:
- screening notes, the free-text causes typed by people, members' names;
- the ORCID iD of members without consent (they get a pseudonymous `agent/<n>`);
- per-annotator codes and journal `params`.

Withheld at team level: journal `params`. The bundle states the level; the profile's per-level
shapes check it (SR17).
**Test:** the public dump of the fixture has no note, no name and no non-consenting ORCID iD.

### SX-7 — Configuration versions

The journal's `configure` events keep only the SHA-256 of `scilex.yml`. On each save, also write
the **effective** configuration (`scilex config show` values, with set-by-user vs. default
flags; never `keys.yml`) to `config_history/<sha256>.yml` in the review folder. The bundle carries
every version, with its date and the activities that used it.
**Test:** two saves give two versions; the collect job event points to the right one.

### SX-8 — Criteria versions

Same for `criteria.yml`: `criteria_history/<sha256>.yml` on each save, and the `criteria` event
(already journaled) gets the hash. `DELETED_BY:filter:<C>` exclusions then point to the criteria
version applied.
**Test:** applying criteria v1, editing, then applying v2 gives exclusions tied to the right
version.

### SX-9 — Metrics tied to their citation snapshot

`metric_computed_at` dates the metrics, but nothing says which network they came from. Record the
source (`zotero_citations.json` and its read date, or the live caches) in a `metric_source`
column, or in the `job:analysis-metrics` event. Do the same for `relevance_score` /
`quality_score` (the collect / aggregation activity and config version that computed them).
**Test:** the bundle gives, for each paper with metrics, a snapshot id and a date.

### SX-10 — Restore a review from a dump

`scilex/gui/services/kg_import.py` rebuilds only the corpus today (Zotero-shaped items, deduced
grid). Extend it to rebuild, from the graph:
- `scilex.yml` (latest effective version) and `criteria.yml`;
- `screening.csv`, `annotation_grid.csv` (questions, paper types), `members.yml`;
- `collection_roles.yml`, `paper_log.json`;
- the journal: imported events, marked `imported_from` the dump.

Record `kg_source.yml` → the dump's IRI and version (`prov:wasDerivedFrom`).
**Test:** round-trip on the fixture: review → dump → review → dump gives isomorphic graphs,
up to the documented losses of the disclosure level.

### SX-11 — Stable IRIs

The base IRI is `https://w3id.org/scilex/data/<slug>/` today. That can collide between users, and
it changes when a review is renamed. Store the base once, at the first dump, in `review_state.yml`
(`kg_base`), and reuse it for every later dump. The choice of pattern is the profile's open
decision D-i4-1. Activity IRIs: `activity/<n>`, where `n` is the line number in `workflow.jsonl`
(append-only, so stable).
**Test:** two dumps of the fixture, before and after a rename, share all paper, criterion and
activity IRIs.

### SX-12 — Profile pin and KG tests

`python -m scilex.kg.sync_profile` installs iteration 4 once it is released (tag + `final/`), then
the latest evaluated iteration (8 on 2026-11-12). Iterations 6 and 8 add placeholders
(`{{GRID_*}}`, `{{KNOWN_SERIES}}`). The profile's own `mappings/ap_profile.py`
(`placeholder_values`) fills them, so SciLEx must call it rather than rebuild the values (A2).

morph-kgc 2.10, which SciLEx pins, crashes on any FnO function that returns a **literal**
(`KeyError: 'reference_results'` in `materializer._materialize_fnml_execution`). Profile
iteration 8 works around it: FnO for IRIs only, literals in SPARQL. Check that case before
upgrading morph-kgc. `tests/test_kg.py` gets the fixture review of SX-1 and checks:
- expected triple counts;
- the answers of GCQ66–GCQ75;
- that the shapes conform.

### SX-13 — No triple after the mapping

Once the profile maps the bundle, remove `describe_dataset` and `describe_subcorpora` from
`scilex/kg/build.py`; their data goes through the bundle (owner, sub-corpora, generator, profile
version). Keep the code path for iteration 3 profiles, chosen by `VERSION.json`.

### SX-14 — Secret scan

Run `sanitize_secrets` on every string of the bundle (journal `used` / `params` included), and
check the graph with a SPARQL query for key-like literals (`api_key`, `token`, `Bearer`, long
hex / base64 strings, e-mail addresses from `keys.yml`). The query must return nothing (SR18).
**Test:** a fixture with a planted key in a URL and in a journal `params` gives a clean bundle
and graph.

### SX-15 — PRISMA parity

`scilex/gui/services/prisma.py` computes the flow. The profile's GCQ73 computes it from the
graph. A test runs both on the fixture and compares them stage by stage. Counts that the corpus
cannot give (raw records per API, duplicates, aggregation filters) come from
`filtering_summary.json` / `aggregation_stats.csv` in the bundle.

### SX-16 — TriG and manifest

Write `output/<name>/kg/<name>.trig`, with one named graph per part:
- bibliography, protocol, decisions, team, history, metrics;
- the manifest graph.

Also write a merged `<name>.ttl` for tools without quads. The Export page lists the parts and
their status (present / absent / withheld) from the manifest. Depends on the profile's D34.

### SX-17 — Paper type origin

`PAPER_TYPE:` tags do not say who set them. Record the origin in a `paper_type_origin` column
(`person:<id>`, `enrich`, `default-guess`) when ③ Screen, Explore or ⑥ Enrich set a type. Without
a record, the origin is `unknown`.

### SX-18 — Per-paper enrichment provenance

The journal says which columns a run wrote and how many papers it updated, but not **which
papers**. Each enricher records, per paper, `{source, at}` in an `enrichment_log` column (or in
`<source>_cache.json` with a date, which the bundle reads). Then every LPWC, ORKG, Crossref,
Zenodo or licence value in the graph points to the run that brought it (SR14). Inferred links
(LPWC / ORKG by title) are flagged as such.

### SX-19 — Query-level acquisition

A query is the unit of the profile (keyword combination × year × API, UCR14). The raw folders
under `output/<name>/<API>/` hold one answer per query, but the corpus keeps only the union of
`archive` / `archiveID`. The bundle should carry:
- the list of queries, from the collect state: keywords, year, API, result count, date, run;
- per paper, the queries that found it, kept through deduplication (`duplicate_tracking.py`
  already knows the merged records).

This also feeds GCQ26 (papers per API before and after deduplication).

### SX-20 — Codes in annotation snapshots

`annotation_history.jsonl` stores counts only. To date the first appearance of each code
(provenance proposal, step 4), store the codes per snapshot, or the codes added and removed since
the previous snapshot.

### SX-21 — Zotero dates and tag authors

Read `dateAdded` / `dateModified` and `meta.createdByUser` / last modifier from the Zotero JSON API
(provenance proposal, step 5). This dates exclusions, assignments and validations made in Zotero
rather than in SciLEx, and attributes them when no ORCID iD is in the tag (profile D10).

### SX-22 — Grid declaration in the generated collection profile

Profile iteration 6 lets a collection profile declare, per dimension:
- `values`: `binary` (0 / 1), `closed` with a `list`, `magnitude` (10^k or counts), `integer`,
  `open`; a binary dimension may send its other values to another dimension (`other_to`);
- `broader`: value → broader values (`skos:broader`; a narrower value satisfies a rule);
- `implies`: value → values a paper must also have (`sxv:implies`; violations: GCQ61, D38).

`scilex/kg/build.py` generates the profile from `annotation_grid.csv`, but writes dimension names
only. Add optional grid columns (`type`, `values`, `broader`, `implies`), or read them from the grid
editor, and write them into the generated profile. Without them, the profile behaves as in
iteration 5: values are untyped, and `NB*` names are read as orders of magnitude.
**Test:** the UCD grid (`re-slr`) declared through `annotation_grid.csv` gives the same profile as
the curated `mappings/collections/re-slr.json`, and GCQ61 returns the same 127 rows.

### SX-23 — Venue fields of the Zotero push

`scilex/Zotero/zotero_api.py` (the `common_fields` loop and the `series` branch after it) does two
things:
- it writes the corpus column `journalAbbreviation`, which holds the **full** venue name the API
  returned, into Zotero's *Journal Abbr* field;
- it writes `serie` into *Series*. For OpenAlex records, `serie` is an **ISSN**.

No `publicationTitle` and no `ISSN` are set. The Zotero BibLaTeX export then has
`series = {0004-4024}` and no `journaltitle`. In the profile's test collections, this left 217
journals without a name (profile iteration 7: t84-tools 173, chdo-lifecycle 33,
goblin-wg11-survey 11). Book series such as LNCS (`0302-9743`) also came out as journals.

Change:
- `journalAbbreviation` → `publicationTitle` for journal articles (and `proceedingsTitle` for
  conference papers when the API gives the proceedings). Keep *Journal Abbr* for real
  abbreviations only.
- A `serie` that is an ISSN (`NNNN-NNNC`) → the item's `ISSN` field, never `series`.
- `series` only for a series name (Lecture Notes in Computer Science, CEUR Workshop Proceedings).
- `conferenceName` unchanged. Keep its year when the API gives it: profile iteration 8 builds the
  conference series and edition from it.

The bundle's `venues` section (SX-1) stays the fallback for libraries pushed before the fix.
**Test:** push a fixture row with `journalAbbreviation`, an ISSN in `serie` and a `conferenceName`.
The Zotero BibLaTeX export has `journaltitle`, `issn` and `eventtitle`, and no ISSN in `series`.

## Progress (2026-11-12)

First implementation pass, with Claude Code (Anthropic). To be reviewed by the maintainer.
The whole test suite passes on Windows (2431 tests).

| Id | What was done | Where | What is left |
|---|---|---|---|
| SX-12 | Profile **iteration 8** pinned from the local checkout (`sync_profile --local`, `+dirty`: not released). `sync_profile` now also copies `mappings/ap_profile.py`, `collections/_*.json`, `alignments/*.json` and the JSON Schemas. `prepare_mapping` runs iteration 4+ profiles through the profile's own `ap_profile.py` (effective profile, `placeholder_values`, strict `expand`); SciLEx only overrides `{{SURVEY}}`, whose path the profile resolves under its own `raw_data/`. | `scilex/kg/sync_profile.py`, `scilex/kg/profile.py` (`_prepare_contract`, `collection_profile_v4`) | Pin a released iteration (tag + `final/`). KG tests on the fixture: triple counts, GCQ66–GCQ75. |
| SX-23 | `journalAbbreviation` (a full venue name) → `publicationTitle`; an ISSN in `serie` → `ISSN` (normalised `NNNN-NNNC`); `series` keeps series names only; `conferenceName` unchanged. *Journal Abbr* is no longer written. | `scilex/Zotero/zotero_api.py` (`_set_venue_fields`) | `proceedingsTitle`: no API gives the proceedings title apart from the venue, so it is left empty. Libraries pushed before the fix still need the bundle's `venues`. |
| SX-2 | `join_papers`: each BibLaTeX entry and each corpus row get the same `paper_key` (normalised DOI, else title and year); the bundle's `papers` part lists `paper` (citation key), `paper_key`, `zotero_key`, `in_bibliography`. A corpus paper without entry gets `sx-<sha1(paper_key)[:12]>`. | `scilex/kg/bundle.py` | The Zotero BibLaTeX export carries no item key, so the join goes through the DOI / title, not the Zotero key. |
| SX-1 | `scilex/kg/bundle.py` writes `kg/bundle/survey.json` before the mapping (GUI and `scilex-build-kg`); the collection profile names it (`survey`), so the profile's `rml/*survey*` mappings run. **Flat parts** keyed by `paper` (decision, see [survey-bundle.md](survey-bundle.md)). Manifest `parts`: status, source, SHA-256, rows. | `scilex/kg/bundle.py`, `scilex/gui/services/kg_export.py` | Validation against `mappings/survey-bundle.schema.json` once the profile publishes it (`jsonschema` not added yet). The fixture lives in `tests/test_kg_bundle.py` rather than `tests/fixtures/review_full/`. |
| SX-14 | Every bundle string goes through `sanitize_secrets` and masks the keys file's values; `find_secrets` scans the built graph (keys file values, `api_key` / `token` / `Bearer`, random-looking tokens; SHA hashes allowed). The export reports `suspect_literals` instead of failing. | `scilex/kg/bundle.py`, `scilex/kg/build.py` | A SPARQL form of the scan for the profile's validation, if wanted. |
| SX-22 | Optional grid columns `type`, `values`, `broader`, `implies`, `other_to`, `lpwc` → the collection profile's dimension entries; `detail` → `question`. | `scilex/kg/profile.py` (`grid_declaration`) | The test against `re-slr.json` and GCQ61's 127 rows. A grid editor for these columns. |
| SX-13 | With an iteration 4+ profile, `build.py` adds no triple after the mapping: `05-dataset.ru` writes the dataset, creator (`{{CREATOR}}`), generator and config hash; sub-corpora go through the profile's `subcorpora` table (`void:subset` / `void:inDataset`). `describe_dataset` / `describe_subcorpora` stay for older profiles. | `scilex/kg/build.py` | — |
| SX-5 | `screening.csv` gets `decided_by` (ORCID iD IRI of the app user); old rows keep an empty value. | `scilex/gui/services/screening.py` | — |
| SX-7 | Each save of `scilex.yml` writes `config_history/<sha256>.yml` (effective values, `default` flag, no key / e-mail / VPN / path). Every `job:*` event records `used: {scilex.yml sha256}`. | `scilex/gui/services/versions.py`, `config_editor.py`, `journal.py` | Versions of files edited outside the app are saved at the next job or export (`ensure_current`). |
| SX-8 | Same for `criteria.yml` (`criteria_history/`); the `criteria` event records the version applied (`used: {criteria.yml sha256}`). | `versions.py`, `criteria.py` | The bundle ties every filter exclusion to the last version applied (no exclusion date yet, see SX-21). |
| SX-4 | `agreement.compute` writes `annotations/agreement/<at>.json` (sample, annotators, α / MASI per dimension, codes per annotator); `merge` adds the rule and the codes to adjudicate. Events `agreement-copies`, `agreement-computed` (`generated.file`), `agreement-merged`. | `scilex/gui/services/agreement.py` | — |
| SX-3 | The bundle lists discarded papers in `excluded` (`by`: `filter:<C>` or an agent, `cause`, `criteria_version`) and `keep`; agreement copies are never papers, their codes are `agreement_codes` on the original. The BibLaTeX export keeps discarded papers **only when the pinned profile maps `$.excluded[*]`** (`profile.maps_part`), so a graph never shows them as members before the profile can flag them. Workflow and metric tags leave the keywords when a bundle is written. | `bundle.py`, `zotero_library.py`, `build.py` | Nothing on the SciLEx side; waits for the profile's iteration 5 survey record. |
| SX-6 | `members.yml`: `consent_public` (④ Annotate → Annotators, **Named in public dumps**). `--disclosure public\|team\|full` and a selector in ⑧ Export. Public: no note, no name, no non-consenting ORCID iD (`agent/<n>`), no per-annotator code, no journal `params`. Team: no journal `params`. | `bundle.py`, `members.py`, `annotators.py`, `export.py`, `build_kg.py` | The profile's per-level shapes (SR17). |
| SX-11 | The base IRI is kept in `review_state.yml` (`kg_base`) from the first dump on; renaming the review keeps it. Iteration 4+ profiles accept any base. Journal rows carry `n` (their line) for `activity/<n>`. | `kg_export.py` (`stable_base_iri`) | The pattern itself (profile D-i4-1). |
| SX-17 | `paper_type_origin` column: `person:<ORCID IRI>` (Screen, Explore: `members.apply_tags`), `collection-role`, `default-guess` (⑥ Enrich); empty → `unknown`. | `scilex/paper_types.py`, `members.py`, `collection_roles.py` | — |
| SX-20 | Snapshots taken from Zotero items record `codes_added` / `codes_removed` (Zotero key, `DIM:value`) since the previous one; `codes_at` replays them. The bundle's `annotation_codes` maps them to citation keys. | `scilex/gui/services/overview.py` | Snapshots before 2026-11-12 have counts only. |
| SX-9, SX-10, SX-15, SX-16, SX-18, SX-19, SX-21 | Not started. SX-15 and SX-16 wait for the profile (GCQ73, D34); SX-10 for the survey record in the graph. | | |

### Found on the profile side

- With sub-corpora, iteration 8's own shapes report 3 violations on a SciLEx graph: a paper in a
  sub-corpus has two `void:inDataset` (`collection-item` allows one), and a `subcorpus/<slug>`
  dataset has no `dcterms:conformsTo` / `prov:wasDerivedFrom` (`kg-dataset`). Either the shapes
  should target the main dataset only, or the mapping should use another property for
  sub-corpus membership.
- `placeholder_values` resolves `{{SURVEY}}` as `raw_data/<file>`: a tool running the mapping
  elsewhere has to override it. A `survey_path` argument would avoid that.
