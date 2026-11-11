"""Seed-papers mode: discover related literature starting from known papers.

Usage:
    scilex-seed --dois 10.1234/abc 10.5678/def [--limit 100]
    scilex-seed --doi-file seeds.txt
    scilex-seed --bibtex seeds.bib --snowball

Seed papers (DOIs given directly, listed in a text file or read from a BibTeX
file) are sent to the Semantic Scholar Recommendations API. Optionally one
snowball round (citations / references of the results) completes them. Results
go through the same quality and citation filters as the aggregation and are
written as an aggregated CSV in ``{output_dir}/{collect_name}/``, so that
``scilex-export-bibtex``, ``scilex-push-zotero`` and ``scilex-export-turtle``
work on it directly.
"""

import argparse
import logging
import os
import sys
import urllib.parse

import bibtexparser
import pandas as pd
import requests
from ratelimit import limits, sleep_and_retry
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from scilex.config_defaults import DEFAULT_AGGREGATED_FILENAME, DEFAULT_OUTPUT_DIR
from scilex.constants import is_valid, normalize_doi, normalize_path_component
from scilex.io_utils import write_aggregated_csv
from scilex.logging_config import setup_logging
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError
from scilex.snowball.fetcher import SS_FIELDS, convert_ss_paper

logger = logging.getLogger(__name__)

SS_RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1/papers"
# Semantic Scholar caps a recommendation request at 500 papers.
MAX_RECOMMENDATIONS = 500
DEFAULT_LIMIT = 100
DEFAULT_SEED_COLLECT_SUFFIX = "_seed"
FALLBACK_COLLECT_NAME = "seed_papers"
SNOWBALL_TOP_K = 100
SNOWBALL_MIN_FREQUENCY = 2


class _RetryableSSError(Exception):
    """Transient Semantic Scholar failure (429, 5xx, network)."""


def _unique_dois(raw_dois) -> list[str]:
    """Normalize DOIs, drop invalid ones and duplicates, keep order."""
    seen: dict[str, None] = {}
    for raw in raw_dois:
        doi = normalize_doi(raw)
        if doi:
            seen.setdefault(doi)
    return list(seen)


def read_doi_file(path: str) -> list[str]:
    """Read DOIs from a text file (one per line, ``#`` comments allowed)."""
    with open(path, encoding="utf-8") as handle:
        lines = [line.split("#", 1)[0].strip() for line in handle]
    return _unique_dois(line for line in lines if line)


def read_bibtex_dois(path: str) -> list[str]:
    """Read the DOIs of the entries of a BibTeX file."""
    library = bibtexparser.parse_file(path)
    return _unique_dois(
        entry.fields_dict["doi"].value
        for entry in library.entries
        if "doi" in entry.fields_dict
    )


@sleep_and_retry
@limits(calls=1, period=1)
def _rate_limited_post(headers: dict, params: dict, body: dict) -> requests.Response:
    return requests.post(
        SS_RECOMMENDATIONS_URL, headers=headers, params=params, json=body, timeout=60
    )


