# Tag reference

SciLEx stores every per-paper state that a team needs to see as a **Zotero tag**, so it
is visible and editable in Zotero and round-trips through the
[sync](../modules/zotero.md#sync). In `aggregated_results.csv`, tags are the `;`-separated
`tags` and `collect_keywords` columns.

## Annotation codes

| Tag | Meaning |
|---|---|
| `DIMENSION:value` | a code of the annotation grid (`SAT_TASK:RelationExtraction`) |
| `DIMENSION:?` | placeholder: the dimension is still to code |
| `DIMENSION-AUTO:value` | an LLM annotator's proposal, to validate by a person ([④ Annotate → Validate](../modules/annotate.md#validate-llm-proposals)); never a code |

The grid (`annotation_grid.csv`) lists the dimensions. Values are normalised when the
grid is applied (`DIMENSION:DeepLearning`). Only these tags count as codes in the
Overview, the [Annotations analysis](../modules/analyses.md#annotations), the agreement
study and the knowledge graph.

## Workflow tags

Defined in `scilex/review_tags.py`. `<id>` is an ORCID iD (`0000-0002-1825-0097`) when
known, else a Zotero user name.

| Tag | Meaning | Set by |
|---|---|---|
| `ANNOT:<id>` | the paper is assigned to annotator `<id>` | [④ Annotate → Assign](../modules/annotate.md#annotators) |
| `ANNOT_VALID_BY:<id>` | annotation complete against the grid, validated by `<id>` | Explore notice, people in Zotero |
| `DELETED_BY:<id>` | discarded by a person: kept in the corpus, left out of the analyses | Explore notice |
| `DELETED_BY:filter:<reason>` | discarded by a rule | [Eligibility criteria](../modules/criteria.md) (`filter:<C> <cause>`), [Consolidate](../modules/consolidate.md#filters) |
| `KEEP:<criterion>` | exception to an eligibility criterion (`KEEP:C1`) | people, criteria panel |
| `AGREEMENT_COPY:<key>` | an annotator's blind copy of paper `<key>` | [agreement study](../modules/annotate.md#agreement-study) |

Discarded papers (`DELETED_BY:`) are left out of every analysis, the Overview counts and
charts, the citation metrics and the knowledge graph; agreement copies are never papers
of the review.

## Automation tags

Written by SciLEx itself; never counted as annotation codes.

| Tag | Meaning | Set by |
|---|---|---|
| `Collect_KW<n>:term` | search keyword of group *n* found / used | ② Collect, [⑥ Enrich → Search keywords](../modules/enrich.md#search-keywords) |
| `BK:term` | bonus keyword found | same |
| `SCREEN:Include`, `SCREEN:Exclude`, `SCREEN:Maybe` | screening decision | [③ Screen](../modules/screen.md) via the sync |
| `PAPER_TYPE:<type>` | Benchmark, Review or State of the art, Dataset, Model or Method | [⑥ Enrich → Paper types](../modules/enrich.md#paper-types) (people may change it) |
| `CITATIONS:10^n`, `REFERENCES:10^n`, `CITATIONS_PER_YEAR:10^n`, `CITED_IN_CORPUS:10^n` | orders of magnitude (`10^2` = 100–999) | [⑥ Enrich → Citation metrics](../modules/enrich.md#citation-metrics) |
| `PAGERANK:top1%` / `top5%` / `top10%` / `top25%` / `other` | PageRank in the review's citation graph | same |
| `QUALITY:<tens>`, `VENUE_RANK:<rank>` | metadata quality score, CORE/SJR venue rank | same |
| `QUALI_SCORE:`, `REL_SCORE:`, `CITAT:`, `HavePDF`, `HavePWC`, `HaveGithub`, `SciLexCollected` | scores and presence flags written by earlier SciLEx pushes | read by the knowledge graph (declared in each collection profile) |

Metric tags are replaced at each computation; other tags are left alone.
