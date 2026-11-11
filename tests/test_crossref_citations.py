"""Tests for CrossRef batch citation lookup.

Tests the getCrossRefCitationsBatch function and its integration
into the citation pipeline (Cache → SS → CrossRef → OpenCitations).
Also tests batch cache functions and the phase-based fetch_citations_for_dataframe.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ============================================================================
# getCrossRefCitationsBatch unit tests (mocked, no network)
# ============================================================================


class TestGetCrossRefCitationsBatch:
    """Test the batch CrossRef lookup function."""

    def _get_fn(self):
        from scilex.citations.citations_tools import getCrossRefCitationsBatch

        return getCrossRefCitationsBatch

    @patch("scilex.citations.citations_tools.requests.get")
    def test_basic_batch_lookup(self, mock_get):
        """Batch lookup returns correct DOI→(cit, ref) mapping."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/test.001",
                        "is-referenced-by-count": 42,
                        "references-count": 15,
                    },
                    {
                        "DOI": "10.1234/test.002",
                        "is-referenced-by-count": 7,
                        "references-count": 30,
                    },
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        result = fn.__wrapped__.__wrapped__.__wrapped__(
            ["10.1234/test.001", "10.1234/test.002"]
        )

        assert result == {
            "10.1234/test.001": (42, 15),
            "10.1234/test.002": (7, 30),
        }

    @patch("scilex.citations.citations_tools.requests.get")
    def test_missing_dois_omitted(self, mock_get):
        """DOIs not found in CrossRef are simply omitted from result."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/found",
                        "is-referenced-by-count": 5,
                        "references-count": 10,
                    },
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        result = fn.__wrapped__.__wrapped__.__wrapped__(
            ["10.1234/found", "10.9999/not-in-crossref"]
        )

        assert "10.1234/found" in result
        assert "10.9999/not-in-crossref" not in result

    @patch("scilex.citations.citations_tools.requests.get")
    def test_empty_input_returns_empty(self, mock_get):
        """Empty DOI list returns empty dict without API call."""
        fn = self._get_fn()
        result = fn.__wrapped__.__wrapped__.__wrapped__([])

        assert result == {}
        mock_get.assert_not_called()

    @patch("scilex.citations.citations_tools.requests.get")
    def test_doi_case_normalization(self, mock_get):
        """Result keys are lowercased for consistent lookup."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/UPPER.Case",
                        "is-referenced-by-count": 3,
                        "references-count": 8,
                    },
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        result = fn.__wrapped__.__wrapped__.__wrapped__(["10.1234/UPPER.Case"])

        assert "10.1234/upper.case" in result

    @patch("scilex.citations.citations_tools.requests.get")
    def test_mailto_included_in_url(self, mock_get):
        """When mailto is provided, it appears in the request URL."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"items": []}}
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        fn.__wrapped__.__wrapped__.__wrapped__(
            ["10.1234/test"], mailto="user@example.org"
        )

        url = mock_get.call_args[0][0]
        assert "mailto=user@example.org" in url

    @patch("scilex.citations.citations_tools.requests.get")
    def test_no_mailto_excluded_from_url(self, mock_get):
        """When mailto is None, it does not appear in the URL."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"items": []}}
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        fn.__wrapped__.__wrapped__.__wrapped__(["10.1234/test"])

        url = mock_get.call_args[0][0]
        assert "mailto" not in url

    @patch("scilex.citations.citations_tools.requests.get")
    def test_url_contains_filter_and_select(self, mock_get):
        """Request URL contains proper filter and select parameters."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"items": []}}
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        fn.__wrapped__.__wrapped__.__wrapped__(["10.1234/a", "10.1234/b"])

        url = mock_get.call_args[0][0]
        assert "filter=doi:10.1234/a,doi:10.1234/b" in url
        assert "select=DOI,is-referenced-by-count,references-count" in url
        assert "rows=2" in url

    @patch("scilex.citations.citations_tools.requests.get")
    def test_missing_count_fields_default_to_zero(self, mock_get):
        """If CrossRef omits count fields, they default to 0."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/sparse",
                        # no is-referenced-by-count or references-count
                    },
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = self._get_fn()
        result = fn.__wrapped__.__wrapped__.__wrapped__(["10.1234/sparse"])

        assert result["10.1234/sparse"] == (0, 0)


# ============================================================================
# CROSSREF_BATCH_SIZE constant
# ============================================================================


class TestCrossRefBatchSize:
    def test_batch_size_is_20(self):
        from scilex.citations.citations_tools import CROSSREF_BATCH_SIZE

        assert CROSSREF_BATCH_SIZE == 20


# ============================================================================
# OpenCitations worker (the only per-paper tier reachable in production)
# ============================================================================


