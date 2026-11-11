import logging
import math
import threading
import time
from datetime import date

from scholarly import ProxyGenerator, scholarly

from .base import API_collector


class GoogleScholarCollector(API_collector):
    """Collector for fetching publication metadata from Google Scholar using the free scholarly package."""

    # Class-level proxy initialization flag
    _proxy_initialized = False
    _proxy_lock = threading.Lock()

    def __init__(self, data_query, data_path, api_key=None):
        """
        Initializes the Google Scholar collector with the given parameters.

        Args:
            data_query (dict): Query parameters containing year, keywords, etc.
            data_path (str): Path to save the collected data.
            api_key (str, optional): Not used for scholarly (kept for API compatibility).
        """
        super().__init__(data_query, data_path, api_key)
        self.rate_limit = 2  # Conservative rate limit for Tor
        self.max_by_page = 20  # scholarly returns ~10-20 results per "page" iteration
        self.api_name = "GoogleScholar"
        self.api_url = ""  # Not used for scholarly
        self.load_rate_limit_from_config()

        # Initialize proxy if not already done (class-level to avoid multiple setups)
        if not GoogleScholarCollector._proxy_initialized:
            with GoogleScholarCollector._proxy_lock:
                if not GoogleScholarCollector._proxy_initialized:
                    self._setup_proxy()

    def _setup_proxy(self):
        """
        Sets up proxy for Google Scholar.
        Priority: Existing Tor service (External) → Spawn Tor (Internal) → FreeProxies → No proxy

        For fastest startup, ensure Tor service is running:
        - macOS: brew services start tor
        - Ubuntu/Debian: sudo service tor start
        """
        # Step 1: Try to connect to existing Tor service (instant startup)
        logging.info("Initializing Google Scholar with Tor...")
        if self._is_tor_running():
            logging.info("✅ Found running Tor service on port 9050")
            try:
                pg = ProxyGenerator()
                # Use Tor_External to connect to system Tor service
                # CookieAuthentication in torrc means no password needed
                success = pg.Tor_External(tor_sock_port=9050, tor_control_port=9051)

                if success:
                    scholarly.use_proxy(pg)
                    GoogleScholarCollector._proxy_initialized = True
                    logging.info("✅ Connected to Tor service successfully (instant)")
                    return
            except Exception as e:
                logging.debug(f"Tor_External failed: {str(e)}")

        # Step 2: Fall back to spawning our own Tor (slower, but works offline)
        logging.info("System Tor service not found, spawning own Tor instance...")
        logging.info("⏳ First run may take 2-3 minutes while Tor bootstraps...")
        try:
            pg = ProxyGenerator()
            success = pg.Tor_Internal(tor_cmd="tor")

            if success:
                scholarly.use_proxy(pg)
                GoogleScholarCollector._proxy_initialized = True
                logging.info("✅ Spawned Tor proxy successfully")
                logging.info("💡 For faster startup next time: brew services start tor")
                return
        except Exception as e:
            logging.debug(f"Tor_Internal failed: {str(e)}")

        # Step 3: Fall back to FreeProxies (unreliable but free)
        logging.warning(
            "Tor initialization failed, trying FreeProxies (less reliable)..."
        )
        try:
            pg = ProxyGenerator()
            success = pg.FreeProxies()

            if success:
                scholarly.use_proxy(pg)
                GoogleScholarCollector._proxy_initialized = True
                logging.warning(
                    "⚠️ Using FreeProxies - may be blocked by Google Scholar"
                )
                logging.info(
                    "For better reliability, start Tor: brew services start tor"
                )
                return
        except Exception as e:
            logging.debug(f"FreeProxies failed: {str(e)}")

        # Step 4: Last resort - proceed without proxy (likely to be blocked)
        logging.warning(
            "All proxy methods failed, proceeding without proxy - requests may be blocked"
        )

    @staticmethod
    def _is_tor_running(host: str = "127.0.0.1", port: int = 9050) -> bool:
        """Check if Tor SOCKS proxy is accessible on the specified port."""
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def parsePageResults(self, results_batch, page):
        """
        Parses results from scholarly search generator for a specific batch/page.

        Args:
            results_batch (list): A batch of results from scholarly.search_pubs()
            page (int): The page/batch number being processed.

        Returns:
            dict: A dictionary containing metadata about the collected results.
        """
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": len(results_batch)
            * page,  # Estimate (scholarly doesn't provide exact totals)
            "results": [],
        }

        for result in results_batch:
            try:
                # Extract data from scholarly result
                parsed_result = {
                    "title": result.get("bib", {}).get("title", ""),
                    "authors": result.get("bib", {}).get("author", []),
                    "abstract": result.get("bib", {}).get("abstract", ""),
                    "venue": result.get("bib", {}).get("venue", ""),
                    "year": result.get("bib", {}).get("pub_year", ""),
                    "url": result.get("pub_url", ""),
                    "eprint_url": result.get("eprint_url", ""),
                    "citations": result.get("num_citations", 0),
                    "scholar_id": result.get("author_id", []),
                    "citation_url": result.get("citedby_url", ""),
                }
                page_data["results"].append(parsed_result)
            except Exception as e:
                logging.warning(
                    f"Error parsing individual Google Scholar result: {str(e)}"
                )
                continue

        logging.debug(f"Parsed page {page}: {len(page_data['results'])} results")
        return page_data

    def get_configurated_url(self):
        """
        Not used for scholarly (kept for API compatibility).

        Returns:
            str: Empty string.
        """
        return ""

    def runCollect(self):
        """
        Runs the collection process using scholarly.search_pubs() instead of URL-based API calls.

        This overrides the parent class method since scholarly uses a generator pattern
        rather than paginated REST API calls.
        """
        state_data = {
            "state": self.state,
            "last_page": self.lastpage,
            "total_art": self.total_art,
            "coll_art": self.nb_art_collected,
            "update_date": str(date.today()),
            "id_collect": self.collectId,
        }

        # Check if collection is already complete
        if self.state == 1:
            logging.info("Collection already completed.")
            return state_data

        # Build search query
        keywords = self.get_keywords()
        if len(keywords) == 2:  # Dual keyword mode
            # Enforce AND: papers must match keywords from BOTH groups
            query = f'("{keywords[0]}") AND ("{keywords[1]}")'
        else:  # Single keyword mode
            query = " ".join(keywords)  # Space-separated OR logic
        year = self.get_year()

        # Add year to query if specified
        if year:
            query += f" {year}"

        logging.info(f"Starting Google Scholar collection with query: '{query}'")

        try:
            # Use scholarly.search_pubs() to get search results
            search_query = scholarly.search_pubs(query)

            page = int(self.get_lastpage()) + 1
            results_batch = []

            # Calculate max_results based on max_articles_per_query config
            max_articles = self.filter_param.get_max_articles_per_query()
            if max_articles > 0:
                # Limit to configured number of articles
                max_results = max_articles
                max_pages = math.ceil(max_articles / self.max_by_page)
                logging.info(
                    f"Google Scholar: Limited to {max_articles} articles (~{max_pages} pages)"
                )
            else:
                # Unlimited mode - set a reasonable upper limit to avoid excessive scraping
                max_results = 1000
                logging.info(
                    f"Google Scholar: Unlimited mode (max {max_results} results to avoid excessive scraping)"
                )

            # Iterate through results
            for idx, result in enumerate(search_query):
                results_batch.append(result)

                # Process in batches
                if len(results_batch) >= self.max_by_page or idx >= max_results - 1:
                    # Parse and save this batch
                    page_data = self.parsePageResults(results_batch, page)

                    # Log API usage (mock - scholarly doesn't provide response objects)
                    self.log_api_usage(None, page, len(page_data["results"]))

                    # Save results
                    self.savePageResults(page_data, page)

                    # Update state
                    self.nb_art_collected += len(page_data["results"])
                    self.set_lastpage(page)
                    state_data["last_page"] = page
                    state_data["coll_art"] = self.nb_art_collected
                    state_data["total_art"] = self.nb_art_collected  # Estimate

                    logging.info(
                        f"Processed page {page}: {len(page_data['results'])} results. Total collected: {self.nb_art_collected}"
                    )

                    # Check if we've collected enough articles (post-check after saving page)
                    if max_articles > 0 and self.nb_art_collected >= max_articles:
                        logging.debug(
                            f"Collected {self.nb_art_collected} articles (limit: {max_articles}). "
                            f"No more pages needed."
                        )
                        break

                    # Move to next page
                    page += 1
                    results_batch = []

                    # Rate limiting
                    time.sleep(1.0 / self.rate_limit)

                # Stop if we hit the max results
                if idx >= max_results - 1:
                    logging.info(
                        f"Reached maximum result limit ({max_results} results)"
                    )
                    break

            # Save any remaining results
            if results_batch:
                page_data = self.parsePageResults(results_batch, page)
                self.savePageResults(page_data, page)
                self.nb_art_collected += len(page_data["results"])
                state_data["last_page"] = page
                state_data["coll_art"] = self.nb_art_collected
                state_data["total_art"] = self.nb_art_collected

            # Mark as complete
            state_data["state"] = 1
            logging.info(
                f"Google Scholar collection complete. Total articles collected: {self.nb_art_collected}"
            )

        except Exception as e:
            logging.error(f"Error during Google Scholar collection: {str(e)}")
            state_data["state"] = 0
            logging.info("Collection encountered an error, marked as incomplete")

        return state_data
