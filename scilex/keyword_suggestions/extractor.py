"""Extract keyword suggestions from clustered papers.

Identifies terms that are frequent in the corpus but absent from the
user's current search configuration, grouped by cluster.
"""

import logging
import re
from collections import Counter

import pandas as pd

from scilex.constants import is_valid
from scilex.pipeline_utils import parse_keyword_values

logger = logging.getLogger(__name__)

_TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "with",
        "from",
        "by",
        "as",
        "it",
        "its",
        "this",
        "that",
        "which",
        "how",
        "what",
        "when",
        "where",
        "who",
        "using",
        "based",
        "via",
        "through",
        "between",
        "into",
    }
)


def _flatten(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [item for element in value for item in _flatten(element)]
    return []


def configured_keywords(config: dict) -> list[str]:
    """Terms already searched: every keyword group plus the bonus keywords.

    ``keywords`` is a list of groups (``[["a", "b"], ["c"]]``); a flat list
    or a comma-separated string is accepted too.
    """
    terms = []
    for source in (config.get("keywords"), config.get("bonus_keywords")):
        terms.extend(_flatten(source.split(",") if isinstance(source, str) else source))
    return terms


def extract_suggestions(
    df: pd.DataFrame,
    existing_keywords: list[str],
    top_k: int = 30,
    min_freq: int = 2,
) -> list[dict]:
    """Extract keyword suggestions not in the current search config.

    Args:
        df: Clusters DataFrame with ``cluster_id``, and optionally
            ``tags``/``keywords``, ``title``.
        existing_keywords: Terms already searched (see ``configured_keywords``).
        top_k: Maximum number of suggestions to return.
        min_freq: Minimum frequency across corpus.

    Returns:
        List of suggestion dicts: ``{"term", "frequency", "cluster_ids"}``,
        sorted by frequency descending.
    """
    existing_keys = {_term_key(k.strip()) for k in existing_keywords}

    # Count terms from keywords/tags columns
    term_freq: Counter[str] = Counter()
    term_clusters: dict[str, set[int]] = {}

    for _, row in df.iterrows():
        cluster_id = int(row.get("cluster_id", -1))

        # Extract from tags/keywords
        for col in ("tags", "keywords", "keyword"):
            if col not in df.columns:
                continue
            val = row.get(col)
            if not is_valid(val):
                continue
            for kw in parse_keyword_values(str(val)):
                _register_term(kw, cluster_id, term_freq, term_clusters)

        # Extract bigrams from titles
        title = row.get("title")
        if is_valid(title):
            for bigram in title_bigrams(str(title)):
                _register_term(bigram, cluster_id, term_freq, term_clusters)

    # Merge singular/plural and case variants under their most frequent form.
    merged_freq: Counter[str] = Counter()
    merged_clusters: dict[str, set[int]] = {}
    display: dict[str, str] = {}
    for term, freq in term_freq.most_common():
        key = _term_key(term)
        display.setdefault(key, term)  # most_common: first seen is the most frequent
        merged_freq[key] += freq
        merged_clusters.setdefault(key, set()).update(term_clusters.get(term, set()))

    # Filter: remove existing keywords and low-frequency terms
    suggestions = []
    for key, freq in merged_freq.most_common():
        if key in existing_keys:
            continue
        if freq < min_freq:
            continue
        if len(key) < 3:
            continue
        suggestions.append(
            {
                "term": display[key],
                "frequency": freq,
                "cluster_ids": sorted(merged_clusters[key]),
            }
        )
        if len(suggestions) >= top_k:
            break

    logger.info(
        f"Keyword suggestions: {len(term_freq)} unique terms, "
        f"{len(suggestions)} suggestions after filtering"
    )
    return suggestions


def _register_term(
    term: str,
    cluster_id: int,
    term_freq: Counter,
    term_clusters: dict[str, set[int]],
) -> None:
    """Register a term in the frequency counter and cluster mapping."""
    if not term or len(term) < 3:
        return
    term_freq[term] += 1
    if term not in term_clusters:
        term_clusters[term] = set()
    term_clusters[term].add(cluster_id)


def title_bigrams(title: str) -> list[str]:
    """Extract lowercase bigrams of adjacent words from a title string.

    Hyphenated words stay whole ("long-term memory", not "term memory").
    Stopwords, short words and punctuation break the sequence instead of being
    skipped, so "Models and Knowledge Graphs" gives "knowledge graphs" but not
    "models knowledge".
    """
    bigrams = []
    for segment in re.split(r"[^\w\s-]", title.lower()):
        previous = None
        for word in re.findall(r"[a-z]+(?:-[a-z]+)*", segment):
            if word in _TITLE_STOPWORDS or len(word) <= 2:
                previous = None
                continue
            if previous:
                bigrams.append(f"{previous} {word}")
            previous = word
    return bigrams


def _term_key(term: str) -> str:
    """Comparison key of a term: lowercase, with a plain plural ``s`` dropped per word.

    "Knowledge Graphs" and "knowledge graph" share a key; "class" keeps its "ss".
    """
    words = term.lower().split()
    return " ".join(
        word[:-1]
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss")
        else word
        for word in words
    )
