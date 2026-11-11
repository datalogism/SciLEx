"""
Parallel aggregation module for paper processing.

Processing stages:
1. Parallel file loading (ThreadPoolExecutor): Load JSON files, I/O bound
2. Parallel batch processing (ThreadPoolExecutor): Convert formats, apply filters
3. Deduplication (serial): DOI-based and normalized title matching (O(n))
"""

import itertools
import json
import logging
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from multiprocessing import cpu_count

import pandas as pd
from tqdm import tqdm

from scilex.constants import (
    MISSING_VALUE,
    QUERY_MARKER_FILES,
    extract_year,
    is_valid,
    normalize_doi,
    parse_archive_apis,
    split_semicolon_field,
)
from scilex.crawlers.aggregate import FORMAT_CONVERTERS
from scilex.pipeline.text_filter import record_passes_text_filter

# Raw (pre-conversion) year fields tried in order, covering all supported APIs:
#   SemanticScholar/DBLP → "year"
#   OpenAlex/IEEE/ORKG   → "publication_year"
#   Elsevier/Springer    → "coverDate"
#   Istex                → "publicationDate"
#   Arxiv                → "published"
#   HAL                  → "producedDate_tdate", "publicationDateY_i"
#   PubMed/PMC           → "PubDate" (nested dict — str() gives "{Year: '2023'...}")
_RAW_YEAR_FIELDS = (
    "year",
    "publication_year",
    "publicationYear",
    "coverDate",
    "publicationDate",
    "published",
    "date",
    "producedDate_tdate",
    "publicationDateY_i",
    "PubDate",
)


def _extract_raw_year(paper: dict) -> int | None:
    """Best-effort year extraction from a raw (unconverted) API paper dict.

    Returns None when year cannot be determined — callers treat that as
    'keep the paper' so we never drop papers with missing dates.
    """
    for field in _RAW_YEAR_FIELDS:
        year = extract_year(paper.get(field))
        if year is not None:
            return year
    return None


# ============================================================================
# HELPER FUNCTIONS: FILESYSTEM DISCOVERY & QUERY RECONSTRUCTION
# ============================================================================


def discover_api_directories(dir_collect: str) -> dict[str, list[str]]:
    """
    Discover API directories and query indices from filesystem.

    Scans the collection directory to find:
    - API subdirectories (e.g., SemanticScholar, OpenAlex)
    - Query index subdirectories within each API (e.g., 0, 1, 2)

    Args:
        dir_collect: Base collection directory path

    Returns:
        Dictionary mapping API names to sorted query index lists
        Example: {"SemanticScholar": ["0", "1", "2"], "OpenAlex": ["0", "1"]}
    """
    _SKIP_NAMES = {
        "config_used.yml",
        "citation_cache.db",
        "abstract_cache.db",
        "abstract_cache.json",
        "abstract_cache.json.migrated",
        "chart_aggregated_papers",
    }

    api_to_queries = {}

    if not os.path.exists(dir_collect):
        logging.warning(f"Collection directory not found: {dir_collect}")
        return api_to_queries

    try:
        top_entries = list(os.scandir(dir_collect))
    except PermissionError:
        logging.warning(f"Permission denied accessing: {dir_collect}")
        return api_to_queries

    for api_entry in top_entries:
        if not api_entry.is_dir(follow_symlinks=False):
            continue
        if api_entry.name in _SKIP_NAMES:
            continue

        query_indices = []
        try:
            for q_entry in os.scandir(api_entry.path):
                if not q_entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    int(q_entry.name)
                    query_indices.append(q_entry.name)
                except ValueError:
                    continue
        except PermissionError:
            logging.warning(f"Permission denied accessing: {api_entry.path}")
            continue

        if query_indices:
            query_indices.sort(key=int)
            api_to_queries[api_entry.name] = query_indices

    logging.info(
        f"Discovered {len(api_to_queries)} APIs with "
        f"{sum(len(q) for q in api_to_queries.values())} total queries"
    )

    return api_to_queries


