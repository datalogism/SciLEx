import logging
import os
import threading
from collections import defaultdict
from itertools import product
from queue import Empty, Queue

import yaml
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import MISSING_VALUE
from scilex.vpn.rotator import vpn_config_from_configs

from .collectors import (
    Arxiv_collector,
    BioRxiv_collector,
    DBLP_collector,
    Elsevier_collector,
    HAL_collector,
    IEEE_collector,
    Istex_collector,
    OpenAIRE_collector,
    OpenAlex_collector,
    ORKG_collector,
    PubMed_collector,
    PubMedCentral_collector,
    SemanticScholar_collector,
    Springer_collector,
)
from .collectors.base import COMPLETE_FILE_NAME, STATE_FILE_NAME
from .utils import sanitize_secrets

api_collectors = {
    "DBLP": DBLP_collector,
    "Arxiv": Arxiv_collector,
    "BioRxiv": BioRxiv_collector,
    "Elsevier": Elsevier_collector,
    "IEEE": IEEE_collector,
    "Springer": Springer_collector,
    "SemanticScholar": SemanticScholar_collector,
    "OpenAlex": OpenAlex_collector,
    "HAL": HAL_collector,
    "Istex": Istex_collector,
    "PubMed": PubMed_collector,
    "PubMedCentral": PubMedCentral_collector,
    "OpenAIRE": OpenAIRE_collector,
    "ORKG": ORKG_collector,
}


# Placeholder values that mean "no institutional token configured"
# (any "YOUR_..." placeholder is rejected separately).
_INVALID_INST_TOKENS = {MISSING_VALUE, "TODO", "", None}

# Thread worker function (processes all queries for one API)


