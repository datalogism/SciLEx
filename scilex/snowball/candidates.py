"""Extract and rank candidate DOIs from citation caches for snowball sampling.

Candidates are DOIs that appear in references or citers but are not
in the user's corpus.  They are ranked by frequency: how many corpus
papers cite or are cited by them.
"""

import logging
from collections import Counter

from scilex.graph_analysis.loader import normalize_citation_map, normalize_dois

logger = logging.getLogger(__name__)


def extract_candidates(
    references: dict[str, list[str]],
    citers: dict[str, list[str]],
    corpus_dois: set[str],
    direction: str = "both",
    top_k: int = 200,
    min_frequency: int = 2,
) -> list[tuple[str, int]]:
    """Extract and rank out-of-corpus DOIs by citation frequency.

    Args:
        references: ``{doi: [cited_dois]}`` — outgoing references.
        citers: ``{doi: [citing_dois]}`` — incoming citers.
        corpus_dois: Set of DOIs already in the collection.
        direction: ``"backward"`` (references only), ``"forward"``
            (citers only), or ``"both"``.
        top_k: Maximum number of candidates to return.
        min_frequency: Minimum number of corpus connections to include.

    Returns:
        List of (doi, frequency) tuples, sorted by frequency descending.
        DOIs are compared and returned in normalized (lowercase) form.
    """
    references = normalize_citation_map(references)
    citers = normalize_citation_map(citers)
    corpus_dois = normalize_dois(corpus_dois)
    freq: Counter[str] = Counter()

    if direction in ("backward", "both"):
        # Papers cited BY corpus papers (references = "what does the corpus cite?")
        for corpus_doi in corpus_dois:
            for ref_doi in references.get(corpus_doi, []):
                if ref_doi not in corpus_dois:
                    freq[ref_doi] += 1

    if direction in ("forward", "both"):
        # Papers that CITE corpus papers (citers = "who cites the corpus?")
        for corpus_doi in corpus_dois:
            for citing_doi in citers.get(corpus_doi, []):
                if citing_doi not in corpus_dois:
                    freq[citing_doi] += 1

    # Filter by minimum frequency and take top-K
    candidates = [
        (doi, count) for doi, count in freq.most_common() if count >= min_frequency
    ][:top_k]

    logger.info(
        f"Snowball candidates: {len(freq)} unique DOIs, "
        f"{len(candidates)} after filtering (min_freq={min_frequency}, top_k={top_k})"
    )
    return candidates
