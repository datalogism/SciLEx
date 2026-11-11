"""Unit tests for PubMed collector.

Tests cover:
- ESearch query construction (single/dual keyword groups)
- Date range filtering
- MEDLINE XML parsing
- PMCID extraction and PDF URL construction
- Publication type mapping
- MeSH terms extraction
"""

from pathlib import Path

from lxml import etree

from scilex.crawlers.collectors import PubMed_collector


class TestPubMedCollector:
    """Test PubMed collector functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.year = 2024
        self.single_keywords = [["machine learning", "deep learning"], []]
        self.dual_keywords = [["knowledge graph"], ["biomedical"]]
        self.fixtures_dir = Path(__file__).parent / "fixtures" / "pubmed"

    def test_single_keyword_group_query(self):
        """Test query construction with single keyword group.

        In production, queryCompositor() breaks single keyword groups into
        one query per keyword. Each collector receives keyword: ["term"],
        so OR logic is achieved by dispatching separate queries, not within
        a single PubMed query.
        """
        # Simulate what queryCompositor passes for single keyword mode:
        # one keyword wrapped in a list
        data_query = {
            "keyword": ["machine learning"],
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)
        query = collector.construct_search_query()

        # Should contain the keyword with Title/Abstract field tag
        assert "machine learning" in query
        assert "[Title/Abstract]" in query
        # Should have date filter
        assert "2024/01/01" in query
        assert "2024/12/31" in query

    def test_dual_keyword_group_query(self):
        """Test query construction with dual keyword groups (AND logic)."""
        data_query = {
            "keyword": self.dual_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)
        query = collector.construct_search_query()

        # Should have both groups (keywords are URL-encoded)
        assert "knowledge%20graph" in query or "knowledge graph" in query
        assert "biomedical" in query
        # Should have AND between groups
        assert " AND " in query
        # Should have date filter
        assert "2024/01/01" in query
        assert "2024/12/31" in query

    def test_esearch_xml_parsing(self):
        """Test ESearch response parsing to extract PMIDs."""
        fixture_path = self.fixtures_dir / "esearch_response.xml"

        with open(fixture_path, "rb") as f:
            xml_content = f.read()

        tree = etree.fromstring(xml_content)

        # Extract total count
        total_elem = tree.find(".//Count")
        assert total_elem is not None
        assert int(total_elem.text) == 42

        # Extract PMIDs
        id_elements = tree.findall(".//Id")
        pmids = [id_elem.text for id_elem in id_elements if id_elem.text]

        assert len(pmids) == 3
        assert "12345678" in pmids
        assert "23456789" in pmids
        assert "34567890" in pmids

    def test_efetch_with_pmcid_parsing(self):
        """Test EFetch parsing for article with PMCID (open access)."""
        fixture_path = self.fixtures_dir / "efetch_with_pmcid.xml"

        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)

        with open(fixture_path, "rb") as f:
            xml_content = f.read()

        articles = collector._parse_efetch_response(xml_content)

        assert len(articles) == 1
        article = articles[0]

        # Check identifiers
        assert article["pmid"] == "12345678"
        assert article["pmcid"] == "PMC9876543"
        assert article["doi"] == "10.1093/database/baad001"

        # Check PDF URL construction
        assert (
            article["pdf_url"]
            == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/pdf/"
        )

        # Check basic metadata
        assert "Machine learning approaches" in article["title"]
        assert len(article["authors"]) == 2
        assert "Smith John" in article["authors"]
        assert "Doe Jane" in article["authors"]

        # Check abstract (with labels)
        assert "BACKGROUND" in article["abstract"]
        assert "METHODS" in article["abstract"]
        assert "RESULTS" in article["abstract"]

        # Check journal
        assert "Database" in article["journal"]

        # Check publication type
        assert article["publication_type"] == "Journal Article"

        # Check MeSH terms
        assert len(article["mesh_terms"]) == 2
        assert "Machine Learning" in article["mesh_terms"]
        assert "Knowledge Bases" in article["mesh_terms"]

        # Check date
        assert article["date"] == "2024-01-15"

        # Check pagination
        assert article["pages"] == "123-145"
        assert article["volume"] == "21"
        assert article["issue"] == "3"

        # Check language
        assert article["language"] == "eng"

    def test_efetch_without_pmcid_parsing(self):
        """Test EFetch parsing for article without PMCID (paywalled)."""
        fixture_path = self.fixtures_dir / "efetch_without_pmcid.xml"

        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)

        with open(fixture_path, "rb") as f:
            xml_content = f.read()

        articles = collector._parse_efetch_response(xml_content)

        assert len(articles) == 1
        article = articles[0]

        # Check identifiers
        assert article["pmid"] == "23456789"
        assert article["pmcid"] == ""  # No PMCID
        assert article["doi"] == "10.1038/s41586-024-07146-0"

        # Check NO PDF URL (paywalled)
        assert article["pdf_url"] == ""

        # Check basic metadata
        assert "Deep learning for drug discovery" in article["title"]
        assert len(article["authors"]) == 1
        assert "Johnson Alice" in article["authors"]

        # Check publication type (Review)
        assert article["publication_type"] == "Review"

        # Check MeSH terms
        assert len(article["mesh_terms"]) == 2
        assert "Machine Learning" in article["mesh_terms"]
        assert "Drug Discovery" in article["mesh_terms"]

    def test_efetch_batch_parsing(self):
        """Test EFetch parsing for multiple articles in batch."""
        fixture_path = self.fixtures_dir / "efetch_multiple.xml"

        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)

        with open(fixture_path, "rb") as f:
            xml_content = f.read()

        articles = collector._parse_efetch_response(xml_content)

        # Should parse both articles
        assert len(articles) == 2

        # First article has PMCID
        assert articles[0]["pmid"] == "12345678"
        assert articles[0]["pmcid"] == "PMC9876543"
        assert (
            articles[0]["pdf_url"]
            == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/pdf/"
        )

        # Second article does not have PMCID
        assert articles[1]["pmid"] == "23456789"
        assert articles[1]["pmcid"] == ""
        assert articles[1]["pdf_url"] == ""

    def test_month_conversion(self):
        """Test month name to number conversion."""
        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)

        # Test month name conversion
        assert collector._convert_month_to_number("Jan") == "01"
        assert collector._convert_month_to_number("February") == "02"
        assert collector._convert_month_to_number("mar") == "03"
        assert collector._convert_month_to_number("December") == "12"

        # Test numeric month
        assert collector._convert_month_to_number("5") == "05"
        assert collector._convert_month_to_number("12") == "12"

        # Test invalid/empty
        assert collector._convert_month_to_number("") == "01"
        assert collector._convert_month_to_number("invalid") == "01"

    def test_pmcid_extraction_variants(self):
        """Test PMCID extraction handles PMC prefix variants."""
        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)

        # Test with PMC prefix already present
        xml_with_prefix = b"""<?xml version="1.0"?>
        <PubmedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <PMID>12345678</PMID>
                    <Article>
                        <ArticleTitle>Test</ArticleTitle>
                        <Journal><Title>Test</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
                        <AuthorList></AuthorList>
                    </Article>
                </MedlineCitation>
                <PubmedData>
                    <ArticleIdList>
                        <ArticleId IdType="pmc">PMC1234567</ArticleId>
                    </ArticleIdList>
                </PubmedData>
            </PubmedArticle>
        </PubmedArticleSet>"""

        articles = collector._parse_efetch_response(xml_with_prefix)
        assert len(articles) == 1
        assert articles[0]["pmcid"] == "PMC1234567"
        assert (
            articles[0]["pdf_url"]
            == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/pdf/"
        )

        # Test with numeric only (no PMC prefix)
        xml_without_prefix = b"""<?xml version="1.0"?>
        <PubmedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <PMID>12345678</PMID>
                    <Article>
                        <ArticleTitle>Test</ArticleTitle>
                        <Journal><Title>Test</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
                        <AuthorList></AuthorList>
                    </Article>
                </MedlineCitation>
                <PubmedData>
                    <ArticleIdList>
                        <ArticleId IdType="pmc">1234567</ArticleId>
                    </ArticleIdList>
                </PubmedData>
            </PubmedArticle>
        </PubmedArticleSet>"""

        articles = collector._parse_efetch_response(xml_without_prefix)
        assert len(articles) == 1
        assert articles[0]["pmcid"] == "PMC1234567"
        assert (
            articles[0]["pdf_url"]
            == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/pdf/"
        )

    def test_database_parameter(self):
        """Test that collector uses 'pubmed' database (not 'pmc')."""
        data_query = {
            "keyword": self.single_keywords,
            "year": self.year,
            "id_collect": 0,
            "total_art": 0,
            "coll_art": 0,
            "last_page": 0,
            "state": 0,
        }

        collector = PubMed_collector(data_query, "/tmp", None)
        url = collector.get_configurated_url()

        # Should use pubmed database
        assert "db=pubmed" in url
        # Should NOT use pmc database
        assert "db=pmc" not in url
