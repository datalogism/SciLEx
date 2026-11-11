#!/usr/bin/env python3
"""
Report on tag/keyword annotations present in a Zotero library at a given moment.

Pulls items live from a Zotero collection (or an entire library), splits their
tags into SciLEx-automation tags vs. human-annotation tags, breaks structured
"TAG:subtag" annotations down by dimension, and uses Zotero's own
createdByUser / lastModifiedByUser metadata to approximate per-annotator
activity. Intended as raw material for later defining a normalised annotation
grid (see scilex/tagging/).

Usage:
    python -m scilex.report_annotations --collection-key BL6827BD --group-id 6623240
    python -m scilex.report_annotations --collection "CHDO_Lifecycle" --group-id 6623240
    python -m scilex.report_annotations --group-id 6623240   # whole library
"""

import argparse
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from scilex.crawlers.utils import load_all_configs
from scilex.tagging.grid import is_automation_tag
from scilex.Zotero.zotero_api import ZoteroAPI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zotero fetching
# ---------------------------------------------------------------------------


def fetch_items(api: ZoteroAPI, collection_key: str | None) -> list[dict]:
    """Fetch all items, either from one collection or the whole library."""
    if collection_key:
        return api.get_collection_items(collection_key)

    items: list[dict] = []
    start = 0
    limit = 100
    while True:
        response = api._get("/items/top", params={"limit": limit, "start": start})
        if not response:
            break
        page = response.json()
        if not page:
            break
        items.extend(page)
        total = int(response.headers.get("Total-Results", 0))
        if start + limit >= total:
            break
        start += limit
    logger.info(f"Found {len(items)} items in library")
    return items


def resolve_collection_key(api: ZoteroAPI, name: str) -> str:
    collection = api.find_collection_by_name(name)
    if not collection:
        logger.error(f"Collection not found: {name}")
        sys.exit(1)
    return collection["data"]["key"]


# ---------------------------------------------------------------------------
# Tag analysis
# ---------------------------------------------------------------------------


def analyze_items(items: list[dict]) -> dict:
    """
    Walk every item's tags and Zotero log metadata, building the aggregates
    needed for the report tables.
    """
    # tag_full -> set of item keys that carry it
    tag_articles: dict[str, set[str]] = defaultdict(set)

    # (category, dimension) -> set of item keys (for the by-dimension table)
    dimension_articles: dict[tuple[str, str], set[str]] = defaultdict(set)
    dimension_subtags: dict[tuple[str, str], set[str]] = defaultdict(set)

    # username -> stats accumulated from items they last touched
    annotator_items: dict[str, set[str]] = defaultdict(set)
    annotator_annotation_tags: dict[str, int] = defaultdict(int)
    annotator_automation_tags: dict[str, int] = defaultdict(int)

    creator_usernames: list[str] = []
    valid_papers = [
        it
        for it in items
        if it.get("data", {}).get("itemType") != "attachment"
        and "title" in it.get("data", {})
    ]

    for item in valid_papers:
        data = item.get("data", {})
        meta = item.get("meta", {})
        item_key = item.get("key", "")

        created_by = meta.get("createdByUser") or {}
        modified_by = meta.get("lastModifiedByUser") or {}
        creator_usernames.append(created_by.get("username", ""))
        last_editor = (
            modified_by.get("username") or created_by.get("username") or "UNKNOWN"
        )

        for tag_entry in data.get("tags", []):
            tag = tag_entry.get("tag", "").strip()
            if not tag:
                continue

            category = "automation" if is_automation_tag(tag) else "annotation"
            tag_articles[tag].add(item_key)

            if ":" in tag:
                dimension, _, _subtag_val = tag.partition(":")
                dimension = dimension.strip()
            else:
                dimension = tag  # unstructured tag is its own "dimension"

            dimension_articles[(category, dimension)].add(item_key)
            dimension_subtags[(category, dimension)].add(tag)

            annotator_items[last_editor].add(item_key)
            if category == "annotation":
                annotator_annotation_tags[last_editor] += 1
            else:
                annotator_automation_tags[last_editor] += 1

    # The username that created the vast majority of items is the SciLEx
    # push account, not a human annotator.
    pusher_username = None
    if creator_usernames:
        pusher_username = max(set(creator_usernames), key=creator_usernames.count)

    return {
        "valid_papers": valid_papers,
        "tag_articles": tag_articles,
        "dimension_articles": dimension_articles,
        "dimension_subtags": dimension_subtags,
        "annotator_items": annotator_items,
        "annotator_annotation_tags": annotator_annotation_tags,
        "annotator_automation_tags": annotator_automation_tags,
        "pusher_username": pusher_username,
    }


# ---------------------------------------------------------------------------
# Report tables
# ---------------------------------------------------------------------------