def _run_job_collects_worker(
    api_name,
    collect_list,
    api_config,
    output_dir,
    collect_name,
    progress_queue,
    cancel_event=None,
    vpn_config=None,
):
    """
    Thread worker function for one API.
    Processes all queries for the assigned API and sends progress updates via queue.

    Args:
        api_name: Name of the API (e.g., "SemanticScholar")
        collect_list: List of query dicts for this API
        api_config: API configuration dict
        output_dir: Output directory path
        collect_name: Collection name
        progress_queue: Queue for sending progress updates to main thread
        cancel_event: Optional threading.Event to signal cancellation
        vpn_config: ``vpn`` block of the job configuration (None disables rotation)
    """
    from scilex.crawlers.circuit_breaker import CircuitBreakerRegistry

    # Use absolute path
    repo = os.path.abspath(os.path.join(output_dir, collect_name))

    # Process each query for this API
    for coll_dict in collect_list:
        # Check for cancellation before each query
        if cancel_event and cancel_event.is_set():
            logging.info(f"[{api_name}] Cancellation requested, stopping collection.")
            return
        data_query = coll_dict["query"]
        query_id = data_query.get("id_collect", 0)
        collector_class = api_collectors[api_name]
        api_key = None
        inst_token = None

        # If the circuit breaker is open, stop processing remaining queries.
        # They will be retried on the next --resume run once the API recovers.
        breaker = CircuitBreakerRegistry().get_breaker(api_name)
        if not breaker.is_available():
            logging.warning(
                f"{api_name}: Circuit breaker OPEN — stopping remaining queries for this API. "
                f"Retry with --resume once the API recovers."
            )
            progress_queue.put(
                {
                    "api": api_name,
                    "query_id": query_id,
                    "articles_collected": 0,
                    "success": False,
                    "error": f"{api_name} circuit breaker open",
                }
            )
            break

        if api_name in api_config:
            api_key = api_config[api_name].get("api_key")
            if api_name == "Elsevier" and "inst_token" in api_config[api_name]:
                token_value = api_config[api_name]["inst_token"]
                # Reject placeholder/invalid tokens
                if token_value not in _INVALID_INST_TOKENS and not (
                    isinstance(token_value, str) and token_value.startswith("YOUR_")
                ):
                    inst_token = token_value
                    logging.debug("Using institutional token for Elsevier API")

        kw_str = " + ".join(f'"{k}"' for k in data_query.get("keyword", [])) or "?"
        year = data_query.get("year", "?")

        current_coll = None
        try:
            # Initialize collector
            if api_name == "Elsevier" and inst_token:
                current_coll = collector_class(data_query, repo, api_key, inst_token)
            else:
                current_coll = collector_class(data_query, repo, api_key)

            current_coll.vpn_config = vpn_config or {}
            current_coll.cancel_event = cancel_event

            # Apply user-configured rate limits (api.config.yml `rate_limits`)
            current_coll.load_rate_limit_from_config(api_config.get("rate_limits"))

            logging.info(f"[{api_name}] Q{query_id}: {kw_str} ({year})")

            # Run collection
            res = current_coll.runCollect()
            articles_collected = res.get("coll_art", 0)

            if articles_collected > 0:
                logging.info(
                    f"[{api_name}] Q{query_id} done: {articles_collected} papers — {kw_str} ({year})"
                )
            else:
                logging.debug(
                    f"[{api_name}] Q{query_id} done: 0 papers — {kw_str} ({year})"
                )

            # Send progress update to main thread via queue
            progress_queue.put(
                {
                    "api": api_name,
                    "query_id": query_id,
                    "articles_collected": articles_collected,
                    "keywords": kw_str,
                    "year": year,
                    "success": True,
                    # runCollect returns state 0 when a page failed (resumable)
                    "complete": res.get("state") == 1,
                }
            )

        except Exception as e:
            # Sanitize error message to remove API keys
            sanitized_error = sanitize_secrets(str(e))
            logging.error(
                f"[{api_name}] Q{query_id} error ({kw_str}, {year}): {sanitized_error}"
            )
            # Send error progress update
            progress_queue.put(
                {
                    "api": api_name,
                    "query_id": query_id,
                    "articles_collected": 0,
                    "keywords": kw_str,
                    "year": year,
                    "success": False,
                    "error": sanitized_error,
                }
            )
        finally:
            # Always flush buffered pages and release the HTTP connection pool
            if current_coll is not None:
                try:
                    current_coll.close_session()
                except Exception as close_exc:
                    logging.warning(
                        f"[{api_name}] Q{query_id}: close_session failed: "
                        f"{sanitize_secrets(str(close_exc))}"
                    )

    # Note: Rate limiting is handled per-API by individual collectors
    # using configured rate limits from api.config.yml


def _log_api_summary(api_name: str, stats: dict) -> None:
    """Log one API's end-of-collection line: Complete, or Partial if resumable."""
    # Queries never started (cancel) are as unfinished as failed ones.
    not_done = stats["total"] - stats["completed"] + stats["incomplete"]
    if not_done > 0:
        logging.warning(
            f"[{api_name}] Partial: {stats['articles']} papers, "
            f"{not_done} of {stats['total']} queries not finished "
            f"(run the collection again to resume them)"
        )
    else:
        logging.info(
            f"[{api_name}] Complete: {stats['articles']} papers "
            f"from {stats['completed']} queries"
        )


