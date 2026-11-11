"""Load citation caches (JSON) produced by scilex-enrich-citations.

The caches are simple ``{doi: [list_of_dois]}`` mappings:

- ``citations_cache.json`` — outgoing references (what each paper cites)
- ``citers_cache.json``    — incoming citers (who cites each paper)
"""

import json
import logging
import os
from collections.abc import Iterable

from scilex.constants import normalize_doi

logger = logging.getLogger(__name__)


def load_citation_caches(
    collect_dir: str,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Load reference and citer caches from the collection output directory.

    Args:
        collect_dir: Path to ``output/{collect_name}/``.

    Returns:
        Tuple of (references_map, citers_map) where each is
        ``{doi: [list_of_dois]}``, with DOIs normalized (see
        ``normalize_citation_map``).

    Raises:
        FileNotFoundError: If neither cache file exists.
    """
    ref_path = os.path.join(collect_dir, "citations_cache.json")
    citer_path = os.path.join(collect_dir, "citers_cache.json")

    references = normalize_citation_map(_load_json_cache(ref_path))
    citers = normalize_citation_map(_load_json_cache(citer_path))

    if not references and not citers:
        raise FileNotFoundError(
            f"No citation caches found in {collect_dir}. "
            "Run scilex-enrich-citations first."
        )

    logger.info(
        f"Loaded citation caches: {len(references)} references, {len(citers)} citers"
    )
    return references, citers


def _load_json_cache(path: str) -> dict[str, list[str]]:
    """Load a single JSON cache file, returning empty dict if absent."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Cache file not found: {path}")
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not load cache {path}: {e}")
        return {}


def normalize_dois(dois: Iterable) -> set[str]:
    """Return the normalized (bare, lowercase) form of ``dois``, dropping empty ones.

    DOIs are case-insensitive: ``10.1/ABC`` and ``10.1/abc`` are the same paper.
    """
    return {doi for doi in map(normalize_doi, dois) if doi}


def normalize_citation_map(mapping: dict) -> dict[str, list[str]]:
    """Normalize the DOIs of a ``{doi: [dois]}`` map, merging case variants.

    Keys that differ only by case (or doi.org prefix) are merged, linked DOIs are
    normalized and deduplicated in their first-seen order, empty ones dropped.
    """
    # dict keys keep the first-seen order and deduplicate.
    normalized: dict[str, dict[str, None]] = {}
    for key, linked in mapping.items():
        doi = normalize_doi(key)
        if not doi:
            continue
        merged = normalized.setdefault(doi, {})
        merged.update(dict.fromkeys(d for d in map(normalize_doi, linked or []) if d))
    return {doi: list(linked) for doi, linked in normalized.items()}
