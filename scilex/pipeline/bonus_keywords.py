"""Bonus keyword tagging and distribution reporting."""

import logging

from scilex.keyword_validation import check_keyword_in_text_flexible


def tag_papers_with_bonus_keywords(df, bonus_keywords):
    """Add a bonus_keyword_tags column listing matched bonus keywords per paper.

    Each matched keyword is prefixed with 'BK:' and tags are pipe-separated,
    e.g. 'BK:Cultural Heritage|BK:Digital Humanities'.
    Uses the same word-level fallback as the main text filter so compound
    keywords like 'Cultural Heritage' are matched even when the words appear
    separately in the abstract.

    Args:
        df: DataFrame with 'title' and 'abstract' columns
        bonus_keywords: List of bonus keyword strings from config

    Returns:
        pd.DataFrame: DataFrame with new 'bonus_keyword_tags' column
    """
    if not bonus_keywords:
        df = df.copy()
        df["bonus_keyword_tags"] = ""
        return df

    def _tags_for_row(row):
        title = str(row.get("title", "") or "")
        abstract = str(row.get("abstract", "") or "")
        combined = title + " " + abstract
        matched = [
            f"BK:{kw}"
            for kw in bonus_keywords
            if check_keyword_in_text_flexible(kw, combined)
        ]
        return "|".join(matched)

    df = df.copy()
    df["bonus_keyword_tags"] = df.apply(_tags_for_row, axis=1)
    return df


def generate_bonus_keyword_stats(df, bonus_keywords):
    """Log a distribution report for bonus keyword tags.

    Args:
        df: DataFrame with 'bonus_keyword_tags' column
        bonus_keywords: List of bonus keyword strings from config
    """
    if not bonus_keywords or "bonus_keyword_tags" not in df.columns:
        return

    total = len(df)
    tagged = (df["bonus_keyword_tags"] != "").sum()

    lines = [
        "",
        "=" * 60,
        "BONUS KEYWORD TAG DISTRIBUTION",
        "=" * 60,
        f"  Papers with at least one tag : {tagged:,} / {total:,} ({tagged / total * 100:.1f}%)",
        "",
    ]

    for kw in bonus_keywords:
        tag = f"BK:{kw}"
        count = df["bonus_keyword_tags"].str.contains(tag, regex=False).sum()
        bar = "#" * min(int(count / max(total, 1) * 40), 40)
        lines.append(f"  {kw:<35s} {count:5,}  {bar}")

    lines.append("=" * 60)
    logging.info("\n".join(lines))
