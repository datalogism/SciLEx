"""Aggregation report (Markdown + CSV) written at the end of a pipeline run."""

import csv
import logging
import os

import pandas as pd

from scilex.constants import is_valid, parse_archive_apis


def collection_warning(dir_collect, main_config) -> list[str]:
    """Markdown lines warning that the collection is incomplete (empty if complete).

    Reports built from a partial collection must say so: the counts of a
    PRISMA flow are only meaningful when every query finished.
    """
    try:
        from scilex.collect_status import build_status

        status = build_status(dir_collect, main_config)
    except Exception as e:
        logging.warning(f"Could not check collection completeness: {e}")
        return []
    totals = status["totals"]
    if totals["total"] == 0 or totals["done"] == totals["total"]:
        return []
    incomplete = [
        f"{api} ({counts['done']}/{counts['total']})"
        for api, counts in status["apis"].items()
        if counts["done"] < counts["total"]
    ]
    return [
        f"> **Warning — partial collection:** {totals['done']} of {totals['total']} "
        f"queries completed. Incomplete APIs: {', '.join(incomplete)}. "
        "Run the collection again to resume the missing queries.",
        "",
    ]


def write_aggregation_report(
    dir_collect,
    collect_name,
    run_date,
    duration_seconds,
    main_config,
    parallel_stats,
    filtering_tracker,
    citation_stats,
    url_stats,
    df_clean,
    collection_warning_lines=(),
):
    """Write aggregation report (Markdown + CSV) to dir_collect."""
    flat_stats = {}

    # --- Identity ---
    flat_stats["collect_name"] = collect_name
    flat_stats["run_date"] = run_date.strftime("%Y-%m-%d %H:%M:%S")
    flat_stats["duration_seconds"] = round(duration_seconds, 1)
    flat_stats["apis"] = ";".join(main_config.get("apis", []))
    flat_stats["years"] = ";".join(str(y) for y in main_config.get("years", []))

    # --- Loading ---
    ls = parallel_stats.get("loading", {})
    flat_stats["files_loaded"] = ls.get("files_loaded", 0)
    flat_stats["papers_loaded"] = ls.get("total_papers", 0)
    flat_stats["load_time_seconds"] = round(ls.get("elapsed_seconds", 0), 1)

    # --- Text filter ---
    ps = parallel_stats.get("processing", {})
    flat_stats["papers_after_text_filter"] = ps.get("papers_filtered", 0)
    flat_stats["papers_rejected_text"] = ps.get("papers_rejected", 0)

    # --- Dedup ---
    ds = parallel_stats.get("deduplication", {})
    flat_stats["papers_after_dedup"] = ds.get("final_count", 0)
    flat_stats["doi_duplicates_removed"] = ds.get("doi_removed", 0)
    flat_stats["title_duplicates_removed"] = ds.get("title_removed", 0)

    # --- Filtering stages ---
    flat_stats["papers_initial_post_dedup"] = filtering_tracker.initial_count
    flat_stats["papers_final"] = (
        filtering_tracker.stages[-1]["papers"]
        if filtering_tracker.stages
        else len(df_clean)
    )

    # --- URL fallback ---
    flat_stats["urls_filled_from_doi"] = url_stats.get("filled", 0)
    flat_stats["urls_already_valid"] = url_stats.get("already_valid", 0)

    # --- Citation fetching ---
    if citation_stats:
        for key, val in citation_stats.items():
            flat_stats[f"citation_{key}"] = val
        cache_total = citation_stats.get("cache_hit", 0) + citation_stats.get(
            "cache_miss", 0
        )
        flat_stats["citation_cache_hit_rate_pct"] = (
            round(citation_stats.get("cache_hit", 0) / cache_total * 100, 1)
            if cache_total > 0
            else 0.0
        )

    # --- Output quality ---
    flat_stats["papers_output"] = len(df_clean)
    if "DOI" in df_clean.columns:
        flat_stats["papers_with_doi"] = int(df_clean["DOI"].apply(is_valid).sum())
    if "abstract" in df_clean.columns:
        flat_stats["papers_with_abstract"] = int(
            df_clean["abstract"].apply(is_valid).sum()
        )
    if "relevance_score" in df_clean.columns:
        flat_stats["relevance_score_mean"] = round(
            float(df_clean["relevance_score"].mean()), 2
        )
        flat_stats["relevance_score_min"] = round(
            float(df_clean["relevance_score"].min()), 2
        )
        flat_stats["relevance_score_max"] = round(
            float(df_clean["relevance_score"].max()), 2
        )
        flat_stats["relevance_score_median"] = round(
            float(df_clean["relevance_score"].median()), 2
        )
    if "nb_citation" in df_clean.columns:
        nb_cit = pd.to_numeric(df_clean["nb_citation"], errors="coerce").fillna(0)
        flat_stats["avg_citations"] = (
            round(float(nb_cit.mean()), 1) if len(nb_cit) else 0.0
        )
        flat_stats["max_citations"] = int(nb_cit.max()) if len(nb_cit) else 0

    # =========================================================================
    # Write CSV (flat key-value)
    # =========================================================================
    csv_path = os.path.join(dir_collect, "aggregation_stats.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["stat", "value"])
        for key, val in flat_stats.items():
            writer.writerow([key, val])

    # =========================================================================
    # Build Markdown
    # =========================================================================
    apis = main_config.get("apis", [])
    years = main_config.get("years", [])
    keywords = main_config.get("keywords", [])
    bonus_keywords = main_config.get("bonus_keywords") or []

    md = []
    md.append(f"# Aggregation Report — {collect_name}")
    md.append("")
    md.append(f"**Date:** {run_date.strftime('%Y-%m-%d %H:%M:%S')}  ")
    md.append(
        f"**Duration:** {duration_seconds:.1f} s ({duration_seconds / 60:.1f} min)  "
    )
    md.append("")
    md.extend(collection_warning_lines)

    # --- Configuration ---
    md.append("## Configuration")
    md.append("")
    md.append("| Setting | Value |")
    md.append("|---------|-------|")
    md.append(f"| APIs | {', '.join(apis)} |")
    md.append(f"| Years | {', '.join(str(y) for y in years)} |")
    if isinstance(keywords, list) and keywords:
        if isinstance(keywords[0], list):
            for i, group in enumerate(keywords):
                md.append(f"| Keyword Group {i + 1} | {', '.join(group)} |")
        else:
            md.append(f"| Keywords | {', '.join(str(k) for k in keywords)} |")
    if bonus_keywords:
        md.append(f"| Bonus Keywords | {', '.join(bonus_keywords)} |")
    md.append("")

    # --- Collection loading ---
    md.append("## Collection Loading")
    md.append("")
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append(f"| JSON files loaded | {ls.get('files_loaded', 0):,} |")
    md.append(f"| Papers loaded | {ls.get('total_papers', 0):,} |")
    md.append(f"| Load time | {ls.get('elapsed_seconds', 0):.1f} s |")
    md.append(
        f"| Papers after text filter | {ps.get('papers_filtered', 0):,} "
        f"({(1 - ps.get('rejection_rate', 0)) * 100:.1f}% pass rate) |"
    )
    md.append(f"| DOI duplicates removed | {ds.get('doi_removed', 0):,} |")
    md.append(f"| Title duplicates removed | {ds.get('title_removed', 0):,} |")
    md.append(f"| Papers after deduplication | {ds.get('final_count', 0):,} |")
    md.append("")

    # --- Filtering pipeline ---
    md.append("## Filtering Pipeline")
    md.append("")
    if filtering_tracker.stages:
        initial = filtering_tracker.initial_count
        md.append(
            "| Stage | Description | Papers | Removed | Stage Rate | Cumulative Removed |"
        )
        md.append(
            "|-------|-------------|--------|---------|------------|-------------------|"
        )
        for info in filtering_tracker.stages:
            cum_removed = initial - info["papers"]
            cum_rate = (cum_removed / initial * 100) if initial > 0 else 0.0
            desc = (
                info["description"][:60] + "…"
                if len(info["description"]) > 60
                else info["description"]
            )
            md.append(
                f"| {info['stage']} | {desc} | {info['papers']:,} | "
                f"{info['removed']:,} | {info['removal_rate']:.1f}% | "
                f"{cum_removed:,} ({cum_rate:.1f}%) |"
            )
    md.append("")

    # --- API coverage ---
    md.append("## API Coverage (Final Output)")
    md.append("")
    if "archive" in df_clean.columns:
        api_counts: dict[str, int] = {}
        for archive_value in df_clean["archive"]:
            for api in parse_archive_apis(archive_value):
                api_counts[api] = api_counts.get(api, 0) + 1
        if api_counts:
            md.append("| API | Papers in Final Output |")
            md.append("|-----|----------------------|")
            for api_name, count in sorted(
                api_counts.items(), key=lambda x: x[1], reverse=True
            ):
                md.append(f"| {api_name} | {count:,} |")
    md.append("")

    # --- Citation fetching ---
    if citation_stats:
        cs = citation_stats
        cache_total = cs.get("cache_hit", 0) + cs.get("cache_miss", 0)
        hit_rate = (
            (cs.get("cache_hit", 0) / cache_total * 100) if cache_total > 0 else 0.0
        )

        md.append("## Citation Fetching")
        md.append("")
        md.append("| Metric | Count |")
        md.append("|--------|-------|")
        md.append(f"| Successful | {cs.get('success', 0):,} |")
        md.append(f"| Errors | {cs.get('error', 0):,} |")
        md.append(f"| Timeouts | {cs.get('timeout', 0):,} |")
        md.append(f"| Without DOI (bypassed) | {cs.get('no_doi', 0):,} |")
        md.append(
            f"| Cache hits | {cs.get('cache_hit', 0):,} ({hit_rate:.1f}% hit rate) |"
        )
        md.append(f"| Semantic Scholar (in-memory) | {cs.get('ss_used', 0):,} |")
        md.append(f"| OpenAlex (in-memory) | {cs.get('oa_used', 0):,} |")
        md.append(f"| CrossRef batch API | {cs.get('cr_used', 0):,} |")
        md.append(f"| OpenCitations API | {cs.get('opencitations_used', 0):,} |")
        md.append("")

    # --- URL fallback ---
    md.append("## URL Enrichment")
    md.append("")
    md.append("| Metric | Count |")
    md.append("|--------|-------|")
    md.append(f"| URLs generated from DOI | {url_stats.get('filled', 0):,} |")
    md.append(f"| URLs already present | {url_stats.get('already_valid', 0):,} |")
    md.append(f"| No DOI available | {url_stats.get('no_doi', 0):,} |")
    md.append("")

    # --- Output quality ---
    md.append("## Output Quality Metrics")
    md.append("")
    n = len(df_clean)
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append(f"| Total papers output | {n:,} |")
    if "DOI" in df_clean.columns:
        doi_count = int(df_clean["DOI"].apply(is_valid).sum())
        md.append(
            f"| Papers with DOI | {doi_count:,} ({(doi_count / n * 100) if n else 0.0:.1f}%) |"
        )
    if "abstract" in df_clean.columns:
        abs_count = int(df_clean["abstract"].apply(is_valid).sum())
        md.append(
            f"| Papers with abstract | {abs_count:,} ({(abs_count / n * 100) if n else 0.0:.1f}%) |"
        )
    if "relevance_score" in df_clean.columns:
        md.append(
            f"| Relevance score — mean | {df_clean['relevance_score'].mean():.2f} |"
        )
        md.append(
            f"| Relevance score — median | {df_clean['relevance_score'].median():.2f} |"
        )
        md.append(
            f"| Relevance score — min | {df_clean['relevance_score'].min():.2f} |"
        )
        md.append(
            f"| Relevance score — max | {df_clean['relevance_score'].max():.2f} |"
        )
    if "nb_citation" in df_clean.columns:
        nb_cit = pd.to_numeric(df_clean["nb_citation"], errors="coerce").fillna(0)
        avg_cit = nb_cit.mean() if len(nb_cit) else 0.0
        max_cit = int(nb_cit.max()) if len(nb_cit) else 0
        md.append(f"| Avg citations per paper | {avg_cit:.1f} |")
        md.append(f"| Max citations | {max_cit:,} |")
    md.append("")
    md.append(
        f"*Report generated by SciLEx `aggregate_collect` — {run_date.strftime('%Y-%m-%d %H:%M:%S')}*"
    )

    md_path = os.path.join(dir_collect, "aggregation_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    logging.info(f"Aggregation report written → {md_path}")
    logging.info(f"Aggregation stats written  → {csv_path}")

    return md_path, csv_path


# ---------------------------------------------------------------------------
# PRISMA 2020 report
# ---------------------------------------------------------------------------

_PRISMA_REASONS = {
    "ItemType Filter": "publication type not in the allowed list",
    "Quality Filter": "failed quality requirements (DOI, abstract, year, authors...)",
    "Abstract Quality Filter": "abstract below the quality threshold",
    "Since Filter": "published before the `since` date",
    "Citation Filter": "below the time-aware citation threshold",
    "Relevance Ranking": "outside the top-N by relevance score",
}
# Stages that only split the data set: they do not exclude anything by themselves.
_PRISMA_NON_EXCLUDING_STAGES = {"ItemType Bypass Split"}


def compute_prisma_screening_steps(filtering_tracker) -> list[dict]:
    """Derive per-filter exclusions from the FilteringTracker stages.

    The tracker records the paper count after every stage; the bypass split stage is
    skipped because bypassed papers are merged back before the next stage.

    Returns:
        List of ``{"stage", "reason", "excluded", "remaining"}`` dicts.
    """
    steps = []
    previous = filtering_tracker.initial_count
    for info in filtering_tracker.stages[1:]:
        if info["stage"] in _PRISMA_NON_EXCLUDING_STAGES:
            continue
        steps.append(
            {
                "stage": info["stage"],
                "reason": _PRISMA_REASONS.get(info["stage"], info["description"]),
                "excluded": max(previous - info["papers"], 0),
                "remaining": info["papers"],
            }
        )
        previous = info["papers"]
    return steps


def build_prisma_report(
    collect_name,
    run_date,
    parallel_stats,
    filtering_tracker,
    final_count,
    collection_warning_lines=(),
) -> str:
    """Build the PRISMA 2020 Markdown report (tables + Mermaid flow diagram)."""
    loading = parallel_stats.get("loading", {})
    processing = parallel_stats.get("processing", {})
    dedup = parallel_stats.get("deduplication", {})

    per_api = loading.get("per_api", {})
    identified = loading.get("total_papers", 0)
    prescreen_excluded = processing.get("papers_rejected", 0)
    duplicates = dedup.get("total_removed", 0)
    screened = filtering_tracker.initial_count
    steps = compute_prisma_screening_steps(filtering_tracker)

    md = [
        f"# PRISMA Report — {collect_name}",
        "",
        f"**Date:** {run_date.strftime('%Y-%m-%d %H:%M:%S')}  ",
        "Flow of records following the PRISMA 2020 statement.",
        "",
        *collection_warning_lines,
        "## Identification",
        "",
        "| Source | Records identified |",
        "|--------|--------------------|",
    ]
    md.extend(f"| {api} | {count:,} |" for api, count in sorted(per_api.items()))
    md.append(f"| **Total** | **{identified:,}** |")
    md += [
        "",
        "| Step | Records removed | Reason |",
        "|------|-----------------|--------|",
        f"| Automated pre-screening | {prescreen_excluded:,} | "
        "outside year range / publication type / keyword filter |",
        f"| Deduplication | {duplicates:,} | duplicate DOI or title |",
        "",
        "## Screening",
        "",
        f"Records screened: **{screened:,}**",
        "",
        "| Filter | Excluded | Remaining | Reason |",
        "|--------|----------|-----------|--------|",
    ]
    md.extend(
        f"| {s['stage']} | {s['excluded']:,} | {s['remaining']:,} | {s['reason']} |"
        for s in steps
    )
    md += [
        "",
        "## Included",
        "",
        f"Records included in the final collection: **{final_count:,}**",
        "",
        "## Flow diagram",
        "",
        "```mermaid",
        "flowchart TD",
        '    subgraph Identification["Identification"]',
        f'        A["Records identified from databases<br/>n = {identified:,}"]',
        f'        B["Records removed before screening<br/>Pre-screening: n = {prescreen_excluded:,}<br/>'
        f'Duplicates: n = {duplicates:,}"]',
        "    end",
        '    subgraph Screening["Screening"]',
        f'        C["Records screened<br/>n = {screened:,}"]',
    ]
    previous_node = "C"
    for index, step in enumerate(steps):
        node = f"S{index}"
        excluded_node = f"X{index}"
        md.append(
            f'        {excluded_node}["Excluded: {step["stage"]}<br/>n = {step["excluded"]:,}"]'
        )
        md.append(f'        {node}["Remaining<br/>n = {step["remaining"]:,}"]')
        md.append(f"        {previous_node} --> {node}")
        md.append(f"        {previous_node} --> {excluded_node}")
        previous_node = node
    md += [
        "    end",
        '    subgraph Included["Included"]',
        f'        Z["Records included<br/>n = {final_count:,}"]',
        "    end",
        "    A --> B",
        "    A --> C",
        f"    {previous_node} --> Z",
        "```",
        "",
    ]
    return "\n".join(md)


def write_prisma_report(
    dir_collect,
    collect_name,
    run_date,
    parallel_stats,
    filtering_tracker,
    final_count,
    collection_warning_lines=(),
) -> str:
    """Write ``prisma_report.md`` into *dir_collect* and return its path."""
    content = build_prisma_report(
        collect_name,
        run_date,
        parallel_stats,
        filtering_tracker,
        final_count,
        collection_warning_lines,
    )
    path = os.path.join(dir_collect, "prisma_report.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    logging.info(f"PRISMA report saved to {path}")
    return path