def reconstruct_query_to_keywords_mapping(
    config_used: dict,
) -> dict[str, dict[str, list[str]]]:
    """
    Reconstruct query index → keywords mapping from config_used.yml.

    Reproduces the same cartesian product used during collection to map
    query indices to their corresponding keyword combinations.

    Args:
        config_used: Configuration dictionary from config_used.yml

    Returns:
        Nested dictionary mapping API → query_index → keywords
        Example: {
            "SemanticScholar": {
                "0": ["LLM", "Knowledge Graph"],
                "1": ["LLM", "knowledge graphs"],
                ...
            },
            "OpenAlex": {...}
        }
    """
    # Extract configuration
    keywords = config_used.get("keywords", [[]])
    years = config_used.get("years", [])
    apis = config_used.get("apis", [])

    # Step 1: Generate keyword combinations (same logic as queryCompositor).
    # Each combination is the keyword list recorded for the query.
    keyword_combinations: list[list[str]] = []
    if len(keywords) == 2 and len(keywords[0]) > 0 and len(keywords[1]) > 0:
        # Dual keyword mode: cartesian product of both groups
        keyword_combinations = [
            list(pair) for pair in itertools.product(keywords[0], keywords[1])
        ]
    elif (len(keywords) == 2 and len(keywords[0]) > 0 and len(keywords[1]) == 0) or (
        len(keywords) == 1 and len(keywords[0]) > 0
    ):
        # Single keyword mode: each keyword is wrapped in its own list
        keyword_combinations = [[keyword] for keyword in keywords[0]]

    logging.debug(f"Reconstructed {len(keyword_combinations)} keyword combinations")

    # Step 2: Cartesian product (keywords × years × apis), grouped by API.
    # The per-API enumeration index is the query index used on disk.
    mapping: dict[str, dict[str, list[str]]] = {}
    for keyword_group, _year, api in itertools.product(
        keyword_combinations, years, apis
    ):
        api_queries = mapping.setdefault(api, {})
        api_queries[str(len(api_queries))] = keyword_group

    logging.debug(
        f"Reconstructed mapping for {len(mapping)} APIs with "
        f"{sum(len(q) for q in mapping.values())} total query indices"
    )

    return mapping


# ============================================================================
# PHASE 1: PARALLEL FILE LOADING
# ============================================================================


