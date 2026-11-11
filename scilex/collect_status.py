"""
Collection completeness report for SciLEx.

Reconstructs the expected query list from config_used.yml, checks what's on
disk, and prints a human-readable summary of:
  - Per-API progress (done / partial / not started)
  - Per-keyword-combo coverage across all APIs and years
  - Overall completion percentage

Callable standalone:  python -m scilex status [--collection NAME]
Also called automatically at the start of  python -m scilex aggregate.
"""

import argparse
import os
import sys
from itertools import product

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import QUERY_MARKER_FILES
from scilex.crawlers.utils import load_yaml_config
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.resolve import resolve_main_config

# ─── helpers ──────────────────────────────────────────────────────────────────


def _resolve_collect_dir(collection_arg: str | None, src_dir: str) -> str:
    """Return absolute path to the collection directory."""
    if collection_arg is None:
        cfg = resolve_main_config()
        output_dir = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
        collect_name = cfg.get("collect_name", "unknown")
        return os.path.join(output_dir, collect_name)

    if (
        os.path.isabs(collection_arg)
        or os.sep in collection_arg
        or "/" in collection_arg
    ):
        return collection_arg

    # Name only — look up output_dir from the current config
    try:
        cfg = resolve_main_config()
        output_dir = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
    except FileNotFoundError:
        output_dir = DEFAULT_OUTPUT_DIR
    return os.path.join(output_dir, collection_arg)


def _build_query_index(config: dict) -> tuple[dict[str, list[dict]], list[list]]:
    """
    Reconstruct the per-API query list from a config dict.

    Returns {api_name: [{keyword: combo, year: y}, ...]} in the same order
    as CollectCollection.queryCompositor() so query_idx == list index.
    """
    keyword_groups = config.get("keywords", [])
    years = config.get("years", [])
    apis = config.get("apis", [])

    if (
        len(keyword_groups) == 2
        and len(keyword_groups[0]) > 0
        and len(keyword_groups[1]) > 0
    ):
        combos = [list(pair) for pair in product(keyword_groups[0], keyword_groups[1])]
    elif len(keyword_groups) >= 1 and len(keyword_groups[0]) > 0:
        combos = [[k] for k in keyword_groups[0]]
    else:
        combos = []

    queries_by_api: dict[str, list[dict]] = {api: [] for api in apis}
    for combo, year, api in product(combos, years, apis):
        queries_by_api[api].append({"keyword": combo, "year": year})

    return queries_by_api, combos


def _query_state(query_dir: str) -> str:
    """Return 'done' | 'partial' | 'not_started' for a query directory."""
    if not os.path.isdir(query_dir):
        return "not_started"
    if os.path.isfile(os.path.join(query_dir, "_complete")):
        return "done"
    files = [f for f in os.listdir(query_dir) if f not in QUERY_MARKER_FILES]
    return "partial" if files else "not_started"


# ─── core status function ─────────────────────────────────────────────────────


def build_status(dir_collect: str, config: dict) -> dict:
    """
    Compute collection completeness.

    Returns a dict with keys:
      apis        — {api: {done, partial, not_started, total}}
      combos      — [{keyword, done, partial, not_started, total_slots}]
      totals      — {done, partial, not_started, total}
      config      — the config dict
      dir_collect — the directory scanned
    """
    queries_by_api, combos = _build_query_index(config)
    apis = list(queries_by_api.keys())
    years = config.get("years", [])

    # Per-API counts
    api_stats: dict[str, dict] = {}
    # Per-combo: map combo_key → {done, partial, not_started}
    combo_stats: dict[str, dict] = {
        str(c): {"done": 0, "partial": 0, "not_started": 0} for c in combos
    }

    for api, queries in queries_by_api.items():
        api_dir = os.path.join(dir_collect, api)
        counts = {"done": 0, "partial": 0, "not_started": 0, "total": len(queries)}
        for idx, query in enumerate(queries):
            state = _query_state(os.path.join(api_dir, str(idx)))
            counts[state] += 1
            ckey = str(query["keyword"])
            combo_stats[ckey][state] += 1
        api_stats[api] = counts

    # Per-combo totals (total_slots = n_apis × n_years, but grouped per combo×api×year)
    n_apis = len(apis)
    n_years = len(years)
    combo_rows = []
    for combo in combos:
        ckey = str(combo)
        s = combo_stats[ckey]
        total = n_apis * n_years
        combo_rows.append(
            {
                "keyword": combo,
                "done": s["done"],
                "partial": s["partial"],
                "not_started": s["not_started"],
                "total_slots": total,
            }
        )

    totals = {"done": 0, "partial": 0, "not_started": 0, "total": 0}
    for s in api_stats.values():
        for k in ("done", "partial", "not_started", "total"):
            totals[k] += s[k]

    return {
        "apis": api_stats,
        "combos": combo_rows,
        "totals": totals,
        "config": config,
        "dir_collect": dir_collect,
    }


# ─── printing ─────────────────────────────────────────────────────────────────


