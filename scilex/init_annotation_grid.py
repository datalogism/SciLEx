#!/usr/bin/env python3
"""
Generic tagging script for Zotero collections.

This script reads a CSV file containing tag definitions and applies them to papers
in a specified Zotero collection. Tags are normalized and missing tags are added
with "?" placeholders.

Usage:
    python init_annotation_grid.py --collection <collection_name> --csv <csv_file> --type <paper_type>

Example:
    python init_annotation_grid.py --collection "datasets" --csv "tag_FOCUS.csv" --type "datasets"
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import requests

from scilex.crawlers.utils import load_all_configs
from scilex.tagging.grid import (  # noqa: F401  (re-exported for callers)
    load_tags_from_csv,
    normalize_tag_value,
    process_paper_tags,
)

logger = logging.getLogger(__name__)


class ZoteroTagger:
    """Handles tagging operations for Zotero collections."""

    def __init__(self, user_id: str, api_key: str, user_role: str = "group"):
        self.user_id = user_id
        self.api_key = api_key
        self.user_role = user_role
        self.base_url = self._build_base_url()

    def _build_base_url(self) -> str:
        """Build the base URL for Zotero API calls."""
        if self.user_role == "group":
            return f"https://api.zotero.org/groups/{self.user_id}"
        elif self.user_role == "user":
            return f"https://api.zotero.org/users/{self.user_id}"
        else:
            raise ValueError(f"Invalid user_role: {self.user_role}")

    def _get_headers(self, version: int = None) -> dict:
        """Get headers for API requests."""
        headers = {"Zotero-API-Key": self.api_key}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        return headers

    def get_item_data(self, item_key: str) -> dict:
        """Fetch item data from Zotero."""
        url = f"{self.base_url}/items/{item_key}?format=json"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def patch_item(self, item_key: str, data: dict) -> int:
        """Patch an item in Zotero with new data."""
        item_data = self.get_item_data(item_key)
        version = item_data["version"]
        url = f"{self.base_url}/items/{item_key}"
        response = requests.patch(
            url,
            data=json.dumps(data),
            headers=self._get_headers(version),
        )
        return response.status_code

    def get_collections(self, limit: int = 100) -> list:
        """Fetch all collections from Zotero."""
        url = f"{self.base_url}/collections?limit={limit}&start=0"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def find_collection_key(self, collection_name: str) -> str | None:
        """Find a collection key by name."""
        collections = self.get_collections()
        for coll in collections:
            if coll["data"]["name"] == collection_name:
                logger.info(f"Found collection: {collection_name}")
                return coll["data"]["key"]
        return None

    def get_collection_items(self, collection_key: str, batch_size: int = 100) -> list:
        """Fetch all items from a collection."""
        all_items = []
        start = 0

        while True:
            url = f"{self.base_url}/collections/{collection_key}/items/top?limit={batch_size}&start={start}"
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()
            items = response.json()

            if not items:
                break

            all_items.extend(items)
            start += batch_size
            logger.info(f"Fetched {len(all_items)} items so far...")

        return all_items


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Apply tags from a CSV file to a Zotero collection."
    )
    parser.add_argument(
        "--collection",
        "-c",
        required=True,
        help="Name of the Zotero collection to process",
    )
    parser.add_argument(
        "--csv",
        "-f",
        required=True,
        help="Path to the CSV file containing tag definitions",
    )
    parser.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["datasets", "surveys", "models"],
        help="Type of papers to process (determines which tags to apply)",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Directory containing config files (default: auto-detect)",
    )

    args = parser.parse_args()

    # Load configurations - auto-detect config directory if not specified
    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        # Default to the same directory as this script (src/)
        config_dir = Path(__file__).resolve().parent

    config_files = {
        "main_config": str(config_dir / "scilex.config.yml"),
        "api_config": str(config_dir / "api.config.yml"),
    }

    try:
        configs = load_all_configs(config_files)
    except Exception as e:
        logger.error(f"Failed to load configuration files: {e}")
        sys.exit(1)

    api_config = configs["api_config"]

    # Initialize Zotero client
    tagger = ZoteroTagger(
        user_id=api_config["Zotero"]["user_id"],
        api_key=api_config["Zotero"]["api_key"],
        user_role=api_config["Zotero"]["user_mode"],
    )

    # Load tags from CSV
    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)

    tags_by_type = load_tags_from_csv(str(csv_path))
    expected_tags = tags_by_type[args.type]
    logger.info(f"Loaded {len(expected_tags)} tags for type '{args.type}'")

    # Find collection
    collection_key = tagger.find_collection_key(args.collection)
    if not collection_key:
        logger.error(f"Collection not found: {args.collection}")
        sys.exit(1)

    # Fetch papers
    logger.info(f"Fetching papers from collection '{args.collection}'...")
    papers = tagger.get_collection_items(collection_key)
    logger.info(f"Found {len(papers)} items in collection")

    # Process papers
    papers_to_update = {}
    for paper in papers:
        # Skip attachments and items without titles
        if paper["data"]["itemType"] == "attachment":
            continue
        if "title" not in paper["data"]:
            continue

        corrected_tags = process_paper_tags(paper, expected_tags)

        if corrected_tags:
            papers_to_update[paper["key"]] = corrected_tags

    logger.info(f"Papers to update: {len(papers_to_update)}")

    # Apply updates
    if args.dry_run:
        logger.info("DRY RUN - No changes will be applied")
        for zid, tags in papers_to_update.items():
            logger.info(f"  {zid}: {tags}")
    else:
        success_count = 0
        error_count = 0

        for zid, tags in papers_to_update.items():
            changes = {"tags": [{"tag": tag} for tag in tags]}
            try:
                status = tagger.patch_item(zid, changes)
                if status == 204:
                    success_count += 1
                    logger.debug(f"Updated {zid}")
                else:
                    error_count += 1
                    logger.warning(f"Failed to update {zid}: status {status}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error updating {zid}: {e}")

        logger.info(f"Completed: {success_count} successful, {error_count} errors")


if __name__ == "__main__":
    main()