def _load_json_file(
    file_path: str,
    api_name: str,
    keywords: list[str],
    year_range: frozenset[int] | None = None,
) -> tuple[list[dict], str, list[str], int]:
    """
    Load a single JSON file and return its papers.

    Args:
        file_path: Path to JSON file
        api_name: API name (e.g., 'SemanticScholar')
        keywords: List of keywords for this query
        year_range: Optional set of allowed publication years. Papers whose year
                    can be determined AND falls outside the set are dropped here,
                    before they enter the aggregation pipeline. Papers with an
                    unreadable year field are kept (conservative).

    Returns:
        Tuple of (papers_list, api_name, keywords, num_papers)
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        papers = data.get("results", [])

        if year_range:
            papers = [
                p
                for p in papers
                if (y := _extract_raw_year(p)) is None or y in year_range
            ]

        return (papers, api_name, keywords, len(papers))

    except Exception as e:
        # Covers json.JSONDecodeError (a ValueError) as well as I/O errors.
        logging.error(f"Error loading {file_path}: {e}")
        return ([], api_name, keywords, 0)


def parallel_load_all_files(
    dir_collect: str,
    config_used: dict,
    num_workers: int | None = None,
    year_range: frozenset[int] | None = None,
) -> tuple[list[tuple[dict, str, list[str]]], dict]:
    """
    Load all JSON files in parallel using threading.

    Args:
        dir_collect: Base collection directory path
        config_used: Configuration dictionary from config_used.yml
        num_workers: Number of parallel workers (default: cpu_count * 4, clamped 8–64)
        year_range: Optional frozenset of allowed publication years. Applied to raw
                    papers during loading so out-of-range papers never enter memory.

    Returns:
        Tuple of:
        - List of (paper_dict, api_name, keywords) tuples
        - Statistics dictionary
    """
    if num_workers is None:
        # I/O-bound threading scales well beyond cpu_count. On WSL2 (cross-filesystem
        # NTFS latency ~200 ms/file) we need many threads to hide the latency.
        # Default: 4 × CPU cores, clamped to [8, 64].
        cpus = cpu_count() or 1
        num_workers = max(8, min(cpus * 4, 64))

    logging.info(f"Parallel file loading with {num_workers} workers (threading)")

    # Collect all file paths and metadata
    file_tasks = []

    # Step 1: Discover API directories and query indices from filesystem
    api_to_queries = discover_api_directories(dir_collect)

    # Step 2: Reconstruct query → keywords mapping from config
    query_to_keywords = reconstruct_query_to_keywords_mapping(config_used)

    # Step 3: Collect file tasks using reconstructed mapping
    for api_name in api_to_queries:
        # Skip APIs not in reconstructed mapping (shouldn't happen, but defensive)
        if api_name not in query_to_keywords:
            logging.warning(
                f"API '{api_name}' found in filesystem but not in config reconstruction. Skipping."
            )
            continue

        for query_index in api_to_queries[api_name]:
            # Get keywords for this query index
            keywords = query_to_keywords[api_name].get(query_index, [])

            if not keywords:
                logging.warning(
                    f"No keywords found for {api_name}/query_{query_index}. Using empty list."
                )

            # Get directory for this API/query combination
            query_dir = os.path.join(dir_collect, api_name, query_index)

            if not os.path.exists(query_dir):
                continue

            # Collect all result pages (skip _complete/_state markers: a partial
            # collection has _state, which is not JSON)
            try:
                for f_entry in os.scandir(query_dir):
                    if f_entry.name in QUERY_MARKER_FILES:
                        continue
                    if f_entry.is_file(follow_symlinks=False):
                        file_tasks.append((f_entry.path, api_name, keywords))
            except PermissionError:
                logging.warning(f"Permission denied scanning: {query_dir}")

    n_files = len(file_tasks)
    logging.info(f"Found {n_files} JSON files to load")
    if year_range:
        logging.info(
            f"Year-range filter active at load time: {sorted(year_range)} "
            f"— out-of-range papers dropped before entering memory"
        )
    if n_files > 10_000:
        logging.info(
            f"Large collection ({n_files:,} files). Using {num_workers} load workers. "
            f"Pass --load-workers N (e.g. 32–64) to speed up loading on slow filesystems."
        )

    # Load files in parallel with progress bar.
    # Submit in chunks so the internal future-set and result memory stay bounded.
    # Without chunking, submitting 73K futures at once causes as_completed's internal
    # tracking set to balloon and the intermediate results list holds all raw JSON
    # simultaneously — several GB before papers_by_api is even built.
    _SUBMIT_CHUNK = 2_000

    start_time = time.time()
    papers_by_api = []
    total_papers = 0
    papers_per_api: dict[str, int] = {}

    with (
        ThreadPoolExecutor(max_workers=num_workers) as executor,
        tqdm(total=n_files, desc="Loading JSON files", unit="file") as pbar,
    ):
        for chunk_start in range(0, n_files, _SUBMIT_CHUNK):
            chunk = file_tasks[chunk_start : chunk_start + _SUBMIT_CHUNK]
            futures = [
                executor.submit(_load_json_file, fp, api, kw, year_range)
                for fp, api, kw in chunk
            ]
            for future in as_completed(futures):
                papers_list, api_name, keywords, num_papers = future.result()
                total_papers += num_papers
                papers_per_api[api_name] = papers_per_api.get(api_name, 0) + num_papers
                for paper in papers_list:
                    papers_by_api.append((paper, api_name, keywords))
                pbar.update(1)
            # futures list goes out of scope here → GC can reclaim completed Future objects

    elapsed = time.time() - start_time

    # Statistics
    stats = {
        "files_loaded": n_files,
        "total_papers": total_papers,
        "per_api": papers_per_api,
        "elapsed_seconds": elapsed,
        "files_per_second": n_files / elapsed if elapsed > 0 else 0,
        "papers_per_second": total_papers / elapsed if elapsed > 0 else 0,
    }

    logging.info(
        f"Loaded {total_papers:,} papers from {n_files} files in {elapsed:.1f}s"
    )
    logging.info(
        f"Throughput: {stats['files_per_second']:.1f} files/sec, {stats['papers_per_second']:.1f} papers/sec"
    )

    return papers_by_api, stats


# ============================================================================
# PHASE 2: PARALLEL BATCH PROCESSING
# ============================================================================


def _process_batch(
    batch: list[tuple[dict, str, list[str]]],
    keyword_groups: list[list[str]] | None = None,
    bonus_keywords: list[str] | None = None,
    cached_abstracts: dict[str, str] | None = None,
    pre_filters: dict | None = None,
    apply_text_filter: bool = True,
) -> tuple[list[dict], Counter]:
    """Convert and filter one batch, counting converter failures per API.

    Args:
        batch: (raw paper dict, API name, keywords used) triples.
        keyword_groups: keyword groups for the text filter.
        bonus_keywords: optional bonus keywords for the text filter.
        cached_abstracts: optional DOI → abstract dict (cache-only mode).
        pre_filters: optional dict with early rejection criteria applied right
                     after format conversion, before the more expensive text
                     filter.  Supported keys:
                       "year_range"         – set[int] of allowed years;
                                              papers with an unknown date are
                                              kept (conservative).
                       "allowed_item_types" – set[str] of allowed itemType
                                              values; empty set = no filter.
        apply_text_filter: when False, papers are only converted (and
                     pre-filtered), never keyword-filtered. Defaults to True.

    Returns:
        Tuple of (processed paper dicts, per-API converter error counts)
    """
    year_range: set[int] = (pre_filters or {}).get("year_range", set())
    allowed_item_types: set[str] = (pre_filters or {}).get("allowed_item_types", set())

    results = []
    converter_errors: Counter = Counter()

    for paper, api_name, keywords in batch:
        if api_name not in FORMAT_CONVERTERS:
            logging.warning(
                f"No format converter found for API: {api_name}. "
                f"Available converters: {list(FORMAT_CONVERTERS.keys())}"
            )
            continue

        try:
            converted = FORMAT_CONVERTERS[api_name](paper)

            # Inject cached abstract when abstract is missing and cache is provided
            if cached_abstracts and not is_valid(converted.get("abstract")):
                doi = converted.get("DOI")
                if is_valid(doi):
                    doi_key = normalize_doi(doi)
                    cached = cached_abstracts.get(doi_key)
                    if cached:
                        converted["abstract"] = cached

            # ── Early filters (cheap field checks before expensive text search) ──

            # Year range: skip papers outside allowed years.
            # Papers with unknown/missing dates are kept (conservative).
            if year_range:
                year = extract_year(converted.get("date"))
                if year is not None and year not in year_range:
                    continue

            # ItemType whitelist: skip disallowed publication types.
            if allowed_item_types:
                item_type = str(converted.get("itemType", "")).strip()
                if item_type and item_type not in allowed_item_types:
                    continue

            # Tag paper with the keywords used to retrieve it
            if keywords:
                kw_tags = ";".join(
                    f"Collect_KW{i + 1}:{kw}" for i, kw in enumerate(keywords)
                )
                converted["collect_keywords"] = kw_tags
            else:
                converted["collect_keywords"] = ""

            if not apply_text_filter or record_passes_text_filter(
                converted,
                keywords,
                keyword_groups=keyword_groups,
                bonus_keywords=bonus_keywords,
            ):
                results.append(converted)

        except Exception as e:
            converter_errors[api_name] += 1
            logging.debug(f"Error converting paper from {api_name}: {e}")

    return results, converter_errors


def parallel_process_papers(
    papers_by_api: list[tuple[dict, str, list[str]]],
    batch_size: int = 5000,
    num_workers: int | None = None,
    keyword_groups: list | None = None,
    bonus_keywords: list | None = None,
    cached_abstracts: dict | None = None,
    pre_filters: dict | None = None,
    apply_text_filter: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Process papers in parallel batches (convert format + text filtering).

    Args:
        papers_by_api: List of (paper_dict, api_name, keywords) tuples
        batch_size: Papers per batch
        num_workers: Number of parallel workers
        keyword_groups: Optional list of keyword groups from config (for dual-group mode)
        bonus_keywords: Optional list of bonus keywords used as flexible Group 2 fallback
        cached_abstracts: Optional DOI → abstract dict (cache-only mode).
        pre_filters: Optional dict with early rejection criteria (year_range,
                     allowed_item_types).  Applied before text filtering to
                     reduce the number of papers that reach expensive stages.
        apply_text_filter: When False, papers are converted but not keyword-filtered.

    Returns:
        Tuple of:
        - DataFrame with processed papers
        - Statistics dictionary (includes ``converter_errors``: API → number
          of papers whose format conversion raised)
    """
    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)

    logging.info(
        f"Parallel batch processing with {num_workers} workers, batch size {batch_size}"
    )

    if pre_filters:
        active = [k for k, v in pre_filters.items() if v]
        logging.info(f"Early filters active in batch workers: {', '.join(active)}")

    # Split into batches
    batches = []
    for i in range(0, len(papers_by_api), batch_size):
        batch = papers_by_api[i : i + batch_size]
        batches.append(batch)

    logging.info(f"Processing {len(papers_by_api):,} papers in {len(batches)} batches")

    process_one_batch = partial(
        _process_batch,
        keyword_groups=keyword_groups,
        bonus_keywords=bonus_keywords,
        cached_abstracts=cached_abstracts,
        pre_filters=pre_filters,
        apply_text_filter=apply_text_filter,
    )

    # Process batches in parallel
    start_time = time.time()
    all_results = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = list(
            tqdm(
                executor.map(process_one_batch, batches),
                total=len(batches),
                desc="Processing papers",
                unit="batch",
            )
        )

    # Flatten results and merge per-API converter error counts
    converter_errors: Counter = Counter()
    for batch_results, batch_errors in results:
        all_results.extend(batch_results)
        converter_errors.update(batch_errors)

    for api_name, n_errors in sorted(converter_errors.items()):
        logging.warning(
            f"{api_name}: {n_errors:,} paper(s) dropped because format conversion "
            f"raised an error (run with LOG_LEVEL=DEBUG for details)"
        )

    elapsed = time.time() - start_time

    # Create DataFrame
    df = pd.DataFrame(all_results)

    # Statistics
    stats = {
        "papers_processed": len(papers_by_api),
        "papers_filtered": len(df),
        "papers_rejected": len(papers_by_api) - len(df),
        "rejection_rate": (len(papers_by_api) - len(df)) / len(papers_by_api)
        if len(papers_by_api) > 0
        else 0,
        "elapsed_seconds": elapsed,
        "papers_per_second": len(papers_by_api) / elapsed if elapsed > 0 else 0,
        "converter_errors": dict(converter_errors),
    }

    logging.info(f"Processed {len(papers_by_api):,} papers in {elapsed:.1f}s")
    logging.info(
        f"Filtered: {len(df):,} papers ({stats['rejection_rate'] * 100:.1f}% rejected)"
    )
    logging.info(f"Throughput: {stats['papers_per_second']:.1f} papers/sec")

    return df, stats


