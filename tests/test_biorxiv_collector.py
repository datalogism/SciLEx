"""Unit tests for BioRxiv collector.

Tests cover:
- URL construction (date range from year)
- JSON response parsing (/details/ endpoint)
- Keyword matching (single, dual, case-insensitive, AND logic)
- Cache directory helpers
- Two-phase runCollect logic
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from scilex.crawlers.collectors import BioRxiv_collector


def _make_data_query(year=2024, keywords=None, collect_id=0):
    """Helper to create a minimal data_query dict."""
    if keywords is None:
        keywords = ["CRISPR"]
    return {
        "keyword": keywords,
        "year": year,
        "id_collect": collect_id,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


def _make_collector(year=2024, keywords=None, data_path="/tmp"):
    """Helper to create a collector instance."""
    return BioRxiv_collector(_make_data_query(year, keywords), data_path, None)


class TestBioRxivURLConstruction:
    """Test URL construction for the bioRxiv /details/ endpoint."""

    def test_url_contains_year_range(self):
        collector = _make_collector(year=2024)
        url_template = collector.get_configurated_url()
        assert "2024-01-01" in url_template
        assert "2024-12-31" in url_template

    def test_url_has_cursor_placeholder(self):
        collector = _make_collector(year=2023)
        url_template = collector.get_configurated_url()
        # Should have a {} placeholder for cursor offset
        assert "{}" in url_template

    def test_url_fills_cursor(self):
        collector = _make_collector(year=2024)
        url = collector.get_configurated_url().format(200)
        assert "/200" in url
        assert "{}" not in url

    def test_url_base(self):
        collector = _make_collector()
        url_template = collector.get_configurated_url()
        assert url_template.startswith("https://api.biorxiv.org/details/biorxiv/")

    def test_construct_search_query_returns_empty(self):
        """bioRxiv has no keyword search -- construct_search_query returns ''."""
        collector = _make_collector()
        assert collector.construct_search_query() == ""


class TestBioRxivParsing:
    """Test JSON response parsing from /details/ endpoint."""

    def _mock_response(self, total, papers):
        """Create a mock requests.Response with bioRxiv JSON."""
        resp = MagicMock()
        resp.json.return_value = {
            "messages": [
                {
                    "status": "ok",
                    "cursor": 0,
                    "count": len(papers),
                    "total": str(total),
                }
            ],
            "collection": papers,
        }
        resp.status_code = 200
        resp.elapsed = MagicMock(total_seconds=MagicMock(return_value=0.5))
        return resp

    def test_parse_extracts_total(self):
        papers = [{"doi": "10.1101/2024.01.01.000001", "title": "Test"}]
        collector = _make_collector()
        resp = self._mock_response(42, papers)
        result = collector.parsePageResults(resp, 1)
        assert result["total"] == 42

    def test_parse_extracts_results(self):
        papers = [
            {"doi": "10.1101/2024.01.01.000001", "title": "Paper A"},
            {"doi": "10.1101/2024.01.02.000002", "title": "Paper B"},
        ]
        collector = _make_collector()
        resp = self._mock_response(2, papers)
        result = collector.parsePageResults(resp, 1)
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Paper A"

    def test_parse_handles_empty_messages(self):
        collector = _make_collector()
        resp = MagicMock()
        resp.json.return_value = {"messages": [], "collection": []}
        result = collector.parsePageResults(resp, 1)
        assert result["total"] == 0
        assert result["results"] == []


class TestBioRxivKeywordMatching:
    """Test keyword matching logic."""

    def _paper(self, title="", abstract=""):
        return {"title": title, "abstract": abstract}

    def test_single_keyword_in_title(self):
        paper = self._paper(title="CRISPR gene editing in plants")
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is True

    def test_single_keyword_in_abstract(self):
        paper = self._paper(abstract="We used CRISPR-Cas9 for gene editing.")
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is True

    def test_keyword_not_found(self):
        paper = self._paper(title="Protein folding", abstract="No match here.")
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is False

    def test_case_insensitive_match(self):
        paper = self._paper(title="crispr gene editing")
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is True

    def test_case_insensitive_keyword(self):
        paper = self._paper(title="CRISPR Gene Editing")
        assert BioRxiv_collector._keyword_matches(paper, ["crispr"]) is True

    def test_and_logic_both_present(self):
        """All keywords must match (AND logic)."""
        paper = self._paper(
            title="CRISPR in neuroscience",
            abstract="Gene therapy for brain disorders.",
        )
        assert (
            BioRxiv_collector._keyword_matches(paper, ["CRISPR", "neuroscience"])
            is True
        )

    def test_and_logic_one_missing(self):
        """If one keyword is missing, should not match."""
        paper = self._paper(title="CRISPR gene editing", abstract="No neuro here.")
        assert (
            BioRxiv_collector._keyword_matches(paper, ["CRISPR", "neuroscience"])
            is False
        )

    def test_empty_keywords_always_matches(self):
        paper = self._paper(title="Anything")
        assert BioRxiv_collector._keyword_matches(paper, []) is True

    def test_none_title_and_abstract(self):
        paper = {"title": None, "abstract": None}
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is False

    def test_missing_title_and_abstract(self):
        paper = {}
        assert BioRxiv_collector._keyword_matches(paper, ["CRISPR"]) is False

    def test_substring_match(self):
        """Should match substrings (e.g., 'RNA' in 'mRNA')."""
        paper = self._paper(title="mRNA vaccine development")
        assert BioRxiv_collector._keyword_matches(paper, ["RNA"]) is True


class TestBioRxivCacheHelpers:
    """Test cache directory and existence helpers."""

    def test_cache_dir_path(self):
        collector = _make_collector(year=2024, data_path="/tmp/test_collect")
        cache_dir = collector._get_year_cache_dir(2024)
        assert Path(cache_dir) == Path("/tmp/test_collect/BioRxiv/_cache/2024")

    def test_cache_exists_with_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "2024")
            os.makedirs(cache_dir)
            # No marker yet
            collector = _make_collector(data_path=tmpdir)
            assert collector._year_cache_exists(cache_dir) is False

            # Create marker
            with open(os.path.join(cache_dir, "_complete"), "w") as f:
                f.write("100")
            assert collector._year_cache_exists(cache_dir) is True


class TestBioRxivFilterAndSave:
    """Test the filter-and-save phase."""

    def test_filter_saves_matching_papers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up cache dir with papers
            cache_dir = os.path.join(tmpdir, "BioRxiv", "_cache", "2024")
            os.makedirs(cache_dir)

            papers = [
                {
                    "doi": "10.1101/2024.01.01.000001",
                    "title": "CRISPR gene editing in plants",
                    "abstract": "We describe a novel CRISPR method.",
                },
                {
                    "doi": "10.1101/2024.01.02.000002",
                    "title": "Protein folding dynamics",
                    "abstract": "Molecular dynamics simulation.",
                },
                {
                    "doi": "10.1101/2024.01.03.000003",
                    "title": "New CRISPR-Cas9 variant",
                    "abstract": "Improved efficiency.",
                },
            ]

            page_data = {"results": papers, "total": 3, "page": 1}
            with open(os.path.join(cache_dir, "page_1"), "w") as f:
                json.dump(page_data, f)

            # Create collector
            collector = _make_collector(
                year=2024, keywords=["CRISPR"], data_path=tmpdir
            )

            state = collector._filter_and_save(cache_dir, ["CRISPR"])

            # Should find 2 matching papers
            assert state["coll_art"] == 2
            assert state["state"] == 1

            # Verify output file exists
            output_path = os.path.join(tmpdir, "BioRxiv", "0", "page_1")
            assert os.path.isfile(output_path)

            with open(output_path) as f:
                saved = json.load(f)
            assert len(saved["results"]) == 2

    def test_filter_no_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "BioRxiv", "_cache", "2024")
            os.makedirs(cache_dir)

            papers = [
                {
                    "doi": "10.1101/2024.01.01.000001",
                    "title": "Protein folding",
                    "abstract": "No match.",
                }
            ]

            page_data = {"results": papers, "total": 1, "page": 1}
            with open(os.path.join(cache_dir, "page_1"), "w") as f:
                json.dump(page_data, f)

            collector = _make_collector(
                year=2024, keywords=["CRISPR"], data_path=tmpdir
            )
            state = collector._filter_and_save(cache_dir, ["CRISPR"])

            assert state["coll_art"] == 0


class TestBioRxivRunCollect:
    """Test the two-phase runCollect method."""

    def test_already_complete(self):
        """If state == 1, runCollect should return immediately."""
        data_query = _make_data_query()
        data_query["state"] = 1
        collector = BioRxiv_collector(data_query, "/tmp", None)

        result = collector.runCollect()
        assert result["state"] == 1

    @patch.object(BioRxiv_collector, "_fetch_year_data")
    def test_uses_cache_when_exists(self, mock_fetch):
        """If cache exists, should NOT call _fetch_year_data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache with complete marker
            cache_dir = os.path.join(tmpdir, "BioRxiv", "_cache", "2024")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "_complete"), "w") as f:
                f.write("0")
            # Create empty page file so filter works
            with open(os.path.join(cache_dir, "page_1"), "w") as f:
                json.dump({"results": [], "total": 0, "page": 1}, f)

            collector = _make_collector(
                year=2024, keywords=["CRISPR"], data_path=tmpdir
            )
            collector.runCollect()

            mock_fetch.assert_not_called()

    def test_api_name(self):
        collector = _make_collector()
        assert collector.get_api_name() == "BioRxiv"

    def test_max_by_page(self):
        collector = _make_collector()
        assert collector.get_max_by_page() == 100


