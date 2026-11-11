"""PubMed collector for fetching biomedical literature metadata.

This collector uses NCBI E-utilities API with a two-phase workflow:
1. ESearch: Search for PMIDs matching keywords and date filters
2. EFetch: Retrieve full metadata for batches of PMIDs

PubMed provides 35+ million biomedical citations/abstracts, including both
open-access and paywalled papers. When PMCID is present, PDF URLs are
automatically generated for PMC open-access content.
"""

import logging
import urllib.parse
from datetime import date

from lxml import etree

from scilex.crawlers.utils import sanitize_secrets

from .base import API_collector


class PubMed_collector(API_collector):
    """Collector for fetching publication metadata from PubMed API.

    Uses NCBI E-utilities (ESearch + EFetch) to retrieve biomedical citations.
    Supports keyword search in title/abstract fields with date range filtering.
    Automatically enriches papers with PMC PDF URLs when PMCID is available.
    """

    def __init__(self, filter_param, data_path, api_key):
        super().__init__(filter_param, data_path, api_key)
        self.api_name = "PubMed"
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.max_by_page = 100  # ESearch maximum retmax
        self.batch_size = 50  # Number of IDs to fetch per EFetch call
        self.load_rate_limit_from_config()

    def construct_search_query(self):
        """Construct Entrez query with keywords and date filters.

        get_keywords() returns a flat list of keywords like ["agents", "knowledge graph"]
        where each element is a complete keyword (possibly multi-word). In dual keyword
        mode, this list represents the cross-product of both groups, so we join them
        with AND to match papers containing all keywords.

        All keywords are quoted for exact phrase matching (disables Automatic Term
        Mapping to MeSH terms, providing more precise results for systematic reviews).

        Returns:
            str: Entrez query string for PubMed API
        """
        # Build query terms for each keyword (all quoted for exact matching)
        query_terms = []
        for keyword in self.get_keywords():
            query_terms.append(f'"{keyword}"[Title/Abstract]')

        # Join all keywords with AND
        query_parts = []
        if query_terms:
            query_parts.append(" AND ".join(query_terms))

        # Add date filter with quoted dates and space around colon
        year = str(self.get_year())
        start_date = self.get_query_start_date()
        range_start = start_date.strftime("%Y/%m/%d") if start_date else f"{year}/01/01"
        date_filter = f'"{range_start}"[PDAT] : "{year}/12/31"[PDAT]'
        query_parts.append(date_filter)

        final_query = " AND ".join(query_parts)
        logging.debug(f"PubMed query: {final_query}")
        return final_query

    def get_configurated_url(self):
        """Construct ESearch URL with pagination placeholder.

        Returns:
            str: URL template with {} placeholder for retstart (offset)
        """
        query = self.construct_search_query()
        # URL-encode the query for safe transmission
        encoded_query = urllib.parse.quote(query, safe="")
        api_key_param = f"&api_key={self.api_key}" if self.api_key else ""

        url = (
            f"{self.base_url}/esearch.fcgi?"
            f"db=pubmed&"
            f"term={encoded_query}&"
            f"retmax={self.max_by_page}&"
            f"retstart={{}}&"
            f"retmode=xml"
            f"{api_key_param}"
        )

        logging.debug(f"Configured ESearch URL template: {self._sanitize_url(url)}")
        return url

    def parsePageResults(self, response, page):
        """Parse ESearch response and fetch metadata for PMIDs.

        Two-phase process:
        1. Parse ESearch XML to extract PMIDs and total count
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

        # Phase 1: Parse ESearch response to get PMIDs
        try:
            tree = etree.fromstring(response.content)

            # Extract total count
            total_elem = tree.find(".//Count")
            if total_elem is not None:
                page_data["total"] = int(total_elem.text)
                logging.debug(f"Total PubMed results: {page_data['total']}")

            # Extract PMIDs
            id_elements = tree.findall(".//Id")
            pmids = [id_elem.text for id_elem in id_elements if id_elem.text]

            if not pmids:
                logging.debug(f"No PMIDs found on page {page}")
                return page_data

            logging.debug(f"Found {len(pmids)} PMIDs on page {page}")

            # Phase 2: Batch EFetch calls to get metadata
            all_articles = []
            for i in range(0, len(pmids), self.batch_size):
                batch_ids = pmids[i : i + self.batch_size]
                batch_articles = self._fetch_metadata_batch(batch_ids)
                all_articles.extend(batch_articles)

            page_data["results"] = all_articles
            logging.debug(
                f"Retrieved metadata for {len(all_articles)} articles on page {page}"
            )

        except Exception as e:
            # Never return a silently truncated page: runCollect marks the
            # query incomplete when this raises.
            logging.error(
                f"Error parsing PubMed results on page {page}: {sanitize_secrets(e)}"
            )
            raise

        return page_data

    def _fetch_metadata_batch(self, pmids):
        """Fetch metadata for a batch of PMIDs using EFetch.

        Args:
            pmids: List of PMIDs (e.g., ["12345678", "23456789"])

        Returns:
            list: List of article metadata dictionaries
        """
        if not pmids:
            return []

        # Build EFetch URL
        id_string = ",".join(pmids)
        api_key_param = f"&api_key={self.api_key}" if self.api_key else ""

        efetch_url = (
            f"{self.base_url}/efetch.fcgi?"
            f"db=pubmed&"
            f"id={id_string}&"
            f"retmode=xml"
            f"{api_key_param}"
        )

        # Errors propagate: a failed batch must not silently drop articles.
        logging.debug(f"Fetching metadata for {len(pmids)} PMIDs")
        response = self.api_call_decorator(efetch_url)
        return self._parse_efetch_response(response.content)

    def _parse_efetch_response(self, xml_content):
        """Parse EFetch XML response to extract article metadata.

        Parses MEDLINE format XML to extract:
        - PMID, PMCID (when available), DOI
        - Title, abstract
        - Authors
        - Journal, volume, issue, pages
        - Publication date
        - Publication type
        - MeSH terms

        Args:
            xml_content: Raw XML bytes from EFetch response

        Returns:
            list: List of article dictionaries
        """
        articles = []

        try:
            root = etree.fromstring(xml_content)

            # Find all PubmedArticle elements
            article_elements = root.findall(".//PubmedArticle")

            for article_elem in article_elements:
                try:
                    article_data = self._extract_article_metadata(article_elem)
                    if article_data:
                        articles.append(article_data)
                except Exception as e:
                    logging.warning(f"Error parsing article: {str(e)}")
                    continue

        except Exception as e:
            logging.error(f"Error parsing EFetch response: {sanitize_secrets(e)}")
            raise

        return articles

    def _extract_article_metadata(self, article_elem):
        """Extract metadata from a single PubmedArticle XML element.

        Args:
            article_elem: lxml Element representing <PubmedArticle>

        Returns:
            dict: Article metadata or None if extraction fails
        """
        try:
            # Navigate to MedlineCitation section
            medline_citation = article_elem.find(".//MedlineCitation")
            if medline_citation is None:
                logging.warning("No MedlineCitation found in article")
                return None

            article = medline_citation.find(".//Article")
            if article is None:
                logging.warning("No Article found in MedlineCitation")
                return None

            # Extract PMID
            pmid_elem = medline_citation.find(".//PMID")
            pmid = (
                pmid_elem.text.strip()
                if pmid_elem is not None and pmid_elem.text
                else ""
            )

            # Extract DOI from ArticleIdList
            doi = ""
            article_id_list = article_elem.find(".//PubmedData/ArticleIdList")
            if article_id_list is not None:
                doi_elem = article_id_list.find(".//ArticleId[@IdType='doi']")
                if doi_elem is not None and doi_elem.text:
                    doi = doi_elem.text.strip()

            # Extract PMCID and construct PMC landing page URL
            pmcid = ""
            pdf_url = ""
            if article_id_list is not None:
                pmcid_elem = article_id_list.find(".//ArticleId[@IdType='pmc']")
                if pmcid_elem is not None and pmcid_elem.text:
                    pmcid_text = pmcid_elem.text.strip()
                    # PMCID may come as "PMC1234567" or just "1234567"
                    pmcid_number = pmcid_text.replace("PMC", "")
                    if pmcid_number.isdigit():
                        pmcid = f"PMC{pmcid_number}"
                        # Construct direct PDF URL (consistent with other collectors)
                        pdf_url = (
                            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
                        )

            # Extract title
            title_elem = article.find(".//ArticleTitle")
            title = self._get_text_content(title_elem) if title_elem is not None else ""

            # Extract abstract
            abstract_elem = article.find(".//Abstract")
            abstract = ""
            if abstract_elem is not None:
                # Abstract may have multiple AbstractText elements
                abstract_texts = abstract_elem.findall(".//AbstractText")
                if abstract_texts:
                    abstract_parts = []
                    for abstract_text in abstract_texts:
                        label = abstract_text.get("Label", "")
                        text = self._get_text_content(abstract_text)
                        if label and text:
                            abstract_parts.append(f"{label}: {text}")
                        elif text:
                            abstract_parts.append(text)
                    abstract = " ".join(abstract_parts)

            # Extract authors
            authors = self._extract_authors(article)

            # Extract journal information
            journal_elem = article.find(".//Journal")
            journal = ""
            if journal_elem is not None:
                # Try Title first, fallback to ISOAbbreviation
                journal_title = journal_elem.find(".//Title")
                if journal_title is not None and journal_title.text:
                    journal = journal_title.text.strip()
                else:
                    iso_abbr = journal_elem.find(".//ISOAbbreviation")
                    if iso_abbr is not None and iso_abbr.text:
                        journal = iso_abbr.text.strip()

            # Extract publication date
            pub_date = self._extract_publication_date(article)

            # Extract volume, issue, pages
            volume = ""
            issue = ""
            pages = ""
            journal_issue = article.find(".//JournalIssue")
            if journal_issue is not None:
                volume_elem = journal_issue.find(".//Volume")
                if volume_elem is not None and volume_elem.text:
                    volume = volume_elem.text.strip()

                issue_elem = journal_issue.find(".//Issue")
                if issue_elem is not None and issue_elem.text:
                    issue = issue_elem.text.strip()

            pagination = article.find(".//Pagination/MedlinePgn")
            if pagination is not None and pagination.text:
                pages = pagination.text.strip()

            # Extract publication type
            publication_type = "Journal Article"  # Default
            pub_type_list = article.findall(".//PublicationTypeList/PublicationType")
            if pub_type_list:
                # Take the first non-empty publication type
                for pub_type_elem in pub_type_list:
                    if pub_type_elem.text:
                        publication_type = pub_type_elem.text.strip()
                        break

            # Extract MeSH terms
            mesh_terms = self._extract_mesh_terms(medline_citation)

            # Extract language
            language = "en"  # Default to English
            language_elem = article.find(".//Language")
            if language_elem is not None and language_elem.text:
                language = language_elem.text.strip().lower()

            # Build article dictionary
            article_data = {
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "date": pub_date,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "publication_type": publication_type,
                "mesh_terms": mesh_terms,
                "pdf_url": pdf_url,
                "language": language,
            }

            return article_data

        except Exception as e:
            logging.error(f"Error extracting article metadata: {str(e)}")
            return None

    def _extract_authors(self, article):
        """Extract author names from AuthorList.

        Args:
            article: lxml Element for Article

        Returns:
            list: List of author names in "LastName ForeName" format
        """
        authors = []
        author_list = article.find(".//AuthorList")

        if author_list is not None:
            for author in author_list.findall(".//Author"):
                last_name_elem = author.find(".//LastName")
                fore_name_elem = author.find(".//ForeName")

                last_name = (
                    last_name_elem.text.strip()
                    if last_name_elem is not None and last_name_elem.text
                    else ""
                )
                fore_name = (
                    fore_name_elem.text.strip()
                    if fore_name_elem is not None and fore_name_elem.text
                    else ""
                )

                if last_name:
                    # Format: "LastName ForeName"
                    full_name = f"{last_name} {fore_name}" if fore_name else last_name
                    authors.append(full_name)
                else:
                    # Handle collective names
                    collective_name = author.find(".//CollectiveName")
                    if collective_name is not None and collective_name.text:
                        authors.append(collective_name.text.strip())

        return authors

    def _extract_publication_date(self, article):
        """Extract publication date in YYYY-MM-DD format.

        Tries multiple date types: ArticleDate (electronic), JournalIssue/PubDate.

        Args:
            article: lxml Element for Article

        Returns:
            str: Date in YYYY-MM-DD format or empty string
        """
        # Try ArticleDate first (electronic publication)
        article_date = article.find(".//ArticleDate[@DateType='Electronic']")
        if article_date is not None:
            year = self._get_element_text(article_date, ".//Year")
            month = self._get_element_text(article_date, ".//Month")
            day = self._get_element_text(article_date, ".//Day")

            if year:
                month = month.zfill(2) if month else "01"
                day = day.zfill(2) if day else "01"
                return f"{year}-{month}-{day}"

        # Fallback to JournalIssue PubDate
        pub_date = article.find(".//JournalIssue/PubDate")
        if pub_date is not None:
            year = self._get_element_text(pub_date, ".//Year")
            month = self._get_element_text(pub_date, ".//Month")
            day = self._get_element_text(pub_date, ".//Day")

            if year:
                # Convert month name to number if needed
                month_num = self._convert_month_to_number(month) if month else "01"
                day = day.zfill(2) if day else "01"
                return f"{year}-{month_num}-{day}"

            # Handle MedlineDate (e.g., "2023 Jan-Feb")
            medline_date = pub_date.find(".//MedlineDate")
            if medline_date is not None and medline_date.text:
                # Extract year from formats like "2023 Jan-Feb" or "2023"
                date_text = medline_date.text.strip()
                year_match = date_text.split()[0]
                if year_match.isdigit():
                    return f"{year_match}-01-01"

        return ""

    def _extract_mesh_terms(self, medline_citation):
        """Extract MeSH (Medical Subject Headings) terms.

        Args:
            medline_citation: lxml Element for MedlineCitation

        Returns:
            list: List of MeSH descriptor names
        """
        mesh_terms = []
        mesh_heading_list = medline_citation.find(".//MeshHeadingList")

        if mesh_heading_list is not None:
            for mesh_heading in mesh_heading_list.findall(".//MeshHeading"):
                descriptor = mesh_heading.find(".//DescriptorName")
                if descriptor is not None and descriptor.text:
                    mesh_terms.append(descriptor.text.strip())

        return mesh_terms

    def _convert_month_to_number(self, month_str):
        """Convert month name/abbreviation to zero-padded number.

        Args:
            month_str: Month name or abbreviation (e.g., "Jan", "January", "1")

        Returns:
            str: Zero-padded month number (e.g., "01")
        """
        if not month_str:
            return "01"

        # If already a number, zero-pad it
        if month_str.isdigit():
            return month_str.zfill(2)

        # Month name mapping
        months = {
            "jan": "01",
            "january": "01",
            "feb": "02",
            "february": "02",
            "mar": "03",
            "march": "03",
            "apr": "04",
            "april": "04",
            "may": "05",
            "jun": "06",
            "june": "06",
            "jul": "07",
            "july": "07",
            "aug": "08",
            "august": "08",
            "sep": "09",
            "september": "09",
            "oct": "10",
            "october": "10",
            "nov": "11",
            "november": "11",
            "dec": "12",
            "december": "12",
        }

        month_lower = month_str.lower()
        return months.get(month_lower, "01")

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