# ============================================================================
# PHASE 3: SIMPLE HASH-BASED DEDUPLICATION
# ============================================================================


def _merge_collect_keywords(kw_strings: list[str]) -> str:
    """Merge collect_keywords strings from duplicate records into one deduplicated set.

    Args:
        kw_strings: List of semicolon-separated keyword-tag strings
                    (e.g. ["Collect_KW1:AI;Collect_KW2:Survey", "Collect_KW1:ML"])

    Returns:
        Single semicolon-separated string of unique tags in insertion order
    """
    seen: dict[str, None] = {}
    for kw_str in kw_strings:
        if kw_str:
            for tag in split_semicolon_field(kw_str):
                seen[tag] = None
    return ";".join(seen.keys())


def _compute_dedup_quality(df: pd.DataFrame) -> pd.Series:
    """Fast metadata completeness score for dedup selection.

    Computes a lightweight quality score per row based on whether key fields
    contain valid (non-missing) values. Used to sort duplicates so that
    `drop_duplicates(keep="first")` keeps the most complete record.

    Args:
        df: DataFrame with paper records.

    Returns:
        Series of integer scores (higher = more complete metadata).
    """
    score = pd.Series(0, index=df.index)
    for field, weight in [
        ("DOI", 5),
        ("abstract", 3),
        ("authors", 3),
        ("date", 2),
        ("journalAbbreviation", 1),
        ("url", 1),
        ("pdf_url", 1),
    ]:
        if field in df.columns:
            score += df[field].apply(is_valid).astype(int) * weight
    return score