@retry(
    retry=retry_if_exception_type(_RetryableSSError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def fetch_recommendations(
    seed_dois: list[str], api_key: str | None = None, limit: int = DEFAULT_LIMIT
) -> list[dict]:
    """Query the SS Recommendations API with the seeds as positive examples.

    Args:
        seed_dois: Normalized DOIs of the seed papers.
        api_key: Optional Semantic Scholar key.
        limit: Number of recommendations requested (max 500).

    Returns:
        Raw SS paper dicts (``recommendedPapers``).
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    body = {
        "positivePaperIds": [
            f"DOI:{urllib.parse.quote(doi, safe='/')}" for doi in seed_dois
        ]
    }
    params = {"fields": SS_FIELDS, "limit": min(limit, MAX_RECOMMENDATIONS)}
    try:
        response = _rate_limited_post(headers, params, body)
    except requests.exceptions.RequestException as error:
        raise _RetryableSSError(str(error)) from error
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableSSError(f"HTTP {response.status_code}")
    response.raise_for_status()
    return response.json().get("recommendedPapers", [])


def recommendations_to_frame(raw_papers: list[dict]) -> pd.DataFrame:
    """Convert raw SS papers to a DataFrame in the internal format."""
    records = []
    for paper in raw_papers:
        if not paper:
            continue
        try:
            records.append(convert_ss_paper(paper))
        except Exception as error:
            logger.debug(f"Could not convert recommended paper: {error}")
    return pd.DataFrame(records)


def snowball_round(
    frame: pd.DataFrame,
    seed_dois: list[str],
    api_key: str | None,
    collect_dir: str,
) -> pd.DataFrame:
    """Add one snowball round on top of ``frame`` and the seeds.

    Fetches references and citers of the seeds and recommendations (cached in
    ``collect_dir``), ranks out-of-corpus candidates with the snowball module
    and appends their metadata.
    """
    from scilex.citations.reference_fetcher import (
        fetch_citers_batch,
        fetch_references_batch,
    )
    from scilex.snowball.candidates import extract_candidates
    from scilex.snowball.fetcher import fetch_metadata_batch

    recommended = (
        [d for d in frame["DOI"] if is_valid(d)] if "DOI" in frame.columns else []
    )
    corpus_dois = set(_unique_dois([*seed_dois, *recommended]))
    references = fetch_references_batch(
        sorted(corpus_dois),
        api_key=api_key,
        cache_path=os.path.join(collect_dir, "citations_cache.json"),
    )
    citers = fetch_citers_batch(
        sorted(corpus_dois),
        api_key=api_key,
        cache_path=os.path.join(collect_dir, "citers_cache.json"),
    )
    candidates = extract_candidates(
        references,
        citers,
        corpus_dois,
        top_k=SNOWBALL_TOP_K,
        min_frequency=SNOWBALL_MIN_FREQUENCY,
    )
    logger.info(f"Snowball: {len(candidates)} candidates")
    if not candidates:
        return frame
    papers = fetch_metadata_batch([doi for doi, _ in candidates], api_key=api_key)
    extra = pd.DataFrame(papers)
    return pd.concat([frame, extra], ignore_index=True)


def apply_filters(
    frame: pd.DataFrame,
    quality_filters: dict,
    keyword_groups: list | None = None,
    bonus_keywords: list | None = None,
) -> pd.DataFrame:
    """Apply the aggregation's quality, keyword and citation filters.

    The keyword filter only runs when ``keyword_groups`` is given.
    """
    from scilex.pipeline.citation_filter import apply_time_aware_citation_filter
    from scilex.pipeline.itemtype_filter import apply_itemtype_bypass
    from scilex.pipeline.text_filter import record_passes_text_filter
    from scilex.quality_validation import apply_quality_filters

    if frame.empty:
        return frame

    # Like the aggregation: trusted item types skip the quality filters.
    # Recommendations often carry truncated abstracts (~30 words), which the
    # 50-word minimum would otherwise reject wholesale.
    bypass_types = quality_filters.get("bypass_item_types", [])
    if quality_filters.get("enable_itemtype_bypass", False) and bypass_types:
        bypassed, others = apply_itemtype_bypass(frame, bypass_types)
    else:
        bypassed, others = frame.iloc[0:0], frame
    if len(others) > 0:
        others, _report = apply_quality_filters(others, quality_filters, False)
    frame = pd.concat([bypassed, others], ignore_index=True)

    if keyword_groups and len(frame) > 0:
        flat_keywords = [kw for group in keyword_groups for kw in group]
        mask = frame.apply(
            lambda row: record_passes_text_filter(
                row.to_dict(),
                flat_keywords,
                keyword_groups=keyword_groups,
                bonus_keywords=bonus_keywords,
            ),
            axis=1,
        )
        frame = frame[mask]
        logger.info(f"Keyword filter: {len(frame)} papers kept")

    if quality_filters.get("apply_citation_filter", True) and len(frame) > 0:
        # SS already returned citation counts: reuse them for the age-aware filter.
        counts = frame.get("ss_citation_count", pd.Series(0, index=frame.index))
        frame = frame.assign(nb_citation=pd.to_numeric(counts, errors="coerce"))
        frame = apply_time_aware_citation_filter(frame)
    return frame.reset_index(drop=True)


def run_seed(
    seed_dois: list[str],
    limit: int,
    api_key: str | None,
    quality_filters: dict,
    collect_dir: str,
    output_filename: str,
    keyword_groups: list | None = None,
    bonus_keywords: list | None = None,
    with_snowball: bool = False,
) -> tuple[str, pd.DataFrame]:
    """Run the full seed workflow and write the aggregated CSV.

    Returns:
        (output CSV path, filtered DataFrame).
    """
    raw = fetch_recommendations(seed_dois, api_key=api_key, limit=limit)
    logger.info(f"Recommendations: {len(raw)} papers")
    frame = recommendations_to_frame(raw)
    if with_snowball:
        os.makedirs(collect_dir, exist_ok=True)
        frame = snowball_round(frame, seed_dois, api_key, collect_dir)

    if not frame.empty and "DOI" in frame.columns:
        seed_set = set(seed_dois)
        frame = frame[~frame["DOI"].apply(lambda d: normalize_doi(d) in seed_set)]
        frame = frame.drop_duplicates(subset="DOI", keep="first")

    frame = apply_filters(frame, quality_filters, keyword_groups, bonus_keywords)
    os.makedirs(collect_dir, exist_ok=True)
    output_path = os.path.join(collect_dir, output_filename)
    write_aggregated_csv(frame, output_path)
    return output_path, frame


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find related papers from seed DOIs (Semantic Scholar Recommendations)"
    )
    parser.add_argument("--dois", nargs="+", default=[], help="Seed DOIs")
    parser.add_argument("--doi-file", help="Text file with one seed DOI per line")
    parser.add_argument("--bibtex", help="BibTeX file whose entries are the seeds")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Recommendations requested, max {MAX_RECOMMENDATIONS} "
        f"(default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--snowball",
        action="store_true",
        help="Complete with one snowball round (citations and references)",
    )
    parser.add_argument(
        "--keyword-filter",
        action="store_true",
        help="Also apply the keyword groups of scilex.config.yml",
    )
    parser.add_argument(
        "--collect-name",
        help="Output collection name (default: <collect_name>_seed from the config)",
    )
    add_config_arguments(parser)
    return parser


def _load_configs() -> tuple[dict, dict]:
    """Load main and API configs, tolerating a missing main config."""
    from scilex.pipeline_utils import load_main_and_api_configs

    try:
        return load_main_and_api_configs()
    except (FileNotFoundError, OSError) as error:
        if isinstance(error, ConfigFileNotFoundError) and (
            os.environ.get("SCILEX_CONFIG") or os.environ.get("SCILEX_KEYS")
        ):
            raise  # an explicitly requested file is missing: do not hide it
        logger.warning("Configuration files not found, using defaults")
        return {}, {}


@exit_on_config_error
def main():
    """Entry point for ``scilex-seed``."""
    setup_logging()
    args = _build_parser().parse_args()
    apply_config_arguments(args)

    try:
        raw_dois = list(args.dois)
        if args.doi_file:
            raw_dois += read_doi_file(args.doi_file)
        if args.bibtex:
            raw_dois += read_bibtex_dois(args.bibtex)
        seed_dois = _unique_dois(raw_dois)
        if not seed_dois:
            print("No valid seed DOI given (use --dois, --doi-file or --bibtex).")
            sys.exit(1)

        main_config, api_config = _load_configs()
        from scilex.config_defaults import get_default_quality_filters

        quality_filters = get_default_quality_filters()
        quality_filters.update((main_config or {}).get("quality_filters", {}))
        # Recommendations are not bound to the query years.
        quality_filters["validate_year_range"] = False

        base_name = (main_config or {}).get("collect_name")
        collect_name = normalize_path_component(
            args.collect_name
            or (
                f"{base_name}{DEFAULT_SEED_COLLECT_SUFFIX}"
                if base_name
                else FALLBACK_COLLECT_NAME
            )
        )
        output_dir = (main_config or {}).get("output_dir", DEFAULT_OUTPUT_DIR)
        collect_dir = os.path.join(output_dir, collect_name)
        output_filename = normalize_path_component(
            (main_config or {}).get("aggregate_file", DEFAULT_AGGREGATED_FILENAME)
        )

        api_key = ((api_config or {}).get("SemanticScholar") or {}).get("api_key")
        logger.info(f"{len(seed_dois)} seed papers")
        output_path, frame = run_seed(
            seed_dois,
            args.limit,
            api_key,
            quality_filters,
            collect_dir,
            output_filename,
            keyword_groups=(main_config or {}).get("keywords")
            if args.keyword_filter
            else None,
            bonus_keywords=(main_config or {}).get("bonus_keywords"),
            with_snowball=args.snowball,
        )
        print(f"\nSeed mode complete: {len(frame)} papers written to {output_path}")
    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as error:
        logger.error(f"File not found: {error}")
        sys.exit(1)
    except _RetryableSSError as error:
        # Expected without a key: no traceback, say what to do.
        logger.error(
            f"Semantic Scholar did not answer ({error}, after 4 attempts). "
            "Without an API key it rate-limits shared traffic: retry in a few "
            "minutes, or set SemanticScholar.api_key in keys.yml."
        )
        sys.exit(1)
    except Exception as error:
        logger.error(f"Error during seed mode: {error}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