class TestOpenCitationsWorker:
    """The phase-4 worker only calls OpenCitations; SS/CrossRef are earlier phases."""

    @patch("scilex.citations.fetcher.cit_tools.getCitationCounts")
    def test_worker_returns_counts_and_source(self, mock_oc):
        from scilex.citations.fetcher import _fetch_opencitations_for_doi

        mock_oc.return_value = (
            {"nb_citations": 1, "nb_cited": 2},
            {"cit_status": "success", "ref_status": "success"},
        )

        result = _fetch_opencitations_for_doi("10.1234/not-in-cr")

        assert result["nb_citations"] == 1
        assert result["nb_cited"] == 2
        assert result["api_stats"]["source"] == "opencitations"
        mock_oc.assert_called_once_with("10.1234/not-in-cr")


# ============================================================================
# Batch cache functions
# ============================================================================


@pytest.fixture
def cache_db(tmp_path):
    """Create an initialized temporary cache database."""
    from scilex.citations.cache import close_connections, initialize_cache

    # Close any stale thread-local connections from previous tests
    close_connections()

    db_path = tmp_path / "test_cache.db"
    initialize_cache(db_path)
    yield db_path

    # Clean up thread-local connection so next test gets a fresh one
    close_connections()


class TestGetCachedCitationsBatch:
    """Test batch cache lookup."""

    def test_empty_dois_returns_empty(self, cache_db):
        from scilex.citations.cache import get_cached_citations_batch

        result = get_cached_citations_batch([], cache_db)
        assert result == {}

    def test_returns_cached_entries(self, cache_db):
        from scilex.citations.cache import (
            cache_citations_batch,
            get_cached_citations_batch,
        )

        # Populate cache
        ok = {"cit_status": "success", "ref_status": "success"}
        cache_citations_batch(
            [
                {
                    "doi": "10.1/a",
                    "citations_json": '{"citing":[]}',
                    "nb_cited": 5,
                    "nb_citations": 10,
                    "api_stats": ok,
                },
                {
                    "doi": "10.1/b",
                    "citations_json": '{"citing":[]}',
                    "nb_cited": 3,
                    "nb_citations": 7,
                    "api_stats": ok,
                },
            ],
            cache_db,
        )

        result = get_cached_citations_batch(["10.1/a", "10.1/b", "10.1/miss"], cache_db)

        assert "10.1/a" in result
        assert "10.1/b" in result
        assert "10.1/miss" not in result
        assert result["10.1/a"]["nb_cited"] == 5
        assert result["10.1/a"]["nb_citations"] == 10
        assert result["10.1/b"]["nb_cited"] == 3

    def test_expired_entries_excluded(self, cache_db):
        """Expired cache entries should not be returned."""
        from scilex.citations.cache import get_cached_citations_batch

        # Manually insert an expired entry
        conn = sqlite3.connect(str(cache_db))
        past = (datetime.now() - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO citations VALUES (?,?,?,?,?,?,?,?)",
            ("10.1/expired", "{}", 1, 2, "success", "success", past, past),
        )
        conn.commit()
        conn.close()

        result = get_cached_citations_batch(["10.1/expired"], cache_db)
        assert result == {}

    def test_chunking_with_many_dois(self, cache_db):
        """Should handle more DOIs than chunk size (500)."""
        from scilex.citations.cache import (
            cache_citations_batch,
            get_cached_citations_batch,
        )

        # Create 600 entries
        entries = [
            {
                "doi": f"10.1/{i}",
                "citations_json": "{}",
                "nb_cited": i,
                "nb_citations": i * 2,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            }
            for i in range(600)
        ]
        cache_citations_batch(entries, cache_db)

        # Query all 600
        dois = [f"10.1/{i}" for i in range(600)]
        result = get_cached_citations_batch(dois, cache_db)

        assert len(result) == 600
        assert result["10.1/0"]["nb_cited"] == 0
        assert result["10.1/599"]["nb_cited"] == 599