def build_tags_summary(analysis: dict) -> pd.DataFrame:
    rows = []
    for tag, item_keys in analysis["tag_articles"].items():
        category = "automation" if is_automation_tag(tag) else "annotation"
        structured = ":" in tag
        if structured:
            dimension, _, subtag = tag.partition(":")
            dimension, subtag = dimension.strip(), subtag.strip()
        else:
            dimension, subtag = "", tag
        rows.append(
            {
                "tag": tag,
                "category": category,
                "is_structured": structured,
                "dimension": dimension,
                "subtag": subtag,
                "nb_articles": len(item_keys),
                "word_count": len(tag.split()),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values("nb_articles", ascending=False).reset_index(drop=True)


def build_tags_by_dimension(analysis: dict) -> pd.DataFrame:
    rows = []
    for (category, dimension), item_keys in analysis["dimension_articles"].items():
        rows.append(
            {
                "category": category,
                "dimension": dimension,
                "nb_distinct_subtags": len(
                    analysis["dimension_subtags"][(category, dimension)]
                ),
                "nb_article_instances": len(item_keys),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values("nb_article_instances", ascending=False).reset_index(
        drop=True
    )


def build_annotator_activity(analysis: dict) -> pd.DataFrame:
    pusher = analysis["pusher_username"]
    rows = []
    for username, item_keys in analysis["annotator_items"].items():
        rows.append(
            {
                "username": username,
                "is_scilex_push_account": username == pusher,
                "nb_items_last_touched": len(item_keys),
                "nb_annotation_tag_instances": analysis["annotator_annotation_tags"][
                    username
                ],
                "nb_automation_tag_instances": analysis["annotator_automation_tags"][
                    username
                ],
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values("nb_items_last_touched", ascending=False).reset_index(
        drop=True
    )


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------


def print_summary(analysis: dict, tags_df: pd.DataFrame) -> None:
    total_papers = len(analysis["valid_papers"])
    automation_instances = tags_df[tags_df["category"] == "automation"][
        "nb_articles"
    ].sum()
    annotation_instances = tags_df[tags_df["category"] == "annotation"][
        "nb_articles"
    ].sum()

    print("\n" + "=" * 70)
    print("ANNOTATION REPORT")
    print("=" * 70)
    print(f"Papers analyzed          : {total_papers}")
    print(f"Distinct tags             : {len(tags_df)}")
    print(f"Automation tag instances  : {automation_instances}")
    print(f"Annotation tag instances  : {annotation_instances}")

    pusher = analysis["pusher_username"]
    untouched = len(analysis["annotator_items"].get(pusher, set())) if pusher else 0
    print(
        f"\nItems never modified since SciLEx push ({pusher}): {untouched} "
        f"/ {total_papers}"
    )

    print("\nTop 15 annotation tags:")
    top = tags_df[tags_df["category"] == "annotation"].head(15)
    for _, row in top.iterrows():
        print(f"  {row['nb_articles']:>4}  {row['tag']}")

    print("\nAnnotator activity (approximate — from Zotero's last-modified log):")
    activity = build_annotator_activity(analysis)
    for _, row in activity.iterrows():
        tag_role = " [SciLEx push account]" if row["is_scilex_push_account"] else ""
        print(
            f"  {row['username']:<20} items={row['nb_items_last_touched']:<5} "
            f"annotation_tags={row['nb_annotation_tag_instances']:<5} "
            f"automation_tags={row['nb_automation_tag_instances']:<5}{tag_role}"
        )
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Report tag/keyword annotations from a Zotero library or collection.",
    )
    parser.add_argument(
        "--collection-key",
        help="Zotero collection key (fastest, skips name lookup), e.g. BL6827BD",
    )
    parser.add_argument(
        "--collection",
        help="Zotero collection name to look up (requires --group-id/--user-id + --library-type)",
    )
    parser.add_argument(
        "--group-id",
        "--user-id",
        dest="library_id",
        help="Zotero group or user ID hosting the collection. "
        "Defaults to api.config.yml's Zotero.user_id if omitted.",
    )
    parser.add_argument(
        "--library-type",
        choices=["group", "user"],
        help="Defaults to api.config.yml's Zotero.user_mode if omitted.",
    )
    parser.add_argument(
        "--api-key",
        help="Zotero API key. Defaults to api.config.yml's Zotero.api_key if omitted.",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Directory containing scilex.config.yml / api.config.yml (default: scilex/ package dir)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write CSV reports to (default: ./annotation_report_<collection>)",
    )
    args = parser.parse_args()

    config_files = {"main_config": "scilex.config.yml", "api_config": "api.config.yml"}
    if args.config_dir:
        config_dir = Path(args.config_dir)
        config_files = {
            "main_config": str(config_dir / "scilex.config.yml"),
            "api_config": str(config_dir / "api.config.yml"),
        }

    try:
        configs = load_all_configs(config_files)
    except Exception as e:
        logger.error(f"Failed to load configuration files: {e}")
        sys.exit(1)

    zotero_cfg = configs["api_config"]["Zotero"]
    library_id = args.library_id or zotero_cfg["user_id"]
    library_type = args.library_type or zotero_cfg["user_mode"]
    api_key = args.api_key or zotero_cfg["api_key"]

    api = ZoteroAPI(user_id=library_id, user_role=library_type, api_key=api_key)

    collection_key = args.collection_key
    if not collection_key and args.collection:
        collection_key = resolve_collection_key(api, args.collection)

    label = args.collection or collection_key or f"library_{library_id}"
    logger.info(f"Fetching items for: {label} (library {library_id}, {library_type})")
    items = fetch_items(api, collection_key)
    logger.info(f"Fetched {len(items)} items")

    analysis = analyze_items(items)
    tags_df = build_tags_summary(analysis)
    dimension_df = build_tags_by_dimension(analysis)
    annotator_df = build_annotator_activity(analysis)

    safe_label = re.sub(r"[^\w]", "_", label)
    out_dir = args.output_dir or Path(f"annotation_report_{safe_label}")
    out_dir.mkdir(parents=True, exist_ok=True)

    tags_df.to_csv(out_dir / "tags_summary.csv", index=False)
    dimension_df.to_csv(out_dir / "tags_by_dimension.csv", index=False)
    annotator_df.to_csv(out_dir / "annotator_activity.csv", index=False)

    print_summary(analysis, tags_df)
    print(f"CSV reports written to: {out_dir}")


if __name__ == "__main__":
    main()
