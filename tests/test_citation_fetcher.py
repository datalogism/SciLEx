"""Tests for scilex.citations.fetcher (checkpointing, cache gating, DOI handling)."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scilex.citations.fetcher import fetch_citations_for_dataframe
from scilex.pipeline.enrichment import (
    use_openalex_citations_fallback,
    use_semantic_scholar_citations_fallback,
)

OC_SUCCESS = (
    {"nb_citations": 1, "nb_cited": 2},
    {"cit_status": "success", "ref_status": "success"},
)
OC_TIMEOUT = (
    {"nb_citations": 0, "nb_cited": 0},
    {"cit_status": "timeout", "ref_status": "timeout"},
)

CIT = "scilex.citations.fetcher.cit_tools"


def _df(dois, **columns):
    data = {"DOI": dois, **columns}
    return pd.DataFrame(data)


def _run(df, **kwargs):
    kwargs.setdefault("use_cache", False)
    kwargs.setdefault("num_workers", 1)
    return fetch_citations_for_dataframe(df, **kwargs)


@patch(f"{CIT}.getCitationCounts", return_value=OC_SUCCESS)
@patch(f"{CIT}.getCrossRefCitationsBatch", return_value={})
class TestCheckpointing:
    def _stale_checkpoint(self, path):
        path.write_text(
            json.dumps(
                {
                    "last_index": 1,
                    "stats": {"success": 2},
                    "extras": ["stale", "stale"],
                    "nb_citeds": [9, 9],
                    "nb_citations": [9, 9],
                }
            )
        )

    def test_stale_checkpoint_ignored_without_resume(self, _cr, mock_oc, tmp_path):
        checkpoint = tmp_path / "ckpt.json"
        self._stale_checkpoint(checkpoint)

        _, nb_citeds, nb_citations, stats = _run(
            _df(["10.1/a", "10.1/b"]),
            checkpoint_path=str(checkpoint),
            resume=False,
        )

        assert mock_oc.call_count == 2
        assert nb_citeds == [2, 2]
        assert nb_citations == [1, 1]
        assert stats["success"] == 2

    def test_legacy_last_index_checkpoint_read_on_resume(self, _cr, mock_oc, tmp_path):
        checkpoint = tmp_path / "ckpt.json"
        self._stale_checkpoint(checkpoint)

        extras, nb_citeds, _, stats = _run(
            _df(["10.1/a", "10.1/b", "10.1/c"]),
            checkpoint_path=str(checkpoint),
            resume=True,
        )

        assert mock_oc.call_count == 1  # only the third paper
        assert extras[0] == "stale"
        assert nb_citeds[:2] == [9, 9]
        assert stats["success"] == 3

    def test_checkpoint_records_resolved_positions_not_watermark(
        self, _cr, mock_oc, tmp_path
    ):
        """An unresolved early paper must not be skipped on resume."""
        checkpoint = tmp_path / "ckpt.json"
        mock_oc.side_effect = lambda doi: OC_TIMEOUT if doi == "10.1/a" else OC_SUCCESS
        df = _df(["10.1/a", "10.1/b", "10.1/c"])

        _run(df, checkpoint_path=str(checkpoint), checkpoint_interval=1)

        saved = json.loads(checkpoint.read_text())
        assert saved["resolved_positions"] == [1, 2]

        mock_oc.reset_mock()
        mock_oc.side_effect = None
        mock_oc.return_value = OC_SUCCESS
        _, _, nb_citations, _ = _run(df, checkpoint_path=str(checkpoint), resume=True)

        mock_oc.assert_called_once_with("10.1/a")
        assert nb_citations == [1, 1, 1]

    def test_crossref_out_of_order_batches_keep_gaps_unresolved(
        self, mock_cr, mock_oc, tmp_path
    ):
        """CrossRef answering only for the last batch leaves earlier papers pending."""
        checkpoint = tmp_path / "ckpt.json"
        dois = [f"10.1/p{i}" for i in range(25)]
        mock_cr.side_effect = lambda batch, mailto=None: (
            {d: (3, 4) for d in batch} if "10.1/p24" in batch else {}
        )
        mock_oc.return_value = OC_TIMEOUT

        _run(_df(dois), checkpoint_path=str(checkpoint), checkpoint_interval=1)

        saved = json.loads(checkpoint.read_text())
        assert saved["resolved_positions"] == [20, 21, 22, 23, 24]


class TestCacheDisabled:
    @patch(f"{CIT}.getCitationCounts", return_value=OC_SUCCESS)
    @patch(f"{CIT}.getCrossRefCitationsBatch", return_value={})
    def test_no_cache_call_when_disabled(self, _cr, _oc):
        with (
            patch("scilex.citations.cache.initialize_cache") as init,
            patch("scilex.citations.cache.get_cached_citations_batch") as get_batch,
            patch("scilex.citations.cache.cache_citations_batch") as put_batch,
        ):
            _, _, _, stats = _run(
                _df(["10.1/a"], ss_citation_count=[None], oa_citation_count=[None]),
                use_cache=False,
            )

        for mocked in (init, get_batch, put_batch):
            mocked.assert_not_called()
        assert stats["opencitations_used"] == 1
        assert stats["cache_miss"] == 0


@patch(f"{CIT}.getCrossRefCitationsBatch", return_value={})
@patch("scilex.citations.cache.get_cache_stats")
@patch("scilex.citations.cache.get_cached_citations_batch", return_value={})
@patch("scilex.citations.cache.initialize_cache", return_value=Path("/tmp/x.db"))
class TestCacheGating:
    def test_failed_opencitations_not_cached(self, _init, _batch, mock_stats, _cr):
        mock_stats.return_value = {"active_entries": 0, "expired_entries": 0}
        with (
            patch(f"{CIT}.getCitationCounts", return_value=OC_TIMEOUT),
            patch("scilex.citations.cache.cache_citations_batch") as put_batch,
        ):
            _, _, _, stats = _run(_df(["10.1/a"]), use_cache=True)

        put_batch.assert_not_called()
        assert stats["timeout"] == 1
        assert stats["success"] == 0

    def test_successful_opencitations_cached(self, _init, _batch, mock_stats, _cr):
        mock_stats.return_value = {"active_entries": 0, "expired_entries": 0}
        with (
            patch(f"{CIT}.getCitationCounts", return_value=OC_SUCCESS),
            patch("scilex.citations.cache.cache_citations_batch") as put_batch,
        ):
            _run(_df(["10.1/a"]), use_cache=True)

        put_batch.assert_called_once()
        assert put_batch.call_args[0][0][0]["doi"] == "10.1/a"


class TestDoiNormalization:
    @patch(f"{CIT}.getCitationCounts")
    @patch(f"{CIT}.getCrossRefCitationsBatch")
    def test_prefixed_mixed_case_doi_matches_crossref_result(self, mock_cr, mock_oc):
        mock_cr.return_value = {"10.1234/abc": (7, 3)}

        _, nb_citeds, nb_citations, stats = _run(_df(["https://doi.org/10.1234/ABC"]))

        mock_cr.assert_called_once()
        assert mock_cr.call_args[0][0] == ["10.1234/abc"]
        assert (nb_citations[0], nb_citeds[0]) == (7, 3)
        assert stats["cr_used"] == 1
        mock_oc.assert_not_called()

    @patch("scilex.citations.cache.get_cache_stats")
    @patch("scilex.citations.cache.get_cached_citations_batch")
    @patch("scilex.citations.cache.initialize_cache", return_value=Path("/tmp/x.db"))
    def test_cache_lookup_uses_normalized_doi(self, _init, mock_batch, mock_stats):
        mock_stats.return_value = {"active_entries": 0, "expired_entries": 0}
        mock_batch.return_value = {
            "10.1234/abc": {
                "citations": "{}",
                "nb_cited": 1,
                "nb_citations": 2,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            }
        }

        _, _, nb_citations, stats = _run(_df(["doi:10.1234/ABC"]), use_cache=True)

        assert mock_batch.call_args[0][0] == ["10.1234/abc"]
        assert stats["cache_hit"] == 1
        assert nb_citations[0] == 2


class TestUnresolvedValuesAndFallbacks:
    def test_no_doi_rows_are_none_not_empty_string(self):
        extras, nb_citeds, nb_citations, stats = _run(_df(["NA"]))

        assert extras == [None]
        assert nb_citeds == [None]
        assert nb_citations == [None]
        assert stats["no_doi"] == 1

    def test_semantic_scholar_fallback_fires_for_no_doi_rows(self):
        df = _df(["NA"], ss_citation_count=[12], ss_reference_count=[5])
        df["extra"], df["nb_cited"], df["nb_citation"] = _run(df)[:3]

        df = use_semantic_scholar_citations_fallback(df)

        assert df["nb_citation"].iloc[0] == 12
        assert df["nb_cited"].iloc[0] == 5

    def test_openalex_fallback_fires_for_no_doi_rows(self):
        df = _df(["NA"], oa_citation_count=[8])
        df["extra"], df["nb_cited"], df["nb_citation"] = _run(df)[:3]

        df = use_openalex_citations_fallback(df)

        assert df["nb_citation"].iloc[0] == 8

    def test_fallback_treats_empty_string_as_unset(self):
        """Old checkpoints stored '' for unresolved papers."""
        df = pd.DataFrame(
            {
                "nb_citation": [""],
                "nb_cited": [""],
                "ss_citation_count": [4],
                "ss_reference_count": [2],
            }
        )

        df = use_semantic_scholar_citations_fallback(df)

        assert df["nb_citation"].iloc[0] == 4
        assert df["nb_cited"].iloc[0] == 2


@patch(f"{CIT}.getCitationCounts", return_value=OC_SUCCESS)
@patch(f"{CIT}.getCrossRefCitationsBatch", return_value={})
def test_cache_created_in_cache_dir_not_cwd(_cr, _oc, tmp_path, monkeypatch):
    """A packaged app starts in a read-only cwd: the cache must follow cache_dir."""
    from scilex.citations import cache

    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    cache_dir = tmp_path / "review_output"

    try:
        _run(_df(["10.1/a"]), use_cache=True, cache_dir=str(cache_dir))
    finally:
        cache.close_connections()

    assert (cache_dir / "citation_cache.db").is_file()
    assert not (workdir / "output").exists()
