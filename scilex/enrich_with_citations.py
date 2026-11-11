"""Enrich aggregated papers with citation data and re-export to BibTeX.

For each paper with a valid DOI, fetches:
- **Outgoing references** (what the paper cites) → ``references`` BibTeX field
  → ``bibo:cites`` triples in RDF.
- **Incoming citers** (who cites the paper) → ``cited_by`` BibTeX field
  → ``bibo:citedBy`` triples in RDF.

Usage:
    scilex-enrich-citations [--limit N] [--no-fallback] [--skip-citers]

The output is written to:
    {output_dir}/{collect_name}/aggregated_results_with_citations.bib
"""

import argparse
import logging
import os
import sys
import time

from scilex.citations.reference_fetcher import (
    fetch_citers_batch,
    fetch_references_batch,
)
from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import is_valid, normalize_path_component
from scilex.crawlers.key_pool import first_key
from scilex.export_to_bibtex import (
    BIBTEX_CITATIONS_FILENAME,
    format_bibtex_entry,
    generate_citation_key,
    safe_get,
)
from scilex.io_utils import load_aggregated_data
from scilex.logging_config import setup_logging
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.resolve import resolve_legacy_configs
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError

setup_logging()
logger = logging.getLogger(__name__)


def load_config() -> tuple[dict, dict]:
    """Load scilex.config.yml and api.config.yml."""
    return resolve_legacy_configs()


@exit_on_config_error
def main():
    """Entry point for citation enrichment."""
    parser = argparse.ArgumentParser(
        description="Enrich BibTeX output with reference DOIs via SemanticScholar"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of papers to process",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable OpenCitations fallback when SemanticScholar returns nothing",
    )
    parser.add_argument(
        "--skip-citers",
        action="store_true",
        help="Skip fetching incoming citers (cited_by field / bibo:citedBy triples)",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    try:
        main_config, api_config = load_config()

        if "collect_name" not in main_config:
            raise ValueError("collect_name not specified in scilex.config.yml")

        output_dir = main_config.get("output_dir", DEFAULT_OUTPUT_DIR)
        collect_name = normalize_path_component(main_config["collect_name"])
        collect_dir = os.path.join(output_dir, collect_name)
        os.makedirs(collect_dir, exist_ok=True)

        # Load paper data
        data = load_aggregated_data(main_config)
        logger.info(f"Loaded {len(data)} papers")

        # Apply limit
        if args.limit:
            data = data.head(args.limit)
            logger.info(f"Limited to {len(data)} papers")

        # Extract valid DOIs
        dois_all = []
        for row in data.itertuples(index=False):
            doi = safe_get(row, "DOI")
            dois_all.append(str(doi).strip() if is_valid(doi) else "")

        dois_valid = [d for d in dois_all if d]
        skipped_no_doi = dois_all.count("")
        logger.info(f"DOIs: {len(dois_valid)} valid, {skipped_no_doi} missing")

        # Get SS API key
        ss_api_key = first_key(api_config.get("SemanticScholar", {}).get("api_key"))
        if ss_api_key:
            logger.info("SemanticScholar API key found")
        else:
            logger.info("No SS API key — using 1 req/sec public rate limit")

        # Get CrossRef mailto for polite pool
        crossref_mailto = api_config.get("CrossRef", {}).get("mailto")
        if crossref_mailto:
            logger.info(f"CrossRef mailto configured: {crossref_mailto}")

        start = time.time()

        # Fetch outgoing references
        ref_cache = os.path.join(collect_dir, "citations_cache.json")
        ref_map = fetch_references_batch(
            dois_valid,
            api_key=ss_api_key,
            cache_path=ref_cache,
            fallback_opencitations=not args.no_fallback,
            mailto=crossref_mailto,
        )

        # Fetch incoming citers
        citer_map: dict[str, list[str]] = {}
        if not args.skip_citers:
            citer_cache = os.path.join(collect_dir, "citers_cache.json")
            citer_map = fetch_citers_batch(
                dois_valid,
                api_key=ss_api_key,
                cache_path=citer_cache,
                fallback_opencitations=not args.no_fallback,
            )

        elapsed = time.time() - start

        # Re-export BibTeX with references + cited_by fields
        output_file = os.path.join(collect_dir, BIBTEX_CITATIONS_FILENAME)
        entries = []
        used_keys: set = set()
        n_enriched = 0
        n_empty = 0
        n_cited_by = 0

        for doi_raw, row in zip(dois_all, data.itertuples(index=False), strict=True):
            citation_key = generate_citation_key(doi_raw, row, used_keys)
            refs = ref_map.get(doi_raw, []) if doi_raw else []
            citers = citer_map.get(doi_raw, []) if doi_raw else []

            entry = format_bibtex_entry(
                row, citation_key, references=refs, cited_by=citers
            )
            entries.append(entry)

            if refs:
                n_enriched += 1
            else:
                n_empty += 1
            if citers:
                n_cited_by += 1

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(entries))
            f.write("\n")

        separator = "=" * 60
        logger.info(
            "\n".join(
                [
                    separator,
                    "Citation Enrichment Summary",
                    separator,
                    f"Total papers:        {len(data)}",
                    f"With references:     {n_enriched}",
                    f"Empty references:    {n_empty}",
                    f"With citers:         {n_cited_by}",
                    f"Skipped (no DOI):    {skipped_no_doi}",
                    f"Elapsed:             {elapsed:.1f}s",
                    f"Output:              {output_file}",
                    separator,
                ]
            )
        )
        print(f"\nBibTeX with citations: {output_file}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during citation enrichment: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
