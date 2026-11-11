# ② Collect

<img src="../_static/modules/collect.png" alt="Collect module" height="80">

Collect queries the academic APIs of `scilex.yml`, then aggregates the answers:
deduplication, filtering and ranking. It is the first step of a review started from
scratch. Once the review has papers, the step leaves the sidebar and lives in
[⑤ Extend → New collect](extend.md#new-collect).

| Sub-module | What it does |
|---|---|
| <a href="#collection"><img src="../_static/modules/sub/collect-collection.png" height="30" alt="Collection"></a> | Parallel queries: keywords × years × APIs |
| <a href="#aggregation"><img src="../_static/modules/sub/collect-aggregation.png" height="30" alt="Aggregation"></a> | Unified format, deduplication, citations |
| <a href="#filtering-pipeline"><img src="../_static/modules/sub/collect-filtering.png" height="30" alt="Filtering pipeline"></a> | Five filtering phases and relevance ranking |

## Collection

One query per keyword combination, year and API, run in parallel with per-API rate
limiting, key rotation, a circuit breaker for failing APIs and, optionally,
[VPN rotation](configure.md#vpn-rotation). Collections are idempotent: a query already
done is skipped, so an interrupted collection resumes where it stopped.

**In the app.** Check the summary line (APIs, years, keyword groups), then click
**Run**. A table shows each API's progress, papers, errors and state; the aggregation
steps follow. **Only papers since** (YYYY-MM-DD) collects recent papers only.
**Resume interrupted collection** continues a stopped one; **Aggregate existing
results** aggregates what a stopped collection already fetched. **Cancel** stops the
collection at the next query (the aggregation cannot be interrupted). At the end, a
summary (collected, after deduplication, kept) and the PRISMA and aggregation reports
are shown.

**Command line.**

```bash
scilex-collect                       # in the folder holding scilex.yml
scilex-collect --resume NAME         # continue a run
scilex-collect --since 2026-01-01    # incremental collection
python -m scilex status              # completeness: keywords, APIs, years
```

Supported APIs: Semantic Scholar, OpenAlex, IEEE, arXiv, bioRxiv, Springer, Elsevier,
PubMed, PubMed Central, HAL, DBLP, ISTEX, OpenAIRE and ORKG. See the
[API comparison](../reference/api-comparison.md).

## Aggregation

The raw answers are converted to one Zotero-shaped format, then deduplicated by DOI and
by normalised title, keeping the most complete record and the list of APIs that found
it. Missing abstracts are fetched, citation counts are looked up (Crossref,
OpenCitations, OpenAlex, Semantic Scholar, with a SQLite cache), and optional steps
add CORE/SJR venue ranks, open access (Unpaywall) and an LLM relevance score.

```bash
scilex-aggregate                         # --skip-citations, --workers N
scilex-aggregate --collection NAME --use-current-config
```

Results go to `<folder>/output/<name>/aggregated_results.csv` (with
`filtering_summary.json` and `aggregation_stats.csv`), the same from the app and the
command line.

## Filtering pipeline

1. **Item type** — whitelist of publication types (`always_keep` types skip the quality
   rules).
2. **Quality** — required DOI, abstract, year, minimum number of authors, open access.
3. **Abstract quality** — placeholder or too-short abstracts are removed.
4. **Citations** — time-aware thresholds (e.g. ≥1 citation after 18 months, ≥10 after
   3 years).
5. **Relevance ranking** — a 0–10 score from keyword density, metadata completeness,
   venue type and citation impact; the top `ranking.max_papers` are kept.

Each phase's count is reported in the PRISMA flow of the [Overview](overview.md). See
the [advanced filtering guide](../user-guides/advanced-filtering.md).