class TestCacheCitationsBatch:
    """Test batch cache write."""

    def test_empty_entries_noop(self, cache_db):
        from scilex.citations.cache import cache_citations_batch, get_cache_stats

        cache_citations_batch([], cache_db)
        stats = get_cache_stats(cache_db)
        assert stats["active_entries"] == 0

    def test_writes_multiple_entries(self, cache_db):
        from scilex.citations.cache import (
            cache_citations_batch,
            get_cached_citations_batch,
        )

        entries = [
            {
                "doi": "10.1/x",
                "citations_json": '{"data":"x"}',
                "nb_cited": 2,
                "nb_citations": 5,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            },
            {
                "doi": "10.1/y",
                "citations_json": '{"data":"y"}',
                "nb_cited": 8,
                "nb_citations": 12,
                "api_stats": {"cit_status": "success", "ref_status": "error"},
            },
        ]
        cache_citations_batch(entries, cache_db)

        found = get_cached_citations_batch(["10.1/x", "10.1/y"], cache_db)
        x = found.get("10.1/x")
        y = found.get("10.1/y")
        assert x is not None
        assert x["nb_cited"] == 2
        assert y is not None
        assert y["nb_citations"] == 12
        assert y["api_stats"]["ref_status"] == "error"

    def test_upsert_overwrites_existing(self, cache_db):
        from scilex.citations.cache import (
            cache_citations_batch,
            get_cached_citations_batch,
        )

        # Insert initial value
        cache_citations_batch(
            [
                {
                    "doi": "10.1/z",
                    "citations_json": '{"old":true}',
                    "nb_cited": 1,
                    "nb_citations": 1,
                    "api_stats": {"cit_status": "success", "ref_status": "success"},
                }
            ],
            cache_db,
        )

        # Overwrite with batch
        cache_citations_batch(
            [
                {
                    "doi": "10.1/z",
                    "citations_json": '{"new":true}',
                    "nb_cited": 99,
                    "nb_citations": 100,
                    "api_stats": {"cit_status": "success", "ref_status": "success"},
                }
            ],
            cache_db,
        )

        z = get_cached_citations_batch(["10.1/z"], cache_db)["10.1/z"]
        assert z["nb_cited"] == 99
        assert z["citations"] == '{"new":true}'


# ============================================================================
# Phase-based fetch_citations_for_dataframe integration tests
# ============================================================================


def _get_parallel_fn():
    from scilex.citations.fetcher import fetch_citations_for_dataframe

    return fetch_citations_for_dataframe