class CollectCollection:
    def __init__(
        self, main_config, api_config, progress_callback=None, cancel_event=None
    ):
        print("Initializing collection")
        self.main_config = main_config
        self.api_config = api_config
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.init_collection_collect()

    def validate_api_keys(self):
        """Validate that required API keys are present before starting collection"""
        logger = logging.getLogger(__name__)
        apis_requiring_keys = {
            "IEEE": "api_key",
            "Springer": "api_key",
            "Elsevier": ["api_key", "inst_token"],
        }

        missing_keys = []
        apis_to_use = self.main_config.get("apis", [])

        for api in apis_to_use:
            if api in apis_requiring_keys:
                required_keys = apis_requiring_keys[api]
                if not isinstance(required_keys, list):
                    required_keys = [required_keys]

                api_config = self.api_config.get(api, {})
                for key in required_keys:
                    if not api_config.get(key):
                        missing_keys.append(f"{api}.{key}")

        if missing_keys:
            logger.warning(
                f"Missing API keys: {', '.join(missing_keys)} - these collections will likely fail"
            )
            return False

        logger.debug("API key validation passed")
        return True

    def get_current_repo(self):
        output_dir = self.main_config.get("output_dir", DEFAULT_OUTPUT_DIR)
        return os.path.join(output_dir, self.main_config["collect_name"])

    def queryCompositor(self):
        """
        Generates all potential combinations of keyword groups, years, APIs, and fields.
            list: A list of dictionaries, each representing a unique combination.
        """

        # Generate all combinations of keywords from two different groups
        keyword_combinations = []
        two_list_k = False
        #### CASE EVERYTHING OK
        if (
            len(self.main_config["keywords"]) == 2
            and len(self.main_config["keywords"][0]) != 0
            and len(self.main_config["keywords"][1]) != 0
        ):
            two_list_k = True
            keyword_combinations = [
                list(pair)
                for pair in product(
                    self.main_config["keywords"][0], self.main_config["keywords"][1]
                )
            ]
        #### CASE ONLY ONE LIST
        elif (
            len(self.main_config["keywords"]) == 2
            and len(self.main_config["keywords"][0]) != 0
            and len(self.main_config["keywords"][1]) == 0
        ) or (
            len(self.main_config["keywords"]) == 1
            and len(self.main_config["keywords"][0]) != 0
        ):
            keyword_combinations = self.main_config["keywords"][0]

        logger = logging.getLogger(__name__)
        logger.debug(f"Generated {len(keyword_combinations)} keyword combinations")

        # Generate all combinations using Cartesian product
        ### ADD LETTER FIELDS
        # combinations = product(keyword_combinations, self.years, self.apis, self.fields)
        combinations = product(
            keyword_combinations, self.main_config["years"], self.main_config["apis"]
        )

        # Create a list of dictionaries with the combinations
        # Include semantic_scholar_mode for SemanticScholar API
        semantic_scholar_mode = self.main_config.get("semantic_scholar_mode", "regular")
        # Get max_articles_per_query from config (default to -1 = unlimited)
        max_articles_per_query = self.main_config.get("max_articles_per_query", -1)

        queries_by_api = defaultdict(list)
        since = self.main_config.get("since")
        for keyword_group, year, api in combinations:
            query = {
                # Two keyword lists give [kw_a, kw_b] pairs; a single list gives [kw]
                "keyword": keyword_group if two_list_k else [keyword_group],
                "year": year,
                "max_articles_per_query": max_articles_per_query,
            }
            if api == "SemanticScholar":
                query["semantic_scholar_mode"] = semantic_scholar_mode
            if since:
                query["since"] = str(since)
            queries_by_api[api].append(query)
        logger.debug(
            f"Generated {sum(map(len, queries_by_api.values()))} total queries "
            f"across {len(self.main_config['apis'])} APIs"
        )

        return dict(queries_by_api)

    def init_collection_collect(self):
        """
        Initialize collection directory and save config snapshot.

        Creates output directory if needed and saves a snapshot of the config
        for use by aggregation later.
        """
        repo = self.get_current_repo()

        # Create directory and save config snapshot on first run
        if not os.path.isdir(repo):
            os.makedirs(repo)
            logging.info(f"Created collection directory: {repo}")

        # Always save/update config snapshot to ensure it's current
        config_path = os.path.join(repo, "config_used.yml")
        with open(config_path, "w") as f:
            yaml.dump(self.main_config, f)
        logging.debug(f"Saved config snapshot to: {config_path}")

    def _query_is_complete(self, repo, api, query_idx):
        """
        Check whether a query was fully collected.

        ``runCollect`` writes ``_state`` ("incomplete") when it starts and
        replaces it with ``_complete`` once every page was fetched (or
        ``max_articles_per_query`` was reached). A directory with ``_state`` but
        no ``_complete`` is a partial/failed run and is resumed.

        Backward compatibility: a directory from an older SciLEx version has
        neither marker. If it holds page files it is treated as complete, so
        old collections are not re-collected. (A run killed before ``_state``
        existed cannot be told apart from those.)

        Args:
            repo: Collection directory path
            api: API name (e.g., 'SemanticScholar')
            query_idx: Query index (e.g., 0, 1, 2)

        Returns:
            bool: True when the query must not be collected again
        """
        query_dir = os.path.join(repo, api, str(query_idx))
        if os.path.isfile(os.path.join(query_dir, COMPLETE_FILE_NAME)):
            return True
        if os.path.isfile(os.path.join(query_dir, STATE_FILE_NAME)):
            return False
        return self._get_last_collected_page(repo, api, query_idx) > 0

    def _get_last_collected_page(self, repo, api, query_idx):
        """
        Infer the last successfully saved page from the page files on disk.

        Args:
            repo: Collection directory path
            api: API name
            query_idx: Query index

        Returns:
            int: Highest page number found (0 if none)
        """
        query_dir = os.path.join(repo, api, str(query_idx))
        if not os.path.isdir(query_dir):
            return 0
        try:
            page_numbers = []
            for fname in os.listdir(query_dir):
                if fname.startswith("page_"):
                    try:
                        page_numbers.append(int(fname[5:]))
                    except ValueError:
                        continue
            return max(page_numbers) if page_numbers else 0
        except (PermissionError, OSError):
            return 0

    def create_collects_jobs(self):
        """
        Create collection jobs and run them in parallel.

        Uses file existence checks for idempotent collections:
        - Skips queries that already have result files
        - Allows safe re-runs without duplicating API calls
        """
        logger = logging.getLogger(__name__)

        # Validate API keys before starting
        self.validate_api_keys()

        # Generate all queries from config
        print("Building query composition")
        queries_by_api = self.queryCompositor()

        # Create grouped jobs dict (one list per API), skipping already-completed queries
        repo = self.get_current_repo()
        jobs_by_api = {}  # Grouped: {"API_name": [query1, query2, ...]}
        n_coll = 0
        n_skipped = 0
        n_resumed = 0

        for api in queries_by_api:
            queries = queries_by_api[api]
            api_jobs = []

            for idx, query in enumerate(queries):
                # Skip queries that were fully completed (sentinel file present)
                if self._query_is_complete(repo, api, idx):
                    n_skipped += 1
                    logger.debug(f"Skipping {api} query {idx} (fully complete)")
                    continue

                # Resume partial collection from last saved page (0 = start fresh)
                last_page = self._get_last_collected_page(repo, api, idx)
                if last_page > 0:
                    n_resumed += 1
                    kw_str = (
                        " + ".join(f'"{k}"' for k in query.get("keyword", [])) or "?"
                    )
                    logger.info(
                        f"Resuming {api} query {idx} from page {last_page + 1} "
                        f"({last_page} pages already collected) — {kw_str} ({query.get('year', '?')})"
                    )

                query["id_collect"] = idx
                query["total_art"] = 0  # Unknown until first API response
                query["last_page"] = last_page  # Resume point (0 = fresh start)
                query["coll_art"] = 0
                query["state"] = 0
                api_jobs.append({"query": query, "api": api})
                n_coll += 1

            # Only add API if it has queries to process
            if api_jobs:
                jobs_by_api[api] = api_jobs

        # Log summary
        if n_skipped > 0:
            logger.info(
                f"Skipped {n_skipped} already-completed queries (idempotent re-run)"
            )
        if n_resumed > 0:
            logger.info(
                f"Resuming {n_resumed} partially-collected queries from their last page"
            )

        # Check if there are any jobs to process
        if len(jobs_by_api) == 0:
            logger.warning(
                "No collections to conduct. All queries already have results."
            )
            logger.warning(
                "To restart collection, delete the API directories in the output folder."
            )
            return

        # One thread per API
        num_threads = len(jobs_by_api)
        num_apis = len(jobs_by_api)
        total_queries = sum(len(api_jobs) for api_jobs in jobs_by_api.values())
        tqdm.write(
            f"Starting collection: {n_coll} queries across {num_apis} API(s) using {num_threads} threads (1 per API)"
        )

        # Per-API stats (no per-API bars — avoids multi-bar cursor-movement artifacts in WSL)
        api_stats = defaultdict(
            lambda: {"completed": 0, "total": 0, "articles": 0, "incomplete": 0}
        )
        for api_name, api_jobs in jobs_by_api.items():
            api_stats[api_name]["total"] = len(api_jobs)

        # Create shared progress queue
        progress_queue = Queue()

        # Extract output_dir with default
        output_dir = self.main_config.get("output_dir", DEFAULT_OUTPUT_DIR)

        vpn_config = vpn_config_from_configs(self.main_config, self.api_config)

        # Create one thread per API
        threads = []
        for api_name, api_jobs in jobs_by_api.items():
            thread = threading.Thread(
                target=_run_job_collects_worker,
                args=(
                    api_name,
                    api_jobs,
                    self.api_config,
                    output_dir,
                    self.main_config["collect_name"],
                    progress_queue,
                    self.cancel_event,
                    vpn_config,
                ),
                name=f"Worker-{api_name}",
            )
            thread.start()
            threads.append(thread)

        # Single overall progress bar — eliminates multi-bar cursor gymnastics
        overall_bar = tqdm(
            total=total_queries,
            desc="Collecting",
            unit="query",
            dynamic_ncols=True,
            position=0,
            leave=True,
        )

        # Monitor progress queue in main thread
        completed_count = 0

        try:
            with logging_redirect_tqdm(loggers=[logging.root]):
                while completed_count < total_queries:
                    # Check for cancellation
                    if self.cancel_event and self.cancel_event.is_set():
                        logging.info(
                            "Cancellation requested, stopping collection monitoring."
                        )
                        break

                    try:
                        result = progress_queue.get(timeout=0.1)

                        api_name = result["api"]
                        articles = result["articles_collected"]
                        api_stats[api_name]["completed"] += 1
                        api_stats[api_name]["articles"] += articles
                        if not result.get("complete", result.get("success", False)):
                            api_stats[api_name]["incomplete"] += 1
                        completed_count += 1

                        overall_bar.update(1)
                        # Postfix: total papers so far + per-API paper count
                        total_papers = sum(s["articles"] for s in api_stats.values())
                        api_summary = " | ".join(
                            f"{a}:{s['articles']}"
                            for a, s in sorted(api_stats.items())
                            if s["completed"] > 0
                        )
                        overall_bar.set_postfix_str(
                            f"{total_papers} papers [{api_summary}]"
                        )

                        # Announce when an API finishes all its queries
                        done = api_stats[api_name]["completed"]
                        total_for_api = api_stats[api_name]["total"]
                        if done == total_for_api:
                            tqdm.write(
                                f"  [{api_name}] finished {done} queries → {api_stats[api_name]['articles']:,} papers"
                            )

                        # Notify progress callback if set
                        if self.progress_callback:
                            self.progress_callback(
                                api_stats, completed_count, total_queries
                            )

                    except Empty:
                        # Queue timeout — check if all threads are done
                        if not any(t.is_alive() for t in threads):
                            break
                        continue

        finally:
            # Wait for every worker, also after a cancel: collectors check the
            # event between pages and during waits, so at most one in-flight
            # request remains. Returning earlier would let a new job read
            # files a worker is still writing.
            for thread in threads:
                thread.join()

            overall_bar.close()

            print("\n" + "=" * 60)
            print("Collection Summary:")
            print("=" * 60)
            for api_name in sorted(api_stats.keys()):
                stats = api_stats[api_name]
                print(
                    f"{api_name:20s}: {stats['completed']:3d} queries | {stats['articles']:,} papers"
                )
                _log_api_summary(api_name, stats)
            print("=" * 60 + "\n")
