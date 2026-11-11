"""Text-based keyword filtering for the aggregation pipeline."""

from scilex.keyword_validation import (
    build_searchable_text,
    exact_match_prepared,
    flexible_match_prepared,
    prepare_text,
)


def _any_exact(keywords_list, text_lower):
    return any(exact_match_prepared(kw, text_lower) for kw in keywords_list)


def _any_flexible(keywords_list, text_lower):
    return any(flexible_match_prepared(kw, text_lower) for kw in keywords_list)


def check_keywords_in_text(keywords_list, text):
    """Exact match: check if any keyword from a list appears verbatim in text.

    Used for mandatory query-term filtering (Group 1 / Group 2 keywords).

    Args:
        keywords_list: List of keywords to check
        text: Text to search in (combined title + abstract)

    Returns:
        bool: True if at least one keyword matches
    """
    return _any_exact(keywords_list, prepare_text(text))


def check_keywords_flexible(keywords_list, text):
    """Flexible match: check if any bonus keyword appears in text.

    Uses a word-level fallback so 'Cultural Heritage' matches even when
    'cultural' and 'heritage' appear separately in the abstract.
    """
    return _any_flexible(keywords_list, prepare_text(text))


def record_passes_text_filter(
    record,
    keywords,
    keyword_groups=None,
    bonus_keywords=None,
):
    """Check if record contains required keywords in title or abstract.

    Dual-group mode (2 groups):
      Group1 (exact) AND (Group2 (exact) OR any bonus keyword (flexible)).
      If no bonus_keywords are configured, Group2 exact match is still required.

    Single-group mode: any keyword from the group (exact match).

    Args:
        record: Paper record dictionary
        keywords: List of keywords from the query (for backward compatibility)
        keyword_groups: Optional list of keyword groups from config (for dual-group mode)
        bonus_keywords: Optional list of domain terms used as flexible fallback
                        for Group 2 when no exact Group 2 match is found.

    Returns:
        bool: True if keyword requirements are met
    """
    if not keywords and not keyword_groups:
        return True

    # Normalized once per record, then reused for every keyword check
    combined_text = prepare_text(
        build_searchable_text(record.get("title"), record.get("abstract"))
    )

    # DUAL KEYWORD GROUP MODE
    if keyword_groups and len(keyword_groups) == 2:
        group1, group2 = keyword_groups

        if not group1 or not group2:
            # Fallback to single-group mode if one group is empty
            all_keywords = [kw for g in keyword_groups for kw in g if g]
            if not all_keywords:
                return True
            keywords = all_keywords
        else:
            if not _any_exact(group1, combined_text):
                return False

            # Group 2: exact match first, then bonus keyword flexible fallback
            if _any_exact(group2, combined_text):
                return True
            if bonus_keywords:
                return _any_flexible(bonus_keywords, combined_text)
            return False

    # SINGLE KEYWORD GROUP MODE
    if keyword_groups:
        keywords = [kw for group in keyword_groups for kw in group if group]

    return _any_exact(keywords, combined_text)