class TestFetchCitationsParallelPhased:
    """Test the phase-based fetch_citations_for_dataframe function."""

    def _make_df(self, papers):
        """Create a test DataFrame from a list of paper dicts."""
        rows = []
        for p in papers:
            rows.append(
                {
                    "DOI": p.get("DOI", "NA"),
                    "title": p.get("title", "Test"),
                    "ss_citation_count": p.get("ss_cit", None),
                    "ss_reference_count": p.get("ss_ref", None),
                    "oa_citation_count": p.get("oa_cit", None),
                }
            )
        return pd.DataFrame(rows)

    @patch("scilex.citations.cache.get_cached_citations_batch")
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_phase1_cache_hits_resolve_papers(
        self, mock_stats, mock_init, mock_batch_cache
    ):
        """Phase 1: Papers found in cache are resolved without API calls."""
        mock_init.return_value = Path("/tmp/test.db")
        mock_batch_cache.return_value = {
            "10.1/a": {
                "citations": '{"source":"cache"}',
                "nb_cited": 5,
                "nb_citations": 10,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            },
            "10.1/b": {
                "citations": '{"source":"cache"}',
                "nb_cited": 2,
                "nb_citations": 3,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            },
        }

        df = self._make_df(
            [
                {"DOI": "10.1/a"},
                {"DOI": "10.1/b"},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        assert stats["cache_hit"] == 2
        assert stats["cache_miss"] == 0
        assert nb_citeds[0] == 5
        assert nb_citations[1] == 3

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_phase2_ss_data_used(
        self, mock_stats, mock_init, mock_batch_cache, mock_cache_write
    ):
        """Phase 2: Papers with SS data are resolved without API calls."""
        mock_init.return_value = Path("/tmp/test.db")

        df = self._make_df(
            [
                {"DOI": "10.1/a", "ss_cit": 20, "ss_ref": 8},
                {"DOI": "10.1/b", "ss_cit": 15, "ss_ref": 5},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        assert stats["ss_used"] == 2
        assert stats["cache_miss"] == 2
        assert nb_citations[0] == 20
        assert nb_citeds[0] == 8
        # Batch cache should have been called for SS results
        mock_cache_write.assert_called_once()
        assert len(mock_cache_write.call_args[0][0]) == 2

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_phase2b_openalex_data_used(
        self, mock_stats, mock_init, mock_batch_cache, mock_cache_write
    ):
        """Phase 2b: Papers with OpenAlex citation data resolved without API calls."""
        mock_init.return_value = Path("/tmp/test.db")

        df = self._make_df(
            [
                {"DOI": "10.1/a", "oa_cit": 100},
                {"DOI": "10.1/b", "oa_cit": 25},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        assert stats["oa_used"] == 2
        assert stats["ss_used"] == 0
        assert stats["cr_used"] == 0
        # OA only provides citation count (nb_citations), not reference count
        assert nb_citations[0] == 100
        assert nb_citations[1] == 25
        assert nb_citeds[0] == 0  # reference count unknown from OA
        assert nb_citeds[1] == 0
        # Batch cache should have been called for OA results
        mock_cache_write.assert_called()

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.fetcher.cit_tools.getCrossRefCitationsBatch")
    @patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_phase3_crossref_batch_resolves(
        self, mock_stats, mock_init, mock_batch_cache, mock_cr_batch, mock_cache_write
    ):
        """Phase 3: CrossRef batch API resolves papers."""
        mock_init.return_value = Path("/tmp/test.db")
        mock_cr_batch.return_value = {
            "10.1/a": (42, 15),
            "10.1/b": (7, 30),
        }

        df = self._make_df(
            [
                {"DOI": "10.1/a"},
                {"DOI": "10.1/b"},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        assert stats["cr_used"] == 2
        assert nb_citations[0] == 42
        assert nb_citeds[0] == 15
        mock_cr_batch.assert_called_once()

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.fetcher.cit_tools.getCitationCounts")
    @patch(
        "scilex.citations.fetcher.cit_tools.getCrossRefCitationsBatch", return_value={}
    )
    @patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_phase4_oc_fallback(
        self,
        mock_stats,
        mock_init,
        mock_batch_cache,
        mock_cr_batch,
        mock_oc,
        mock_cache_write,
    ):
        """Phase 4: OpenCitations used for papers not resolved by phases 1-3."""
        mock_init.return_value = Path("/tmp/test.db")
        mock_oc.return_value = (
            {"nb_citations": 1, "nb_cited": 2},
            {"cit_status": "success", "ref_status": "success"},
        )

        df = self._make_df([{"DOI": "10.1/a"}])

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, num_workers=1, use_cache=True)

        assert stats["opencitations_used"] == 1
        assert nb_citeds[0] == 2
        assert nb_citations[0] == 1
        mock_oc.assert_called_once()

    def test_no_doi_papers_resolved_immediately(self):
        """Papers without DOI are resolved instantly (no API calls)."""
        df = self._make_df(
            [
                {"DOI": "NA"},
                {"DOI": ""},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=False)

        assert stats["no_doi"] == 2
        assert stats["success"] == 0

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.fetcher.cit_tools.getCrossRefCitationsBatch")
    @patch("scilex.citations.cache.get_cached_citations_batch")
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_mixed_phases_all_tiers(
        self, mock_stats, mock_init, mock_batch_cache, mock_cr_batch, mock_cache_write
    ):
        """Mix of papers resolved by different phases including OpenAlex."""
        mock_init.return_value = Path("/tmp/test.db")

        # Paper 0: cache, Paper 1: SS, Paper 2: OA, Paper 3: CrossRef, Paper 4: no DOI
        mock_batch_cache.return_value = {
            "10.1/cached": {
                "citations": '{"source":"cache"}',
                "nb_cited": 1,
                "nb_citations": 2,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            },
        }
        mock_cr_batch.return_value = {
            "10.1/crossref": (50, 20),
        }

        df = self._make_df(
            [
                {"DOI": "10.1/cached"},
                {"DOI": "10.1/ss-paper", "ss_cit": 30, "ss_ref": 10},
                {"DOI": "10.1/oa-paper", "oa_cit": 75},
                {"DOI": "10.1/crossref"},
                {"DOI": "NA"},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        assert stats["cache_hit"] == 1
        assert stats["ss_used"] == 1
        assert stats["oa_used"] == 1
        assert stats["cr_used"] == 1
        assert stats["no_doi"] == 1
        assert stats["opencitations_used"] == 0
        assert nb_citations[0] == 2  # cached
        assert nb_citations[1] == 30  # SS
        assert nb_citations[2] == 75  # OpenAlex
        assert nb_citations[3] == 50  # CrossRef

    @patch("scilex.citations.cache.cache_citations_batch")
    @patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
    @patch("scilex.citations.cache.initialize_cache")
    @patch(
        "scilex.citations.cache.get_cache_stats",
        return_value={"active_entries": 0, "expired_entries": 0},
    )
    def test_ss_takes_priority_over_openalex(
        self, mock_stats, mock_init, mock_batch_cache, mock_cache_write
    ):
        """SS (Phase 2) takes priority over OpenAlex (Phase 2b) when both available."""
        mock_init.return_value = Path("/tmp/test.db")

        df = self._make_df(
            [
                {"DOI": "10.1/a", "ss_cit": 30, "ss_ref": 10, "oa_cit": 100},
            ]
        )

        fn = _get_parallel_fn()
        extras, nb_citeds, nb_citations, stats = fn(df, use_cache=True)

        # SS should resolve it, not OA
        assert stats["ss_used"] == 1
        assert stats["oa_used"] == 0
        assert nb_citations[0] == 30  # SS citation count, not OA's 100
        assert nb_citeds[0] == 10  # SS reference count
