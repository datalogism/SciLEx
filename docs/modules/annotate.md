# ④ Annotate

<img src="../_static/modules/annotate.png" alt="Annotate module" height="80">

Annotate prepares and follows the manual coding of the papers, done by a team in the
review's [Zotero group](zotero.md#zotero-group). Codes are Zotero tags of the form
`DIMENSION:value`; SciLEx never asks annotators to leave Zotero.

| Sub-module | What it does |
|---|---|
| <a href="#annotation-grid"><img src="../_static/modules/sub/annotate-grid.png" height="30" alt="Annotation grid"></a> | Dimensions, questions, paper types; apply in Zotero |
| <a href="#annotators"><img src="../_static/modules/sub/annotate-annotators.png" height="30" alt="Annotators"></a> | Members, balanced assignment, progress |
| <a href="#workflow-tags"><img src="../_static/modules/sub/annotate-workflow-tags.png" height="30" alt="Workflow tags"></a> | Assigned, validated, discarded |
| <a href="#agreement-study"><img src="../_static/modules/sub/annotate-agreement.png" height="30" alt="Agreement study"></a> | Blind copies, Krippendorff's alpha, merge |
| <a href="#annotation-report"><img src="../_static/modules/sub/annotate-report.png" height="30" alt="Annotation report"></a> | Counts by dimension, tags, editors |

## Annotation grid

One row per dimension (`SAT_TASK`, `SAT_DATASET`…), the question annotators answer, and
the paper types it applies to (datasets, surveys, models). Start from the SciLEx grid,
import a CSV (a `tag` column, and `X` in the type columns), or **Deduce from Zotero
annotations** (the `DIMENSION:value` tags of the chosen collection). Saved as
`annotation_grid.csv` in the review folder; it also defines the coding dimensions of
the [knowledge graph](export.md#knowledge-graph).

**Add the grid to the Zotero papers**: choose the collection and the dimensions (all, or
those of one paper type), click **Preview changes**, then **Apply in Zotero**. Each
paper gets `DIMENSION:?` for every dimension it has no value for, and existing values
are normalised (`DIMENSION:DeepLearning`). Other tags are kept unless you untick the
option. A paper edited in Zotero between preview and apply is skipped: preview again.

## Annotators

**Find in Zotero** lists the members of the review's group (owner, admins, members,
and everyone who edited its items), kept in `members.yml`; add each person's ORCID iD,
or add people by hand. **Assign** spreads the papers over the chosen annotators with
balanced loads (all papers or one sub-corpus, 1 to 5 annotators per paper, only papers
not assigned yet), as `ANNOT:<id>` tags. **Progress** counts, per annotator, the papers
assigned, validated and discarded. `<id>` is the ORCID iD, else the Zotero user name.

## Workflow tags

Shared with Zotero by the [sync](zotero.md#sync):

- `ANNOT:<id>` — assigned to annotator `<id>`;
- `ANNOT_VALID_BY:<id>` — annotation complete against the grid, validated by `<id>`;
- `DELETED_BY:<who>` — discarded: kept in the corpus but left out of the analyses,
  counts and charts (`DELETED_BY:filter:<reason>` when a rule did it).

The notice of [Explore](explore.md#paper-notice) has **Validated by me** and **Discard**
with your ORCID iD; Screen and Explore filter on annotation status, annotator and
validator. These tags never count as annotation dimensions. See all
[tag conventions](../reference/tags.md).

## Agreement study

Papers assigned to two annotators or more are copied, by **Create annotator copies**,
into the Zotero collection `agreement/<annotator>` of each of them: same bibliographic
data and `DIMENSION:?` placeholders but no codes (blind annotation), plus `ANNOT:<id>`
and `AGREEMENT_COPY:<key of the paper>`. Copies are never taken for papers of the
review.

Once the copies are coded, **Compute agreement** gives Krippendorff's alpha with the
MASI distance per dimension (≥ 0.8 good, ≥ 0.667 tentative, ≥ 0.4 moderate, ≥ 0.2 fair,
below poor). **Merge into the papers** writes on each paper the codes every annotator
gave (and, ticked, those a majority gave), removing the placeholders of the dimensions
now coded; the other codes are listed to adjudicate.

## Annotation report

Counts the annotation tags by dimension, the most used tags, and who last edited each
paper; the tables are also written to `output/<name>/annotations/`. Same as
`python -m scilex.report_annotations`. Each report records a snapshot of the
[annotation history](overview.md#review-card). The deeper analysis of the codes
(coverage, crossings, merges) is the [Annotations analysis](analyses.md#annotations).