def print_status(status: dict, verbose: bool = False) -> None:
    """Print a formatted status report to stdout."""
    cfg = status["config"]
    keyword_groups = cfg.get("keywords", [])
    years = cfg.get("years", [])
    apis = cfg.get("apis", [])

    n_g1 = len(keyword_groups[0]) if len(keyword_groups) > 0 else 0
    n_g2 = len(keyword_groups[1]) if len(keyword_groups) > 1 else 0
    n_combos = len(status["combos"])

    collect_name = cfg.get("collect_name", os.path.basename(status["dir_collect"]))
    W = 68

    print()
    print("═" * W)
    print(f"  Collection Status: {collect_name}")
    print("═" * W)
    print(f"  Directory : {status['dir_collect']}")
    if n_g2:
        print(f"  Keywords  : {n_g1} (group 1) × {n_g2} (group 2) = {n_combos} combos")
    else:
        print(f"  Keywords  : {n_g1} (single group = {n_combos} queries per year/API)")
    print(
        f"  Years     : {len(years)}  →  {years[0]}–{years[-1]}"
        if years
        else "  Years     : —"
    )
    print(f"  APIs      : {len(apis)}  →  {', '.join(apis)}")
    t = status["totals"]
    print(f"  Expected  : {t['total']:,} total queries")
    print()

    # ── Per-API table ──────────────────────────────────────────────────────
    print(
        f"  {'API':<22} {'Done':>6} {'Partial':>8} {'Not Started':>12} {'Total':>7}  {'%Done':>6}"
    )
    print("  " + "─" * (W - 2))
    for api, s in sorted(status["apis"].items()):
        pct = f"{100 * s['done'] / s['total']:.1f}%" if s["total"] else "—"
        print(
            f"  {api:<22} {s['done']:>6,} {s['partial']:>8,} {s['not_started']:>12,} "
            f"{s['total']:>7,}  {pct:>6}"
        )
    print("  " + "─" * (W - 2))
    pct_total = f"{100 * t['done'] / t['total']:.1f}%" if t["total"] else "—"
    print(
        f"  {'TOTAL':<22} {t['done']:>6,} {t['partial']:>8,} {t['not_started']:>12,} "
        f"{t['total']:>7,}  {pct_total:>6}"
    )
    print()

    # ── Keyword-combo summary ──────────────────────────────────────────────
    combos = status["combos"]
    done_combos = [c for c in combos if c["done"] == c["total_slots"]]
    partial_combos = [
        c for c in combos if 0 < c["done"] < c["total_slots"] or c["partial"] > 0
    ]
    pending_combos = [c for c in combos if c["done"] == 0 and c["partial"] == 0]

    def _combo_label(combo_kw):
        return " + ".join(combo_kw) if isinstance(combo_kw, list) else str(combo_kw)

    print(
        f"  Keyword combo coverage  ({n_combos} combos × {len(apis)} APIs × {len(years)} years = {n_combos * len(apis) * len(years):,} slots)"
    )
    print("  " + "─" * (W - 2))
    print(f"  ✓ Fully complete : {len(done_combos)}")
    print(f"  ~ Partial        : {len(partial_combos)}")
    print(f"  ✗ Not started    : {len(pending_combos)}")
    print()

    if verbose:
        if done_combos:
            print("  [COMPLETE]")
            for c in done_combos:
                print(f"    {_combo_label(c['keyword'])}")
            print()
        if partial_combos:
            print("  [PARTIAL]")
            for c in partial_combos:
                total = c["total_slots"]
                print(
                    f"    {_combo_label(c['keyword'])}  ({c['done']}/{total} slots done)"
                )
            print()
        if pending_combos:
            print("  [NOT STARTED]")
            for c in pending_combos:
                print(f"    {_combo_label(c['keyword'])}")
            print()
    else:
        # Compact view: always show partial; cap complete/pending lists
        MAX_SHOW = 5
        if partial_combos:
            print("  Partial combos:")
            for c in partial_combos[:MAX_SHOW]:
                total = c["total_slots"]
                print(
                    f"    ~ {_combo_label(c['keyword'])}  ({c['done']}/{total} slots done)"
                )
            if len(partial_combos) > MAX_SHOW:
                print(
                    f"    … and {len(partial_combos) - MAX_SHOW} more  (use --verbose to see all)"
                )
            print()
        if pending_combos:
            print("  Not-started combos:")
            for c in pending_combos[:MAX_SHOW]:
                print(f"    ✗ {_combo_label(c['keyword'])}")
            if len(pending_combos) > MAX_SHOW:
                print(
                    f"    … and {len(pending_combos) - MAX_SHOW} more  (use --verbose to see all)"
                )
            print()

    # ── Overall verdict ────────────────────────────────────────────────────
    if t["total"] == 0:
        verdict = "EMPTY — collection not yet started"
    elif t["done"] == t["total"]:
        verdict = "COMPLETE ✓"
    elif t["done"] == 0 and t["partial"] == 0:
        verdict = "NOT STARTED"
    else:
        verdict = f"PARTIAL — {pct_total} done"
    print(f"  Overall: {t['done']:,} / {t['total']:,} queries complete → {verdict}")
    print("═" * W)
    print()


# ─── entry point ──────────────────────────────────────────────────────────────


@exit_on_config_error
def main():
    parser = argparse.ArgumentParser(
        description="Show collection completeness status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scilex status\n"
            "  python -m scilex status --collection CulturalHeritageAItools\n"
            "  python -m scilex status --collection CulturalHeritageAItools --verbose\n"
        ),
    )
    parser.add_argument(
        "--collection",
        metavar="COLLECT",
        default=None,
        help="Collection name or full path (default: from scilex.config.yml)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full keyword combo lists instead of truncated summaries",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    src_dir = os.path.dirname(os.path.abspath(__file__))
    dir_collect = _resolve_collect_dir(args.collection, src_dir)

    config_path = os.path.join(dir_collect, "config_used.yml")
    if not os.path.isfile(config_path):
        print(f"Error: config_used.yml not found at {config_path}")
        print("Start a collection first:  python -m scilex collect")
        sys.exit(1)

    config = load_yaml_config(config_path)
    status = build_status(dir_collect, config)
    print_status(status, verbose=args.verbose)


if __name__ == "__main__":
    main()