def _merge_archives_for_duplicates(archives: list[str], winner_archive: str) -> str:
    """Merge archive list with winner marked by asterisk.

    Args:
        archives: List of archive names (e.g., ["SemanticScholar", "OpenAlex"])
        winner_archive: The archive that was kept after dedup

    Returns:
        Merged string like "SemanticScholar*;OpenAlex" where * marks the winner
    """
    unique_archives = list(dict.fromkeys(archives))  # Preserve order, remove dupes
    return ";".join([a + "*" if a == winner_archive else a for a in unique_archives])


_WINNER_COLUMN = "_winner_archive"


def _dedup_by_key(
    df: pd.DataFrame, key_col: str, is_valid_key=is_valid
) -> tuple[pd.DataFrame, int]:
    """Drop duplicates on `key_col`, keeping the best record and merging provenance.

    Rows are expected to carry `_dedup_quality` (best record is kept) and
    `_winner_archive` (the API the kept record originally came from, so the
    winner star stays correct across successive dedup passes). Rows whose key
    is not valid are passed through untouched.

    For each group of duplicates:
    - `archive` becomes the merged list with the winner starred ("A*;B");
    - `collect_keywords` (if present) becomes the union of all query tags.

    Args:
        df: DataFrame to deduplicate.
        key_col: Column holding the dedup key (e.g. "DOI", "title_normalized").
        is_valid_key: Predicate telling whether a key value is usable.

    Returns:
        Tuple of (deduplicated DataFrame, number of rows removed).
    """
    if df.empty or key_col not in df.columns:
        return df, 0

    valid_mask = df[key_col].apply(is_valid_key).astype(bool)
    keyed = df[valid_mask]
    unkeyed = df[~valid_mask]
    if keyed.empty:
        return df, 0

    groups = keyed.groupby(key_col, sort=False)
    group_sizes = groups.size().to_dict()
    key_to_archives = groups["archive"].apply(list).to_dict()
    key_to_keywords = (
        groups["collect_keywords"].apply(list).to_dict()
        if "collect_keywords" in keyed.columns
        else None
    )

    # Best record first so drop_duplicates(keep="first") keeps it
    kept = keyed.sort_values("_dedup_quality", ascending=False).drop_duplicates(
        subset=[key_col], keep="first"
    )
    removed = len(keyed) - len(kept)

    merged_archives = []
    for key, own_archive, winner in zip(
        kept[key_col], kept["archive"], kept[_WINNER_COLUMN], strict=True
    ):
        names = [n for cell in key_to_archives[key] for n in parse_archive_apis(cell)]
        names = list(dict.fromkeys(names))
        if group_sizes[key] > 1 or len(names) > 1:
            merged_archives.append(
                _merge_archives_for_duplicates(names, winner) if names else own_archive
            )
        else:
            merged_archives.append(own_archive)
    kept = kept.copy()
    kept["archive"] = merged_archives

    if key_to_keywords is not None:
        kept["collect_keywords"] = [
            _merge_collect_keywords(key_to_keywords[key]) for key in kept[key_col]
        ]

    return pd.concat([kept, unkeyed], ignore_index=True), removed


