#!/usr/bin/env python3
"""
Script to push aggregated papers to Zotero collection.

This script reads aggregated paper data and pushes it to a specified
Zotero collection, handling duplicates and creating the collection if needed.
"""

import argparse
import logging
import os
import sys
from datetime import datetime

import pandas as pd
from tqdm import tqdm

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import is_valid, normalize_path_component
from scilex.io_utils import load_aggregated_data
from scilex.logging_config import setup_logging
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.resolve import resolve_legacy_configs
from scilex.Zotero.zotero_api import (
    ZoteroAPI,
    fetch_item_template,
    prepare_zotero_item,
)


def prefetch_templates(data: pd.DataFrame) -> dict[str, dict]:
    """
    Pre-fetch all unique item type templates before processing.

    This avoids blocking HTTP calls during the main processing loop
    and ensures we only fetch each template once.

    Args:
        data: DataFrame containing paper metadata with 'itemType' column

    Returns:
        Dictionary mapping item types to their Zotero templates
    """
    unique_types = data["itemType"].dropna().unique()
    templates = {}

    logging.info(f"Pre-fetching {len(unique_types)} item type templates...")

    for item_type in unique_types:
        # Handle special case mapping
        if item_type == "bookSection":
            item_type = "journalArticle"

        template = fetch_item_template(item_type)
        if template:
            templates[item_type] = template
            logging.debug(f"Fetched template for: {item_type}")
        else:
            logging.warning(f"Failed to fetch template for {item_type}")

    logging.info(f"Successfully pre-fetched {len(templates)} templates")
    return templates


def push_new_items_to_zotero(
    data: pd.DataFrame,
    zotero_api: ZoteroAPI,
    collection_key: str,
    existing_urls: set,
    templates_cache: dict[str, dict],
    config: dict,
) -> dict[str, int]:
    """
    Push new items to Zotero collection using bulk upload.

    Args:
        data: DataFrame containing paper metadata
        zotero_api: ZoteroAPI client instance
        collection_key: Key of the target collection
        existing_urls: Set of URLs already in the collection (for O(1) lookups)
        templates_cache: Pre-fetched item type templates

    Returns:
        Dictionary with counts: {"success": n, "failed": m, "skipped": k, "skipped_for_incompatibility": j}
    """
    output_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
    dir_collect = config.get("_collect_dir") or os.path.join(
        output_dir, normalize_path_component(config.get("collect_name", ""))
    )
    results = {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "skipped_for_incompatibility": 0,
    }
    invalid_items = []
    items_to_upload = []

    logging.info("Processing papers for upload...")

    # Plain dict records keep the original column names (itertuples renames
    # columns that are not valid identifiers) and are fast to iterate.
    for row in tqdm(data.to_dict("records"), total=len(data), desc="Preparing items"):
        # Prepare Zotero item from row
        item = prepare_zotero_item(row, collection_key, templates_cache)

        if item is None:
            results["skipped_for_incompatibility"] += 1
            invalid_items.append(row)
            continue

        # Check for duplicate URL
        item_url = item.get("url")
        if not is_valid(item_url):
            title = row.get("title", "Unknown")
            logging.warning(f"Skipping paper without valid URL: {title}")
            invalid_items.append(row)
            results["skipped_for_incompatibility"] += 1
            continue

        if item_url in existing_urls:  # O(1) set lookup
            logging.debug(f"Skipping duplicate URL: {item_url}")
            results["skipped"] += 1
            continue

        # Add to batch for bulk upload
        items_to_upload.append(item)
    if invalid_items:
        invalid_data = pd.DataFrame(invalid_items)
        os.makedirs(dir_collect, exist_ok=True)
        invalid_data_path = os.path.join(dir_collect, "invalid_items_no_url.csv")
        invalid_data.to_csv(invalid_data_path, index=False)
        logging.info(
            f"Found {len(invalid_items)} invalid items without valid URLs, saving them into {invalid_data_path}..."
        )
    # Upload all items in bulk (automatically batched into groups of 50)
    if items_to_upload:
        logging.info(f"Uploading {len(items_to_upload)} new papers in bulk...")
        bulk_results = zotero_api.post_items_bulk(items_to_upload)
        results["success"] = bulk_results["success"]
        results["failed"] = bulk_results["failed"]
    else:
        logging.info("No new papers to upload")

    return results


