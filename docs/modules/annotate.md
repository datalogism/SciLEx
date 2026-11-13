# ④ Annotate

<img src="../_static/modules/annotate.png" alt="Annotate module" height="80">

Annotate prepares and follows the manual coding of the papers, done by a team in the
review's [Zotero group](zotero.md#zotero-group). Codes are Zotero tags of the form
`DIMENSION:value`; SciLEx never asks annotators to leave Zotero.

The screen is an annotation manager in five tabs: **Parameters** (the grid and its
guideline), **Team** (the annotators), **Campaigns** (who annotates which collection,
people and LLM annotators), **Validate** (the LLM proposals) and **Progress &
agreement** (campaign progress, LLM agreement, the agreement study and the report).

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

## Annotation guideline

`annotation_guideline.md` in the review folder (Parameters tab): the Markdown manual that
goes with the grid. A `## DIMENSION` section whose heading is a dimension of the grid is
the guidance for that dimension (shown next to its question, and sent with it to the LLM
annotators); the rest is the general part. Same layout as SciLEx Annotator's guideline.

## Annotators

**Find in Zotero** lists the members of the review's group (owner, admins, members,
and everyone who edited its items), kept in `members.yml`; add each person's ORCID iD,
or add people by hand. **Assign** spreads the papers over the chosen annotators with
balanced loads (all papers or one sub-corpus, 1 to 5 annotators per paper, only papers
not assigned yet), as `ANNOT:<id>` tags. **Progress** counts, per annotator, the papers
assigned, validated and discarded. `<id>` is the ORCID iD, else the Zotero user name.
**Named in public dumps** records that a person agrees to appear, with their ORCID iD,
in a knowledge graph exported at the public level ([⑧ Export](export.md#survey-bundle)).

## Campaigns

A campaign is one Zotero collection of the review (usually a screened collection, e.g.
`datasets`), the paper type whose grid dimensions apply, its human annotators and how
many annotate each paper (2 or more = cross-annotation, measured by the
[agreement study](#agreement-study)), and its LLM annotators. A review can have several
campaigns; they are kept in `campaigns.yml`. **Assign papers** previews then writes the
`ANNOT:<id>` tags of the campaign with balanced loads.

**Run LLM annotators** sends the campaign (grid, guideline, paper type, papers as
BibTeX) to the SciLEx Annotator (`scilex-annotator api`)
service, a separate program. Its address is set under **LLM annotator service (SciLEx
Annotator)** at the top of the Campaigns tab (collapsed by default) and saved in the
review's `campaigns.yml`. SciLEx itself listens on port 8000, so start the service on
another port (`scilex-annotator api --port 8001`) and set the address to
`http://127.0.0.1:8001`. Its token is a key
(`LmmAnnotator: {token: …}` in `keys.yml`, or `$SCILEX_ANNOTATOR_TOKEN`) and is never
written in the review. Human first: a model only writes `DIMENSION-AUTO:value` on the
dimensions still `DIMENSION:?` or missing; on dimensions a person coded its answer is
kept locally only. Only the dimensions the service accepts are sent: it never asks the
screening tags (`SCREEN`, `EXCLUSION`, `INCLUSION_EXCEPTION`), and decision models such
as GLiNER2 answer only dimensions with a closed list of values. Answers are imported
as they arrive: the run card shows *N of M questions answered, P proposals imported*.
Every answer (values, evidence, confidence) is kept in
`annotations/llm/<campaign>.jsonl`. Setup, models and troubleshooting are documented in
SciLEx Annotator's `docs/scilex-integration.md`.

## Validate LLM proposals

The list follows a running LLM campaign: new proposals appear on their own within a few
seconds, without leaving the page you are on or losing a correction being typed.
Each `DIMENSION-AUTO:value` proposal is shown with the model's rationale and verbatim
evidence: **Accept** or **Correct** writes your `DIMENSION:value` code, **Reject** keeps
`DIMENSION:?`; either way the `-AUTO` tag is removed and the decision is logged in
`annotations/llm/decisions.jsonl`. You can also do it in Zotero (replace `DIMENSION:?`
with your code and delete the `-AUTO` tag), then **Check Zotero edits** after a sync.
`-AUTO` tags never count as codes. **Progress & agreement** compares each model with
the human codes.

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