class TestBioRxivHooksIntegration:
    """Reconciliation with the generic collector hooks."""

    def test_rate_limit_from_defaults(self):
        assert _make_collector().rate_limit == 1.0

    def test_complete_marker_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "BioRxiv", "_cache", "2024")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "_complete"), "w") as f:
                f.write("0")
            with open(os.path.join(cache_dir, "page_1"), "w") as f:
                json.dump({"results": [{"title": "CRISPR"}], "total": 1}, f)
            collector = _make_collector(keywords=["CRISPR"], data_path=tmpdir)
            state = collector.runCollect()
            query_dir = os.path.join(tmpdir, "BioRxiv", "0")
            assert state["state"] == 1
            assert os.path.isfile(os.path.join(query_dir, "_complete"))
            assert not os.path.exists(os.path.join(query_dir, "_state"))

    def test_fetch_failure_leaves_query_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = _make_collector(data_path=tmpdir)
            with patch.object(
                BioRxiv_collector, "_fetch_year_data", side_effect=RuntimeError("boom")
            ):
                state = collector.runCollect()
            query_dir = os.path.join(tmpdir, "BioRxiv", "0")
            assert state["state"] == 0
            assert os.path.isfile(os.path.join(query_dir, "_state"))
            assert not os.path.exists(os.path.join(query_dir, "_complete"))