@exit_on_config_error
def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Push aggregated papers to Zotero collection"
    )
    parser.add_argument(
        "--collect-name",
        type=str,
        default=None,
        help="Collect name used to derive the directory path (overrides scilex.config.yml)",
    )
    parser.add_argument(
        "--collect-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Direct path to the collect directory containing aggregated_results.csv "
        "(overrides --output-dir + --collect-name derivation)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (overrides scilex.config.yml)",
    )
    parser.add_argument(
        "--zotero-collection",
        type=str,
        default=None,
        metavar="NAME",
        help="Zotero collection name to push into (overrides collect_name from config)",
    )

    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)
    setup_logging()

    logging.info(f"Zotero push process started at {datetime.now()}")
    logging.info("=" * 60)

    # Load configurations
    main_config, api_config = resolve_legacy_configs()

    # Override with CLI arguments if provided
    if args.collect_name:
        main_config["collect_name"] = args.collect_name
    if args.output_dir:
        main_config["output_dir"] = args.output_dir
    if args.collect_dir:
        main_config["_collect_dir"] = args.collect_dir

    # Extract Zotero configuration (handle both lowercase and capitalized keys)
    zotero_config = api_config.get("Zotero") or api_config.get("zotero")
    if not zotero_config:
        logging.error("Zotero configuration not found in api.config.yml")
        logging.error("Please ensure your api.config.yml has a 'zotero:' section with:")
        logging.error("  - api_key: Your Zotero API key")
        logging.error("  - user_id: Your Zotero user ID")
        logging.error("  - user_mode: 'user' or 'group'")
        sys.exit(1)

    api_key = zotero_config.get("api_key")
    user_id = zotero_config.get("user_id")
    user_role = zotero_config.get("user_mode", "user")

    if not api_key:
        logging.error("Zotero API key not found in api.config.yml")
        sys.exit(1)

    if not user_id:
        logging.error("Zotero user_id not found in api.config.yml")
        logging.error("Please add 'user_id' to the zotero section in api.config.yml")
        logging.error(
            "You can find your user ID at: https://www.zotero.org/settings/keys"
        )
        sys.exit(1)

    collection_name = args.zotero_collection or main_config.get(
        "collect_name", "new_models"
    )

    # Initialize Zotero API client
    logging.info(f"Initializing Zotero API client for {user_role} {user_id}")
    zotero_api = ZoteroAPI(user_id, user_role, api_key)

    # Get or create collection
    logging.info(f"Looking for collection: '{collection_name}'")
    collection = zotero_api.get_or_create_collection(collection_name)

    if not collection:
        logging.error(f"Failed to get or create collection '{collection_name}'")
        sys.exit(1)

    collection_key = collection["data"]["key"]
    logging.info(f"Using collection key: {collection_key}")

    # Get existing URLs to avoid duplicates
    logging.info("Fetching existing items in collection...")
    existing_urls = zotero_api.get_existing_item_urls(collection_key)
    logging.info(f"Found {len(existing_urls)} existing items")

    # Load aggregated data
    data = load_aggregated_data(main_config, collect_dir=args.collect_dir)

    # Pre-fetch all item type templates
    templates_cache = prefetch_templates(data)

    # Push new items
    logging.info("=" * 60)
    logging.info("Starting upload of new papers...")
    results = push_new_items_to_zotero(
        data, zotero_api, collection_key, existing_urls, templates_cache, main_config
    )

    # Log summary
    logging.info("=" * 60)
    logging.info("Upload complete!")
    logging.info(f"✅ Successfully uploaded: {results['success']} papers")
    logging.info(f"❌ Failed to upload: {results['failed']} papers")
    logging.info(f"⏭️  Skipped (duplicates/none): {results['skipped']} papers")
    logging.info(
        f"⏭️  Skipped (non URL): {results['skipped_for_incompatibility']} papers"
    )
    logging.info(f"Process completed at {datetime.now()}")


if __name__ == "__main__":
    main()
