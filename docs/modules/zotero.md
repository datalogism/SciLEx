# Zotero

<img src="../_static/modules/zotero.png" alt="Zotero module" height="80">

Zotero is where a review's team reads, annotates and discusses the papers. SciLEx
gives each review its own Zotero group and keeps the two sides in sync, so every
decision SciLEx makes (screening, discards, types, metrics) is a Zotero tag the team
can see and edit, and every code annotators add in Zotero comes back to SciLEx.

| Sub-module | What it does |
|---|---|
| <a href="#zotero-group"><img src="../_static/modules/sub/zotero-group.png" height="30" alt="Zotero group"></a> | One dedicated group per review |
| <a href="#members"><img src="../_static/modules/sub/zotero-members.png" height="30" alt="Members"></a> | The people of the review |
| <a href="#sync"><img src="../_static/modules/sub/zotero-sync.png" height="30" alt="Sync"></a> | Two-way synchronisation, conflicts |
| <a href="#tag-conventions"><img src="../_static/modules/sub/zotero-tags.png" height="30" alt="Tag conventions"></a> | The tags SciLEx reads and writes |

## Zotero group

One **global access key** is set once in the [API keys](workspace.md#api-keys); the
user id is detected from it. Each review then gets its own **dedicated group**, chosen
among the groups the key reaches, on the review's **Zotero group** step (not when the
review is created). Optionally, the review uses one collection of the group (with or
without its sub-collections) instead of the whole library. The choice is saved in
`zotero_source.yml`; it is used by the sync, the push, ④ Annotate, the extensions and
the knowledge graph.

The page shows the group: name, description, link on zotero.org, id, type (private,
public closed or open membership), number of items and people, who can read and edit
the library and the files, dates, and whether your key can read and write it (a
read-only key makes pushes fail). A review on a personal library, or with no library,
is flagged on this page and on ⑤ Extend.

## Members

The group's owner, admins and members, completed by `members.yml`: names, ORCID iDs,
and people added by hand. **Find names in Zotero** reads the user names of the people
who edited the group's items. The same list is the annotators of
[④ Annotate](annotate.md#annotators), and Zotero contributors appear in the
[review card](overview.md#review-card).

## Sync

An icon at the top left of every review page shows the state at a glance: in sync,
Zotero has updates to get, SciLEx has changes to push, both, conflict, or not linked
yet (click to link). It checks every two minutes; a click opens the details and the
actions.

- **Linking** gives each row of `aggregated_results.csv` its Zotero item
  (`zotero_key` column), preferring items in the required sub-corpora, and takes the
  sub-corpora from the items' collections.
- **Baselines**: `zotero_sync_state.json` keeps, for every linked paper, the state of
  both sides at the last sync. A side changed a value when it differs from *its own*
  baseline, so a change is never attributed to the wrong side; the same value changed
  differently on both sides is a conflict you resolve.
- **Synced data**: bibliographic fields and tags. Tags merge as sets: what one side
  added or removed is added or removed on the other. Screening decisions travel as
  `SCREEN:` tags.
- **Cheap checks**: Zotero numbers every change of a library; a check asks only for the
  items changed since the last synced version.

Writes to one Zotero library (push, annotations, tag cleaning, sync) never run at the
same time.

## Tag conventions

| Tag | Meaning | Written by |
|---|---|---|
| `DIMENSION:value` | an annotation code of the grid (`DIMENSION:?` = to code) | annotators, ④ Annotate |
| `Collect_KW<n>:term`, `BK:term` | search and bonus keywords found | ② Collect, ⑥ Enrich |
| `SCREEN:Include` / `Exclude` / `Maybe` | screening decision | ③ Screen |
| `PAPER_TYPE:<type>` | Benchmark, Review or State of the art, Dataset, Model or Method | ⑥ Enrich, people |
| `ANNOT:<id>` | assigned to an annotator | ④ Annotate |
| `ANNOT_VALID_BY:<id>` | annotation validated against the grid | Explore, people |
| `DELETED_BY:<who>` | discarded from the analyses (`filter:<reason>` for a rule) | Explore, Criteria, Consolidate |
| `KEEP:<criterion>` | exception to an eligibility criterion | people |
| `AGREEMENT_COPY:<key>` | an annotator's blind copy of a paper | ④ Annotate |
| `CITATIONS:10^n`, `PAGERANK:top5%`… | citation metrics | ⑥ Enrich |

`<id>` is an ORCID iD when known, else the Zotero user name. Only `DIMENSION:value`
tags of the grid count as annotation codes; the others are workflow or automation tags.
See the [tag reference](../reference/tags.md).
