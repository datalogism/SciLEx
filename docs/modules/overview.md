# Overview

<img src="../_static/modules/overview.png" alt="Overview module" height="80">

Opening a review shows its **Overview** first: a visual summary of its state built from
what the review already records, without any network access.

| Sub-module | What it does |
|---|---|
| <a href="#prisma-flow"><img src="../_static/modules/sub/overview-prisma.png" height="30" alt="PRISMA flow"></a> | Flow diagram from identification to inclusion |
| <a href="#review-card"><img src="../_static/modules/sub/overview-review-card.png" height="30" alt="Review card"></a> | Origin, extensions, enrichments, annotation, contributors |
| <a href="#history"><img src="../_static/modules/sub/overview-history.png" height="30" alt="History"></a> | Every event of the review, by whom |
| <a href="#things-to-check"><img src="../_static/modules/sub/overview-checks.png" height="30" alt="Things to check"></a> | Inconsistencies, each with its fix |

Above them, key figures (papers, Zotero collections, share screened, annotation
state) and charts: papers per year, per source, per collection and per
[paper type](enrich.md#paper-types), screening decisions, papers enriched per source,
papers coded per dimension. Papers discarded with a `DELETED_BY:` tag are left out of
the counts and charts.

## Review workflow

The Overview opens on a map of the review: the ten steps as cards in two rows (①
Configure to ④ Annotate, then ⑤ Extend to ⑧ Export), with how far each one is (a bar
coloured green from 75 %, amber from 40 %, red below), the three loops back in blue
(new papers to screen after an extension, metrics for the criteria after Enrich,
suggested keywords after Analyses) and what applies at every step (Zotero sync,
journal, ORCID attribution, tags). Select a step to see where it stands, what is
left to do, and a button to open it. Progress is read from the results, the
criteria, the screening decisions, the annotation tags and the journal.

## PRISMA flow

The PRISMA flow is drawn first as a **funnel**: identified, in the corpus (after
duplicates and filters), eligible (after the criteria and people's discards),
screened, included, with what was lost at each stage and why beside it. Switch to
**Diagram** for the [PRISMA](https://www.prisma-statement.org/) flow diagram:

- **Identification**: the collect of `scilex.yml` (APIs, keywords, years) and its raw
  count, plus the records from other sources: each extension (new collect,
  snowballing, BibTeX, Zotero);
- **Screening**: duplicates and each automatic filter of the aggregation, the papers
  discarded by an [eligibility criterion](criteria.md) (one line per criterion) or a
  person (`DELETED_BY:` tags), and the screening decisions;
- **Included**: the papers included in ③ Screen, and those still to screen;
- **Enrichment**: the enrichments run on the corpus, beside the flow.

**Export** draws the flow as a PRISMA-style figure, `prisma_flow.svg` and
`prisma_flow.png`, plus the funnel `prisma_flow_funnel.svg`, written to the collection folder and downloaded, ready for the
methods section of the paper.

## Review card

From the workflow journal:

- **origin**: SciLEx collection (keywords, years, sources, fingerprint of the
  configuration), Zotero import, knowledge-graph or BibTeX import, or empty review;
  when and by whom it was created;
- **extensions**: each one with who, when and the papers added;
- **enrichments**: each run with who, when and the papers updated (the columns it
  filled, compared with the previous run);
- **annotation**: annotated papers and codes now and at the first record, with a chart
  over time; papers validated against the grid (`ANNOT_VALID_BY:<id>`) are counted
  apart;
- **contributors**: SciLEx users (ORCID iD and name) and Zotero users who added or
  modified items of the review's library — group annotators appear even if they never
  used SciLEx.

**Annotation history.** Zotero keeps no history of tags, so SciLEx records a snapshot
each time it reads the annotations: Zotero import, annotation report, knowledge-graph
export. They are kept in `annotation_history.jsonl` and drawn as a chart.

## History

Every action on the review is recorded in `workflow.jsonl` (review folder), one line
per event, never rewritten: creation and imports (with the Zotero library and its
version), each save of `scilex.yml` (with its SHA-256 fingerprint), renames, changes of
Zotero library, every job that finished or failed, consolidations, classifications,
criteria applied, and exports (with the version of the scilex-lpwc-ap profile for a
knowledge graph). Each event names its agent (your ORCID iD), what it used and what it
produced; API keys are never written. When a review gets its journal, the past is
reconstructed once from the files that exist (marked *reconstructed*, agent *unknown
(before tracking)*). The **History** card lists the events, most recent first.

The journal is designed to map to PROV-O; see the
[provenance proposal](../kg/provenance-proposal.md).

## Things to check

On opening, the Overview compares the review with its journal and lists what looks
inconsistent, each with its fix:

- results found in another folder named after the review (**Use this folder**);
- a Zotero library other than the one the papers came from;
- a collection that stopped before the end (resume it in [② Collect](collect.md));
- papers in none of the required sub-corpora (classify them in
  [Consolidate](consolidate.md#sub-corpora)).

A review without a dedicated Zotero group says so on ⑤ Extend and on its
[Zotero group](zotero.md#zotero-group) page.
