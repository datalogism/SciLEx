"""ItemType-based filtering for the aggregation pipeline."""

import logging

import pandas as pd

from scilex.constants import is_missing


def apply_itemtype_bypass(df, bypass_item_types):
    """Separate papers into bypass and non-bypass groups based on itemType.

    Papers with itemTypes in bypass_item_types skip subsequent quality filters.

    Args:
        df: Input DataFrame
        bypass_item_types: List of itemType values that bypass filters

    Returns:
        tuple: (bypass_df, non_bypass_df)
    """
    if not bypass_item_types:
        return pd.DataFrame(), df

    if "itemType" not in df.columns:
        logging.warning("itemType column not found - bypass filter skipped")
        return pd.DataFrame(), df

    bypass_df = df[df["itemType"].isin(bypass_item_types)].copy()
    non_bypass_df = df[~df["itemType"].isin(bypass_item_types)].copy()

    logging.info(
        f"ItemType bypass: {len(bypass_df)} papers bypass filters ({', '.join(bypass_item_types)})"
    )
    logging.info(f"ItemType bypass: {len(non_bypass_df)} papers require filtering")

    return bypass_df, non_bypass_df


def apply_itemtype_filter(df, allowed_types, enabled):
    """Filter papers to only keep specified itemTypes (whitelist mode).

    Args:
        df: Input DataFrame
        allowed_types: List of allowed itemType values (whitelist)
        enabled: Boolean flag to enable/disable filtering

    Returns:
        tuple: (filtered_df, stats_dict)
    """
    stats = {
        "enabled": enabled,
        "total_before": len(df),
        "total_after": 0,
        "removed": 0,
        "removed_missing_itemtype": 0,
        "kept_by_type": {},
        "removed_by_type": {},
    }

    if not enabled:
        logging.info("ItemType filtering: DISABLED - all itemTypes allowed")
        stats["total_after"] = len(df)
        return df, stats

    if "itemType" not in df.columns:
        logging.warning(
            "ItemType filtering: itemType column not found - filtering skipped"
        )
        stats["total_after"] = len(df)
        return df, stats

    if not allowed_types:
        logging.warning(
            "ItemType filtering: allowed_item_types list is EMPTY - all papers will be removed!"
        )
        stats["total_after"] = 0
        stats["removed"] = len(df)
        return pd.DataFrame(columns=df.columns), stats

    logging.info(
        f"ItemType filtering: ENABLED - whitelist mode with {len(allowed_types)} allowed types"
    )
    logging.info(f"ItemType filtering: Allowed types: {', '.join(allowed_types)}")

    missing_mask = df["itemType"].map(is_missing)
    missing_count = missing_mask.sum()

    filtered_df = df[df["itemType"].isin(allowed_types) & ~missing_mask].copy()

    stats["total_after"] = len(filtered_df)
    stats["removed"] = stats["total_before"] - stats["total_after"]
    stats["removed_missing_itemtype"] = missing_count

    if not filtered_df.empty:
        kept_counts = filtered_df["itemType"].value_counts()
        stats["kept_by_type"] = kept_counts.to_dict()

    removed_df = df[~df.index.isin(filtered_df.index) & ~missing_mask]
    if not removed_df.empty:
        removed_counts = removed_df["itemType"].value_counts()
        stats["removed_by_type"] = removed_counts.to_dict()

    logging.info(f"ItemType filtering: {stats['total_before']} papers before filtering")
    logging.info(
        f"ItemType filtering: {stats['total_after']} papers after filtering (KEPT)"
    )
    removal_pct = (
        stats["removed"] / stats["total_before"] * 100
        if stats["total_before"] > 0
        else 0.0
    )
    logging.info(
        f"ItemType filtering: {stats['removed']} papers removed ({removal_pct:.1f}%)"
    )

    if stats["removed_missing_itemtype"] > 0:
        logging.info(
            f"  - {stats['removed_missing_itemtype']} papers removed: missing/NA itemType"
        )

    if stats["kept_by_type"]:
        logging.info("  Papers KEPT by itemType:")
        for item_type, count in sorted(
            stats["kept_by_type"].items(), key=lambda x: x[1], reverse=True
        ):
            logging.info(f"    - {item_type}: {count} papers")

    if stats["removed_by_type"]:
        logging.info("  Papers REMOVED by itemType:")
        for item_type, count in sorted(
            stats["removed_by_type"].items(), key=lambda x: x[1], reverse=True
        ):
            logging.info(f"    - {item_type}: {count} papers")

    return filtered_df, stats