def simple_deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Simple, fast deduplication using hash-based exact matching.

    Strategy:
    1. DOI-based dedup (hash set, O(n))
    2. Normalized title dedup (hash dict, O(n))
    3. Exact substring matching only (fast, sufficient for most cases)

    Normalization:
    - Lowercase
    - Strip whitespace
    - Remove punctuation
    - Examples:
      * "Machine Learning!" → "machine learning"
      * "Deep Learning  " → "deep learning"

    Args:
        df: DataFrame with papers to deduplicate

    Returns:
        Tuple of:
        - Deduplicated DataFrame
        - Statistics dictionary
    """
    logging.info(f"Starting simple deduplication on {len(df):,} papers")
    start_time = time.time()

    initial_count = len(df)
    df_output = df.copy()

    # Temporary bookkeeping columns, dropped before returning:
    # - quality: sort key so "first" duplicate = most complete record
    # - winner: API of the record that survives, tracked explicitly so that the
    #   archive star stays right when DOI and title merges stack up
    df_output["_dedup_quality"] = _compute_dedup_quality(df_output)
    added_archive_column = "archive" not in df_output.columns
    if added_archive_column:
        df_output["archive"] = MISSING_VALUE
    df_output[_WINNER_COLUMN] = df_output["archive"].apply(
        lambda cell: (parse_archive_apis(cell) or [None])[0]
    )

    # STEP 1: DOI-based deduplication
    df_output, doi_removed = _dedup_by_key(df_output, "DOI")
    logging.info(f"DOI deduplication: removed {doi_removed:,} duplicates")

    # STEP 2: Normalized title deduplication
    if "title" in df_output.columns:
        df_output["title_normalized"] = (
            df_output["title"]
            .fillna("")
            .astype(str)
            .str.lower()
            .str.strip()
            .str.replace(r"[^\w\s]", "", regex=True)  # Remove punctuation
            .str.replace(r"\s+", " ", regex=True)  # Normalize whitespace
        )
        df_output, title_removed = _dedup_by_key(
            df_output, "title_normalized", is_valid_key=lambda title: title != ""
        )
        df_output = df_output.drop(columns=["title_normalized"])
    else:
        title_removed = 0
    logging.info(f"Title deduplication: removed {title_removed:,} duplicates")

    # Final statistics
    elapsed = time.time() - start_time
    final_count = len(df_output)
    total_removed = initial_count - final_count

    stats = {
        "initial_count": initial_count,
        "final_count": final_count,
        "total_removed": total_removed,
        "removal_rate": total_removed / initial_count if initial_count > 0 else 0,
        "doi_removed": doi_removed,
        "title_removed": title_removed,
        "elapsed_seconds": elapsed,
        "papers_per_second": initial_count / elapsed if elapsed > 0 else 0,
    }

    logging.info(
        f"Deduplication complete: {initial_count:,} → {final_count:,} papers ({total_removed:,} removed, {stats['removal_rate'] * 100:.1f}%)"
    )
    logging.info(
        f"Deduplication took {elapsed:.2f}s ({stats['papers_per_second']:.1f} papers/sec)"
    )

    temporary_columns = ["_dedup_quality", _WINNER_COLUMN]
    if added_archive_column:
        temporary_columns.append("archive")
    df_output = df_output.drop(columns=temporary_columns)
    return df_output, stats


# ============================================================================
# MAIN PARALLEL AGGREGATION FUNCTION
# ============================================================================


def parallel_aggregate(
    dir_collect: str,
    config_used: dict,
    txt_filters: bool = True,
    num_workers: int | None = None,
    batch_size: int = 5000,
    keyword_groups: list | None = None,
    load_workers: int | None = None,
    bonus_keywords: list | None = None,
    cached_abstracts: dict | None = None,
    pre_filters: dict | None = None,
    since_collect_dirs: list[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Main parallel aggregation function (orchestrates all phases).

    Args:
        dir_collect: Base collection directory
        config_used: Configuration dictionary from config_used.yml
        txt_filters: Enable keyword text filtering; when False papers are only
            converted (early pre_filters still apply)
        num_workers: Number of parallel workers for batch processing
        batch_size: Papers per batch
        keyword_groups: Optional list of keyword groups from config (for dual-group mode)
        load_workers: Number of parallel workers for file loading (default: 4)
        bonus_keywords: Optional list of bonus keywords used as flexible Group 2 fallback
        since_collect_dirs: Optional ``<collect>_since_<date>`` directories merged into
            the collection (date post-filtered; overlaps removed by deduplication)

    Returns:
        Tuple of:
        - Aggregated and deduplicated DataFrame
        - Combined statistics dictionary
    """
    logging.info("=" * 70)
    logging.info("PARALLEL AGGREGATION STARTED")
    logging.info("=" * 70)

    overall_start = time.time()
    combined_stats = {}

    # ========================================================================
    # PHASE 1: PARALLEL FILE LOADING
    # ========================================================================

    logging.info("\n--- Phase 1: Parallel File Loading ---")
    # Extract year_range from pre_filters so it can be applied at load time —
    # papers outside the range are dropped before entering memory.
    load_year_range: frozenset[int] | None = None
    if pre_filters and pre_filters.get("year_range"):
        load_year_range = frozenset(pre_filters["year_range"])

    papers_by_api, load_stats = parallel_load_all_files(
        dir_collect,
        config_used=config_used,
        num_workers=load_workers,
        year_range=load_year_range,
    )
    combined_stats["loading"] = load_stats

    if since_collect_dirs:
        from scilex.since_utils import load_since_collection_papers

        for since_dir in since_collect_dirs:
            since_papers = load_since_collection_papers(since_dir)
            papers_by_api.extend(since_papers)
            load_stats["total_papers"] += len(since_papers)
            per_api = load_stats.setdefault("per_api", {})
            for _paper, api_name, _kw in since_papers:
                per_api[api_name] = per_api.get(api_name, 0) + 1

    if not papers_by_api:
        logging.error("No papers loaded. Check collection directory and state file.")
        return pd.DataFrame(), combined_stats

    # ========================================================================
    # PHASE 2: PARALLEL BATCH PROCESSING
    # ========================================================================

    logging.info(
        "\n--- Phase 2: Parallel Batch Processing "
        + ("(with text filtering) ---" if txt_filters else "(no text filtering) ---")
    )
    df, process_stats = parallel_process_papers(
        papers_by_api,
        batch_size=batch_size,
        num_workers=num_workers,
        keyword_groups=keyword_groups,
        bonus_keywords=bonus_keywords,
        cached_abstracts=cached_abstracts,
        pre_filters=pre_filters,
        apply_text_filter=txt_filters,
    )
    combined_stats["processing"] = process_stats

    if df.empty:
        logging.warning("No papers after processing. Check filtering criteria.")
        return df, combined_stats

    # ========================================================================
    # PHASE 3: SIMPLE DEDUPLICATION
    # ========================================================================

    logging.info("\n--- Phase 3: Simple Hash-Based Deduplication ---")
    df_dedup, dedup_stats = simple_deduplicate(df)
    combined_stats["deduplication"] = dedup_stats

    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================

    overall_elapsed = time.time() - overall_start
    combined_stats["overall"] = {
        "total_elapsed_seconds": overall_elapsed,
        "papers_loaded": load_stats["total_papers"],
        "papers_after_filtering": len(df),
        "papers_final": len(df_dedup),
        "overall_throughput": load_stats["total_papers"] / overall_elapsed
        if overall_elapsed > 0
        else 0,
    }

    logging.info("\n" + "=" * 70)
    logging.info("PARALLEL AGGREGATION COMPLETE")
    logging.info("=" * 70)
    logging.info(
        f"Total time: {overall_elapsed:.1f}s ({overall_elapsed / 60:.1f} minutes)"
    )
    logging.info(f"Papers loaded: {load_stats['total_papers']:,}")
    logging.info(f"Papers after filtering: {len(df):,}")
    logging.info(f"Papers after deduplication: {len(df_dedup):,}")
    logging.info(
        f"Overall throughput: {combined_stats['overall']['overall_throughput']:.1f} papers/sec"
    )
    logging.info("=" * 70 + "\n")

    return df_dedup, combined_stats
