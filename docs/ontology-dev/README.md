# Ontology development: what SciLEx must do for a complete knowledge-graph dump

Status: plan, 2026-11-12 (updated after profile iterations 5–8). Drafted with Claude Code
(Anthropic); to be reviewed by the maintainer.
Not part of the user documentation (excluded from the Sphinx build, like `decisions/` and `wip/`).

This folder lists the SciLEx developments needed to fully support the
[scilex-lpwc-ap](https://codeberg.org/cringwald/scilex-lpwc-ap) application profile. The goal is a
**knowledge-graph dump of a whole SciLEx survey**: not only its Zotero library, but everything the
review folder records. The requirements live in the profile's **iteration 5 ORSD**
(`iterations/iter5/orsd/requirements.md`, §5septies, requirements `SR1`–`SR21`, decisions
`D29`–`D37`). This folder is the SciLEx side of that work.

| File | Content |
|---|---|
| [developments.md](developments.md) | The developments `SX-1`…`SX-21`: what to change, where, which requirement it serves, how to test it |
| [survey-bundle.md](survey-bundle.md) | Draft of `survey.json`, the file SciLEx writes for the profile: one section per review file, with its source and the code that reads it |

## Update (2026-11-12, evening): first implementation pass

Profile **iteration 8** is pinned and run through its own `ap_profile.py`. The survey bundle is
written with every export. Phases 0–2 are done except the KG fixture tests of SX-12 and the
`re-slr` comparison of SX-22. SX-6, SX-11, SX-13, SX-14 and SX-20 are done too. Details and
what is left: [developments.md, Progress](developments.md#progress-2026-11-12).

## Where we were (2026-11-12: commit `40b48cc9` plus uncommitted changes; profile iteration 3 pinned)

`scilex-build-kg` and ⑧ Export → Knowledge graph (`scilex/kg/build.py`) do the following:
- export the review's Zotero library as BibLaTeX;
- generate a collection profile from `annotation_grid.csv`;
- run the profile's RML + SPARQL;
- add a few triples afterwards: dataset creator, sub-corpora, profile version;
- validate the result with the profile's general shapes.

So the graph holds **what Zotero holds**, minus what SciLEx drops on purpose:
- discarded papers (`DELETED_BY:`) and agreement copies are left out (`1e58b6c3`);
- workflow and metric tags are never annotation codes (`cbefe3fc`).

Not in the graph today: `scilex.yml` (only its hash with iteration 4 profiles), `criteria.yml`,
`screening.csv`, `members.yml`, `collection_roles.yml`, `snowball.yml`, `paper_log.json`,
`workflow.jsonl`, `annotation_history.jsonl`, agreement results, `metric_*` values, enrichment
columns (`lpwc_*`, `orkg_*`, `crossref_*`, `zenodo_*`, `code_license`), and the PRISMA counts.
The full inventory is in ORSD §5septies.a.

## Profile side since iteration 4 (2026-11-12)

Iterations 5–8 of the profile are built and evaluated in X-DigCheck (locally; not released yet).
What each one means for SciLEx:

| Profile iteration | What changed in the profile | Consequence for SciLEx |
|---|---|---|
| 5, step 1 | iter4 regressions fixed (PDF embodiment typed `fabio:DigitalManifestation`; ontology rebuilt, 0 undeclared terms). The survey record itself (`SR1`–`SR21`) is **not** built: it waits for the bundle. | None yet: SX-1 is still the blocker. |
| 6 | **Grid declaration** in the collection profile: per dimension `values` (`binary`, `closed` + `list`, `magnitude`, `integer`, `open`), `broader` (hierarchy) and `implies` (implication rules). One `oa:Annotation` per code (AR3). | The profile SciLEx *generates* from `annotation_grid.csv` can carry value types and rules (**SX-22**). The annotator and date of each code need SX-21 and the bundle's `assigned_to` / `validated_by`. |
| 7 | First bundle section consumed: **`venues`** (`rml/survey-venues.rml.ttl`). Journals known only by an ISSN take their name from it: 217 → 13 untitled journals. | The cause is in SciLEx's Zotero push (**SX-23**). Until it is fixed, SX-1 must write `venues` (see [survey-bundle.md](survey-bundle.md)). |
| 8 | **Venue chain**: conference series (`lpwc:conference`) and editions (`bibo:Conference`, one per series and year) from `eventtitle`; book series written as journals (LNCS, CEUR-WS…) retyped from a reference table of ISSNs. | The push should keep `conferenceName` with its year, and write real series names to *Series* (SX-23). morph-kgc 2.10, which SciLEx pins, cannot write FnO literals: the profile now computes literals in SPARQL (SX-12). |

The profile's reference bundle writer, `scripts/survey_bundle.py` in scilex-lpwc-ap, already
reads a SciLEx collection folder (`output/<name>/`): config versions, queries, sources,
aggregation, scores and venues. SciLEx's `bundle.py` (SX-1) can start from it.

## The approach

1. **SciLEx writes a survey bundle; the profile maps it.** The bundle is the BibLaTeX export plus
   a `survey.json` that follows a JSON Schema published by the profile
   (`mappings/survey-bundle.schema.json`). The profile's RML + SPARQL turn it into RDF. SciLEx
   adds no triple after the mapping, and the `describe_dataset` / `describe_subcorpora`
   post-processing of `build.py` goes away (ORSD D29, D30).
2. **Nothing is dropped; things are flagged.** Discarded papers are excluded members with their
   reason. Agreement copies become per-annotator codes on the original paper (D31, D33).
3. **Three disclosure levels.** *Public* (default for publishing), *team* and *full*. No secret at
   any level. Members are named publicly only with their consent (SR17, SR18, D36).
4. **Restorable.** A dump rebuilds the review: `kg_import.py` grows from "corpus only" to the
   whole record (SR19).

## Order of work

| Phase | Developments | Gives | Depends on (profile) |
|---|---|---|---|
| 0 | SX-12 (pin iteration 4, then 8), SX-23 | the declared interfaces; venue names and ISSNs in Zotero | iter4–iter8 release |
| 1 | SX-2, SX-1, SX-14, SX-22 | a bundle with the record files as they are (first section: `venues`), joined to citation keys, secret-free; a typed grid in the generated profile | bundle schema draft; iter6 grid declaration; iter7 `venues` |
| 2 | SX-3, SX-4, SX-5, SX-7, SX-8, SX-17 | data SciLEx loses today: discards, agreement results, decider, config and criteria versions, paper-type origin | — |
| 3 | SX-6, SX-16, SX-13 | disclosure levels, TriG output, no post-mapping triples | iter5 shapes per level, D34 |
| 4 | SX-9, SX-18, SX-19, SX-20, SX-21 | dated metrics, per-value enrichment provenance, query-level acquisition, history of codes | iter5 module `30-survey-record.ttl` |
| 5 | SX-10, SX-11, SX-15 | restore, stable IRIs, PRISMA parity | iter5 CQs (GCQ66–GCQ75) |

Phases 1–2 can start before the profile's iteration 5 is built. They only write files that SciLEx
itself can use (Overview, PRISMA, restore), so no work is lost if a decision changes.
