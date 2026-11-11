"""PubMed Central (PMC) collector for fetching open-access biomedical literature.

This collector uses NCBI E-utilities API with a two-phase workflow:
1. ESearch: Search for PMC IDs matching keywords and date filters
2. EFetch: Retrieve full metadata for batches of PMC IDs

PMC provides 7+ million open-access articles including chemistry, biochemistry,
medicinal chemistry, and drug discovery papers.
"""

import logging
import urllib.parse
from datetime import date

from lxml import etree

from .base import API_collector


class PubMedCentral_collector(API_collector):
    """Collector for fetching publication metadata from PubMed Central API.

    Uses NCBI E-utilities (ESearch + EFetch) to retrieve open-access articles.
    Supports keyword search in title/abstract fields with date range filtering.
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "PubMedCentral"
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.rate_limit = 10 if api_key else 3  # 10 req/sec with API key
        self.max_by_page = 100  # ESearch maximum retmax
        self.batch_size = 50  # Number of IDs to fetch per EFetch call
        self.load_rate_limit_from_config()

    def construct_search_query(self):
        """Construct Entrez query with keyword groups and date filters.

        Supports dual keyword groups:
        - Single group: [["term1", "term2"], []] → (term1 OR term2)
        - Dual groups: [["group1"], ["group2"]] → (group1) AND (group2)

        Returns:
            str: URL-encoded Entrez query string
        """
        keyword_groups = []

        for keyword_set in self.get_keywords():
            if not keyword_set:  # Skip empty groups
                continue

            # Build OR terms for this group
            group_terms = []
            for keyword in keyword_set:
                # Search in both title and abstract
                encoded_keyword = urllib.parse.quote(keyword)
                group_terms.append(f"({encoded_keyword}[Title/Abstract])")

            # Join terms in this group with OR
            if group_terms:
                keyword_groups.append(f"({' OR '.join(group_terms)})")

        # Join all groups with AND
        query_parts = []
        if keyword_groups:
            query_parts.append(" AND ".join(keyword_groups))

        # Add date filter
        year = str(self.get_year())
        date_filter = f'"{year}/01/01"[PDAT] : "{year}/12/31"[PDAT]'
        query_parts.append(date_filter)

        final_query = " AND ".join(query_parts)
        logging.debug(f"Constructed PMC query: {final_query}")
        return final_query

    def get_configurated_url(self):
        """Construct ESearch URL with pagination placeholder.

        Returns:
            str: URL template with {} placeholder for retstart (offset)
        """
        query = self.construct_search_query()
        api_key_param = f"&api_key={self.api_key}" if self.api_key else ""

        url = (
            f"{self.base_url}/esearch.fcgi?"
            f"db=pmc&"
            f"term={query}&"
            f"retmax={self.max_by_page}&"
            f"retstart={{}}&"
            f"retmode=xml"
            f"{api_key_param}"
        )

        logging.debug(f"Configured ESearch URL template: {url}")
        return url

    def parsePageResults(self, response, page):
        """Parse ESearch response and fetch metadata for PMC IDs.

        Two-phase process:
        1. Parse ESearch XML to extract PMC IDs and total count
        2. Batch EFetch calls to retrieve metadata (50 IDs per call)

        Args:
            response: Response object from ESearch API call
            page: Current page number

        Returns:
            dict: Page data with results list and total count
        """
        page_data = {
            "date_search": str(date.today()),
            "id_collect": self.get_collectId(),
            "page": page,
            "total": 0,
            "results": [],
        }

        # Phase 1: Parse ESearch response to get PMC IDs
        try:
            tree = etree.fromstring(response.content)

            # Extract total count
            total_elem = tree.find(".//Count")
            if total_elem is not None:
                page_data["total"] = int(total_elem.text)
                logging.debug(f"Total PMC results: {page_data['total']}")

            # Extract PMC IDs
            id_elements = tree.findall(".//Id")
            pmc_ids = [id_elem.text for id_elem in id_elements if id_elem.text]

            if not pmc_ids:
                logging.debug(f"No PMC IDs found on page {page}")
                return page_data

            logging.debug(f"Found {len(pmc_ids)} PMC IDs on page {page}")

            # Phase 2: Batch EFetch calls to get metadata
            all_articles = []
            for i in range(0, len(pmc_ids), self.batch_size):
                batch_ids = pmc_ids[i : i + self.batch_size]
                batch_articles = self._fetch_metadata_batch(batch_ids)
                all_articles.extend(batch_articles)

            page_data["results"] = all_articles
            logging.debug(
                f"Retrieved metadata for {len(all_articles)} articles on page {page}"
            )

        except etree.XMLSyntaxError as e:
            logging.error(f"XML parsing error on page {page}: {str(e)}")
        except Exception as e:
            logging.error(f"Error parsing PMC results on page {page}: {str(e)}")

        return page_data

    def _fetch_metadata_batch(self, pmc_ids):
        """Fetch metadata for a batch of PMC IDs using EFetch.

        Args:
            pmc_ids: List of PMC IDs (e.g., ["1234567", "2345678"])

        Returns:
            list: List of article metadata dictionaries
        """
        if not pmc_ids:
            return []

        # Build EFetch URL
        id_string = ",".join(pmc_ids)
        api_key_param = f"&api_key={self.api_key}" if self.api_key else ""

        efetch_url = (
            f"{self.base_url}/efetch.fcgi?"
            f"db=pmc&"
            f"id={id_string}&"
            f"retmode=xml"
            f"{api_key_param}"
        )

        try:
            logging.debug(f"Fetching metadata for {len(pmc_ids)} PMC IDs")
            response = self.api_call_decorator(efetch_url)
            return self._parse_efetch_response(response.content)
        except Exception as e:
            logging.error(f"Error fetching batch metadata: {str(e)}")
            return []

    def _parse_efetch_response(self, xml_content):
        """Parse EFetch XML response to extract article metadata.

        Parses NLM DTD format XML to extract:
        - PMC ID, PMID, DOI
        - Title, abstract
        - Authors
        - Journal, volume, issue, pages
        - Publication date
        - Publisher, language

        Args:
            xml_content: Raw XML bytes from EFetch response

        Returns:
            list: List of article dictionaries
        """
        articles = []

        try:
            root = etree.fromstring(xml_content)

            # Find all article elements
            article_elements = root.findall(".//article")

            for article_elem in article_elements:
                try:
                    article_data = self._extract_article_metadata(article_elem)
                    if article_data:
                        articles.append(article_data)
                except Exception as e:
                    logging.warning(f"Error parsing article: {str(e)}")
                    continue

        except etree.XMLSyntaxError as e:
            logging.error(f"XML syntax error in EFetch response: {str(e)}")
        except Exception as e:
            logging.error(f"Error parsing EFetch response: {str(e)}")

        return articles

    def _extract_article_metadata(self, article_elem):
        """Extract metadata from a single article XML element.

        Args:
            article_elem: lxml Element representing <article>

        Returns:
            dict: Article metadata or None if extraction fails
        """
        try:
            # Navigate to article-meta section
            article_meta = article_elem.find(".//article-meta")
            if article_meta is None:
                logging.warning("No article-meta found in article")
                return None

            # Extract identifiers
            pmc_id = self._extract_article_id(article_meta, "pmc")
            pmid = self._extract_article_id(article_meta, "pmid")
            doi = self._extract_article_id(article_meta, "doi")

            # Extract title
            title_elem = article_meta.find(".//title-group/article-title")
            title = self._get_text_content(title_elem) if title_elem is not None else ""

            # Extract abstract
            abstract_elem = article_meta.find(".//abstract")
            abstract = (
                self._get_text_content(abstract_elem)
                if abstract_elem is not None
                else ""
            )

            # Extract authors
            authors = self._extract_authors(article_meta)

            # Extract journal information
            journal_meta = article_elem.find(".//journal-meta")
            journal = self._extract_journal_name(journal_meta)

            # Extract publication date
            pub_date = self._extract_publication_date(article_meta)

            # Extract volume, issue, pages
            volume = self._get_element_text(article_meta, ".//volume")
            issue = self._get_element_text(article_meta, ".//issue")

            fpage = self._get_element_text(article_meta, ".//fpage")
            lpage = self._get_element_text(article_meta, ".//lpage")
            pages = f"{fpage}-{lpage}" if fpage and lpage else (fpage or lpage or "")

            # Extract publisher
            publisher = ""
            if journal_meta is not None:
                publisher_elem = journal_meta.find(".//publisher/publisher-name")
                if publisher_elem is not None:
                    publisher = self._get_text_content(publisher_elem)

            # Extract language - xml:lang is typically on the root article element
            language = "en"  # Default to English
            # Try to get xml:lang attribute without namespace prefix
            if "xml:lang" in article_elem.attrib:
                language = article_elem.attrib["xml:lang"]
            # Try with full namespace
            elif "{http://www.w3.org/XML/1998/namespace}lang" in article_elem.attrib:
                language = article_elem.attrib[
                    "{http://www.w3.org/XML/1998/namespace}lang"
                ]

            # Build article dictionary
            article_data = {
                "pmc_id": f"PMC{pmc_id}" if pmc_id else "",
                "pmid": pmid,
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "date": pub_date,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "publisher": publisher,
                "language": language,
            }

            return article_data

        except Exception as e:
            logging.error(f"Error extracting article metadata: {str(e)}")
            return None

    def _extract_article_id(self, article_meta, pub_id_type):
        """Extract article ID of specific type (pmc, pmid, doi).

        Args:
            article_meta: lxml Element for article-meta
            pub_id_type: Type of ID (pmc, pmid, doi)

        Returns:
            str: Article ID or empty string
        """
        id_elem = article_meta.find(f".//article-id[@pub-id-type='{pub_id_type}']")
        if id_elem is not None:
            return id_elem.text.strip() if id_elem.text else ""
        return ""

    def _extract_authors(self, article_meta):
        """Extract author names from contrib-group.

        Args:
            article_meta: lxml Element for article-meta

        Returns:
            list: List of author names in "Surname GivenNames" format
        """
        authors = []
        contrib_group = article_meta.find(".//contrib-group")

        if contrib_group is not None:
            for contrib in contrib_group.findall(".//contrib[@contrib-type='author']"):
                name_elem = contrib.find(".//name")
                if name_elem is not None:
                    surname = self._get_element_text(name_elem, ".//surname")
                    given_names = self._get_element_text(name_elem, ".//given-names")

                    if surname:
                        # Format: "Surname GivenNames"
                        full_name = (
                            f"{surname} {given_names}" if given_names else surname
                        )
                        authors.append(full_name)

        return authors

    def _extract_journal_name(self, journal_meta):
        """Extract journal name from journal-meta.

        Tries journal-title first, falls back to journal-id.

        Args:
            journal_meta: lxml Element for journal-meta

        Returns:
            str: Journal name or empty string
        """
        if journal_meta is None:
            return ""

        # Try journal-title first
        journal_title = journal_meta.find(".//journal-title")
        if journal_title is not None:
            text = self._get_text_content(journal_title)
            if text:
                return text

        # Fallback to journal-id
        journal_id = journal_meta.find(".//journal-id[@journal-id-type='nlm-ta']")
        if journal_id is not None:
            text = journal_id.text
            if text:
                return text.strip()

        return ""

    def _extract_publication_date(self, article_meta):
        """Extract publication date in YYYY-MM-DD format.

        Tries multiple date types: epub, ppub, collection.

        Args:
            article_meta: lxml Element for article-meta

        Returns:
            str: Date in YYYY-MM-DD format or empty string
        """
        # Try different publication date types in order of preference
        date_types = ["epub", "ppub", "collection"]

        for date_type in date_types:
            pub_date = article_meta.find(f".//pub-date[@pub-type='{date_type}']")
            if pub_date is not None:
                year = self._get_element_text(pub_date, ".//year")
                month = self._get_element_text(pub_date, ".//month")
                day = self._get_element_text(pub_date, ".//day")

                if year:
                    # Pad month and day with zeros
                    month = month.zfill(2) if month else "01"
                    day = day.zfill(2) if day else "01"
                    return f"{year}-{month}-{day}"

        return ""

    def _get_element_text(self, parent, xpath):
        """Safely get text content from XPath query.

        Args:
            parent: lxml Element to search within
            xpath: XPath query string

        Returns:
            str: Stripped text content or empty string
        """
        elem = parent.find(xpath)
        if elem is not None and elem.text:
            return elem.text.strip()
        return ""

    def _get_text_content(self, elem):
        """Get all text content from element and subelements.

        Handles mixed content (text + tags) by concatenating all text nodes.

        Args:
            elem: lxml Element

        Returns:
            str: Concatenated text content
        """
        if elem is None:
            return ""

        # Use itertext() to get all text content
        text_parts = [text.strip() for text in elem.itertext() if text.strip()]
        return " ".join(text_parts)
