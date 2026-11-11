"""Tests for scilex.citations.reference_fetcher module.

All HTTP calls are mocked; no real network access.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.citations.reference_fetcher import (
    _fetch_citers_oc,
    _fetch_references_crossref,
    _fetch_references_oc,
    _is_retryable_ss_error,
    _save_cache,
    _ss_batch_lookup,
    fetch_citers_batch,
    fetch_references_batch,
    fetch_references_ss,
)


@pytest.fixture(autouse=True)
def _no_ss_batch(request, monkeypatch):
    """Keep the batch lookup offline; its own tests opt out with ``real_batch``."""
    if "real_batch" in request.keywords:
        return
    monkeypatch.setattr(
        "scilex.citations.reference_fetcher._ss_batch_lookup",
        lambda *args, **kwargs: {},
    )


class TestIsRetryableSsError:
    def test_timeout_is_retryable(self):
        assert _is_retryable_ss_error(requests.exceptions.Timeout()) is True

    def test_connection_error_is_retryable(self):
        assert _is_retryable_ss_error(requests.exceptions.ConnectionError()) is True

    def test_429_is_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is True

    def test_500_is_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is True

    def test_503_is_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is True

    def test_404_not_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is False

    def test_401_not_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is False

    def test_403_not_retryable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        exc = requests.exceptions.HTTPError(response=mock_resp)
        assert _is_retryable_ss_error(exc) is False

    def test_non_http_exception_not_retryable(self):
        assert _is_retryable_ss_error(ValueError("bad")) is False

    def test_http_error_no_response_not_retryable(self):
        exc = requests.exceptions.HTTPError(response=None)
        assert _is_retryable_ss_error(exc) is False


class TestDoSsRequest:
    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_returns_doi_list_on_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"citedPaper": {"externalIds": {"DOI": "10.1234/cited.001"}}},
                {"citedPaper": {"externalIds": {"DOI": "10.5678/cited.002"}}},
            ]
        }
        mock_get.return_value = mock_resp

        from scilex.citations.reference_fetcher import _do_ss_request

        result = _do_ss_request("10.1234/paper", api_key=None)
        assert result == ["10.1234/cited.001", "10.5678/cited.002"]

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_returns_empty_on_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        from scilex.citations.reference_fetcher import _do_ss_request

        result = _do_ss_request("10.9999/missing", api_key=None)
        assert result == []

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_api_key_added_to_headers(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp

        from scilex.citations.reference_fetcher import _do_ss_request

        _do_ss_request("10.1234/paper", api_key="my-key")
        headers = mock_get.call_args[1]["headers"]
        assert headers.get("x-api-key") == "my-key"

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_skips_entries_without_doi(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"citedPaper": {"externalIds": {}}},
                {"citedPaper": {"externalIds": {"DOI": "10.1234/valid"}}},
            ]
        }
        mock_get.return_value = mock_resp

        from scilex.citations.reference_fetcher import _do_ss_request

        result = _do_ss_request("10.0000/paper", api_key=None)
        assert result == ["10.1234/valid"]


class TestFetchReferencesSs:
    @patch("scilex.citations.reference_fetcher._fetch_ss_no_key")
    def test_returns_refs_without_api_key(self, mock_fn):
        mock_fn.return_value = ["10.1/a", "10.2/b"]
        result = fetch_references_ss("10.0/paper")
        assert result == ["10.1/a", "10.2/b"]

    @patch("scilex.citations.reference_fetcher._fetch_ss_with_key")
    def test_returns_refs_with_api_key(self, mock_fn):
        mock_fn.return_value = ["10.1/a"]
        result = fetch_references_ss("10.0/paper", api_key="key123")
        assert result == ["10.1/a"]

    @patch("scilex.citations.reference_fetcher._fetch_ss_no_key")
    def test_returns_empty_on_exception(self, mock_fn):
        mock_fn.side_effect = requests.exceptions.RequestException("failed")
        result = fetch_references_ss("10.0/paper")
        assert result == []

    @patch("scilex.citations.reference_fetcher._fetch_ss_no_key")
    def test_strips_doi_url_prefix(self, mock_fn):
        mock_fn.return_value = []
        fetch_references_ss("https://doi.org/10.1234/paper")
        call_doi = mock_fn.call_args[0][0]
        assert call_doi == "10.1234/paper"


class TestFetchReferencesCrossref:
    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_returns_doi_list_on_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "reference": [
                    {"DOI": "10.1111/cited.a"},
                    {"DOI": "10.2222/cited.b"},
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = _fetch_references_crossref.__wrapped__.__wrapped__.__wrapped__
        result = fn("10.0/paper")
        assert result == ["10.1111/cited.a", "10.2222/cited.b"]

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_returns_empty_on_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        fn = _fetch_references_crossref.__wrapped__.__wrapped__.__wrapped__
        result = fn("10.9999/missing")
        assert result == []

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_skips_refs_without_doi(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "reference": [
                    {"title": "no doi ref"},
                    {"DOI": "10.3333/has-doi"},
                ]
            }
        }
        mock_get.return_value = mock_resp

        fn = _fetch_references_crossref.__wrapped__.__wrapped__.__wrapped__
        result = fn("10.0/paper")
        assert result == ["10.3333/has-doi"]

    @patch("scilex.citations.reference_fetcher.requests.get")
    def test_mailto_passed_as_param(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"reference": []}}
        mock_get.return_value = mock_resp

        fn = _fetch_references_crossref.__wrapped__.__wrapped__.__wrapped__
        fn("10.0/paper", mailto="user@example.org")
        params = mock_get.call_args[1]["params"]
        assert params.get("mailto") == "user@example.org"


class TestFetchReferencesOc:
    @patch("scilex.citations.reference_fetcher.getReferences")
    def test_returns_doi_list_on_success(self, mock_get_refs):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"cited": "https://doi.org/10.1111/ref.a"},
            {"cited": "https://doi.org/10.2222/ref.b"},
        ]
        mock_get_refs.return_value = (True, mock_resp, None)

        result = _fetch_references_oc("10.0/paper")
        assert result == ["10.1111/ref.a", "10.2222/ref.b"]

    @patch("scilex.citations.reference_fetcher.getReferences")
    def test_returns_empty_on_failure(self, mock_get_refs):
        mock_get_refs.return_value = (False, None, None)
        result = _fetch_references_oc("10.0/paper")
        assert result == []

    @patch("scilex.citations.reference_fetcher.getReferences")
    def test_returns_empty_on_json_error(self, mock_get_refs):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_get_refs.return_value = (True, mock_resp, None)
        result = _fetch_references_oc("10.0/paper")
        assert result == []


class TestSaveCache:
    def test_writes_json_file(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        data = {"10.1/a": ["10.2/b"], "10.3/c": []}
        _save_cache(cache_path, data)
        with open(cache_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_creates_parent_directory(self, tmp_path):
        cache_path = str(tmp_path / "nested" / "dir" / "cache.json")
        _save_cache(cache_path, {})
        assert (tmp_path / "nested" / "dir" / "cache.json").exists()


class TestFetchReferencesBatch:
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_basic_fetch(self, mock_ss):
        mock_ss.return_value = ["10.1/cited"]
        result = fetch_references_batch(["10.0/paper"], cache_path=None)
        assert result == {"10.0/paper": ["10.1/cited"]}

    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_loads_from_cache(self, mock_ss, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(
            json.dumps({"10.0/cached": ["10.1/ref"]}), encoding="utf-8"
        )
        result = fetch_references_batch(["10.0/cached"], cache_path=str(cache_file))
        assert result == {"10.0/cached": ["10.1/ref"]}
        mock_ss.assert_not_called()

    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_falls_through_to_crossref(self, mock_ss, mock_cr, mock_oc):
        mock_ss.return_value = []
        mock_cr.return_value = ["10.9/crossref"]
        result = fetch_references_batch(["10.0/paper"], cache_path=None)
        assert result["10.0/paper"] == ["10.9/crossref"]
        mock_oc.assert_not_called()

    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_falls_through_to_oc(self, mock_ss, mock_cr, mock_oc):
        mock_ss.return_value = []
        mock_cr.return_value = []
        mock_oc.return_value = ["10.7/opencitations"]
        result = fetch_references_batch(
            ["10.0/paper"], cache_path=None, fallback_opencitations=True
        )
        assert result["10.0/paper"] == ["10.7/opencitations"]

    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_no_oc_when_disabled(self, mock_ss, mock_cr, mock_oc):
        mock_ss.return_value = []
        mock_cr.return_value = []
        result = fetch_references_batch(
            ["10.0/paper"], cache_path=None, fallback_opencitations=False
        )
        assert result["10.0/paper"] == []
        mock_oc.assert_not_called()

    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_empty_doi_skipped(self, mock_ss):
        result = fetch_references_batch([""], cache_path=None)
        assert result[""] == []
        mock_ss.assert_not_called()

    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_cache_written_at_end(self, mock_ss, tmp_path):
        mock_ss.return_value = ["10.1/ref"]
        cache_file = tmp_path / "cache.json"
        fetch_references_batch(["10.0/paper"], cache_path=str(cache_file))
        assert cache_file.exists()
        loaded = json.loads(cache_file.read_text())
        assert loaded["10.0/paper"] == ["10.1/ref"]

    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_multiple_dois(self, mock_ss):
        mock_ss.side_effect = [["10.1/a"], ["10.2/b"]]
        result = fetch_references_batch(["10.0/paper1", "10.0/paper2"], cache_path=None)
        assert result["10.0/paper1"] == ["10.1/a"]
        assert result["10.0/paper2"] == ["10.2/b"]


class TestFetchCitersOc:
    @patch("scilex.citations.reference_fetcher.getCitations")
    def test_returns_citing_dois(self, mock_get_cit):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"citing": "https://doi.org/10.5/citer.a"},
            {"citing": "https://doi.org/10.6/citer.b"},
        ]
        mock_get_cit.return_value = (True, mock_resp, None)

        result = _fetch_citers_oc("10.0/paper")
        assert result == ["10.5/citer.a", "10.6/citer.b"]

    @patch("scilex.citations.reference_fetcher.getCitations")
    def test_returns_empty_on_failure(self, mock_get_cit):
        mock_get_cit.return_value = (False, None, None)
        result = _fetch_citers_oc("10.0/paper")
        assert result == []

    @patch("scilex.citations.reference_fetcher.getCitations")
    def test_returns_empty_on_json_error(self, mock_get_cit):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_get_cit.return_value = (True, mock_resp, None)
        result = _fetch_citers_oc("10.0/paper")
        assert result == []


class TestFetchCitersBatch:
    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_basic_fetch(self, mock_ss):
        mock_ss.return_value = ["10.5/citer"]
        result = fetch_citers_batch(["10.0/paper"], cache_path=None)
        assert result == {"10.0/paper": ["10.5/citer"]}

    @patch("scilex.citations.reference_fetcher._fetch_citers_oc")
    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_falls_through_to_oc(self, mock_ss, mock_oc):
        mock_ss.return_value = []
        mock_oc.return_value = ["10.7/citer"]
        result = fetch_citers_batch(
            ["10.0/paper"], cache_path=None, fallback_opencitations=True
        )
        assert result["10.0/paper"] == ["10.7/citer"]

    @patch("scilex.citations.reference_fetcher._fetch_citers_oc")
    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_no_oc_when_disabled(self, mock_ss, mock_oc):
        mock_ss.return_value = []
        result = fetch_citers_batch(
            ["10.0/paper"], cache_path=None, fallback_opencitations=False
        )
        assert result["10.0/paper"] == []
        mock_oc.assert_not_called()

    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_loads_from_cache(self, mock_ss, tmp_path):
        cache_file = tmp_path / "citers.json"
        cache_file.write_text(
            json.dumps({"10.0/cached": ["10.5/citer"]}), encoding="utf-8"
        )
        result = fetch_citers_batch(["10.0/cached"], cache_path=str(cache_file))
        assert result == {"10.0/cached": ["10.5/citer"]}
        mock_ss.assert_not_called()

    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_cache_written_at_end(self, mock_ss, tmp_path):
        mock_ss.return_value = ["10.5/citer"]
        cache_file = tmp_path / "citers.json"
        fetch_citers_batch(["10.0/paper"], cache_path=str(cache_file))
        assert cache_file.exists()
        loaded = json.loads(cache_file.read_text())
        assert loaded["10.0/paper"] == ["10.5/citer"]


class TestBatchCancellation:
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_references_stop_before_next_paper_and_keep_cache(self, mock_ss, tmp_path):
        mock_ss.return_value = ["10.9/ref"]
        cache = tmp_path / "refs.json"
        progress = []
        result = fetch_references_batch(
            ["10.1/a", "10.1/b", "10.1/c"],
            cache_path=str(cache),
            should_stop=lambda: mock_ss.call_count >= 1,
            on_progress=lambda done, total: progress.append((done, total)),
        )
        assert mock_ss.call_count == 1
        assert result == {"10.1/a": ["10.9/ref"]}
        assert json.loads(cache.read_text()) == {"10.1/a": ["10.9/ref"]}
        assert progress == [(1, 3)]

    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    def test_references_skip_fallbacks_when_stopped(self, mock_ss, mock_cr, mock_oc):
        mock_ss.return_value = []
        result = fetch_references_batch(
            ["10.1/a"], should_stop=lambda: mock_ss.call_count >= 1
        )
        mock_cr.assert_not_called()
        mock_oc.assert_not_called()
        assert result == {}

    @patch("scilex.citations.reference_fetcher._fetch_citers_oc")
    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    def test_citers_stop_between_tiers(self, mock_ss, mock_oc):
        mock_ss.return_value = []
        result = fetch_citers_batch(
            ["10.1/a", "10.1/b"], should_stop=lambda: mock_ss.call_count >= 1
        )
        mock_oc.assert_not_called()
        assert mock_ss.call_count == 1
        assert result == {}


def _batch_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.real_batch
class TestSSBatchLookup:
    @patch("scilex.citations.reference_fetcher.requests.post")
    def test_maps_references_and_unknown_papers(self, mock_post):
        mock_post.return_value = _batch_response(
            [
                {
                    "paperId": "a",
                    "references": [
                        {"paperId": "r1", "externalIds": {"DOI": "10.1/r1 "}},
                        {"paperId": "r2", "externalIds": None},
                    ],
                },
                None,
            ]
        )
        result = _ss_batch_lookup(["10.0/a", "10.0/unknown"], "references", "key")
        assert result == {"10.0/a": ["10.1/r1"], "10.0/unknown": []}
        kwargs = mock_post.call_args.kwargs
        assert kwargs["json"] == {"ids": ["DOI:10.0/a", "DOI:10.0/unknown"]}
        assert kwargs["params"] == {"fields": "references.externalIds,referenceCount"}
        assert kwargs["headers"] == {"x-api-key": "key"}

    @patch("scilex.citations.reference_fetcher.SS_BATCH_SIZE", 2)
    @patch("scilex.citations.reference_fetcher.requests.post")
    def test_splits_into_chunks(self, mock_post):
        mock_post.side_effect = [
            _batch_response([{"citations": []}, {"citations": []}]),
            _batch_response([{"citations": [{"externalIds": {"DOI": "10.9/c"}}]}]),
        ]
        result = _ss_batch_lookup(["10.0/a", "10.0/b", "10.0/c"], "citations")
        assert mock_post.call_count == 2
        assert result["10.0/c"] == ["10.9/c"]

    @patch("scilex.citations.reference_fetcher._post_ss_batch")
    def test_cut_list_left_out(self, mock_batch):
        """SS empties some citation lists in big responses: retry those papers."""
        mock_batch.return_value = [
            {"citationCount": 9177, "citations": []},
            {
                "citationCount": 40289,
                "citations": [
                    {"externalIds": {"DOI": f"10.9/{i}"}} for i in range(9999)
                ],
            },
            {"citationCount": 0, "citations": []},
        ]
        result = _ss_batch_lookup(["10.0/a", "10.0/b", "10.0/c"], "citations")
        assert "10.0/a" not in result
        assert len(result["10.0/b"]) == 9999
        assert result["10.0/c"] == []

    @patch("scilex.citations.reference_fetcher.fetch_citers_ss")
    @patch("scilex.citations.reference_fetcher._post_ss_batch")
    def test_cut_list_falls_back_to_single_request(self, mock_batch, mock_single):
        mock_batch.return_value = [{"citationCount": 50, "citations": []}]
        mock_single.return_value = ["10.9/c"]
        result = fetch_citers_batch(["10.0/a"], cache_path=None)
        assert result == {"10.0/a": ["10.9/c"]}
        mock_single.assert_called_once()

    @patch("scilex.citations.reference_fetcher.SS_BATCH_RETRY_PAUSE", 0)
    @patch("scilex.citations.reference_fetcher._post_ss_batch")
    def test_failed_chunk_left_out(self, mock_batch):
        mock_batch.side_effect = requests.exceptions.HTTPError("400")
        assert _ss_batch_lookup(["10.0/a"], "references") == {}
        assert mock_batch.call_count == 2

    @patch("scilex.citations.reference_fetcher.SS_BATCH_RETRY_PAUSE", 0)
    @patch("scilex.citations.reference_fetcher.SS_BATCH_SIZE", 1)
    @patch("scilex.citations.reference_fetcher._post_ss_batch")
    def test_failed_chunk_retried_after_the_others(self, mock_batch):
        """A batch lost to a 429 is retried once instead of 100 single calls."""
        mock_batch.side_effect = [
            requests.exceptions.HTTPError("429"),
            [{"references": [{"externalIds": {"DOI": "10.1/b"}}]}],
            [{"references": [{"externalIds": {"DOI": "10.1/a"}}]}],
        ]
        result = _ss_batch_lookup(["10.0/a", "10.0/b"], "references")
        assert result == {"10.0/a": ["10.1/a"], "10.0/b": ["10.1/b"]}
        sent = [c.args[0] for c in mock_batch.call_args_list]
        assert sent == [["DOI:10.0/a"], ["DOI:10.0/b"], ["DOI:10.0/a"]]

    @patch("scilex.citations.reference_fetcher.fetch_references_ss")
    @patch("scilex.citations.reference_fetcher._post_ss_batch")
    def test_batch_answer_skips_single_request(self, mock_batch, mock_single):
        mock_batch.return_value = [
            {"references": [{"externalIds": {"DOI": "10.1/r"}}]},
        ]
        result = fetch_references_batch(["https://doi.org/10.0/a"], cache_path=None)
        assert result == {"https://doi.org/10.0/a": ["10.1/r"]}
        mock_single.assert_not_called()


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = MagicMock()
    response.status_code = status
    return requests.exceptions.HTTPError(str(status), response=response)


class TestSSSingleBreaker:
    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher._fetch_ss_no_key")
    def test_stops_ss_after_repeated_429(self, mock_ss, mock_cr, mock_oc):
        mock_ss.side_effect = _http_error(429)
        mock_cr.return_value = ["10.9/cr"]
        dois = [f"10.0/{i}" for i in range(6)]
        result = fetch_references_batch(dois, cache_path=None)
        assert mock_ss.call_count == 3
        assert mock_cr.call_count == 6
        assert all(refs == ["10.9/cr"] for refs in result.values())

    @patch("scilex.citations.reference_fetcher._fetch_citers_oc")
    @patch("scilex.citations.reference_fetcher._fetch_ss_citers_no_key")
    def test_success_resets_the_count(self, mock_ss, mock_oc):
        mock_ss.side_effect = [
            _http_error(429),
            _http_error(429),
            ["10.9/c"],
            _http_error(429),
            _http_error(429),
            ["10.9/d"],
        ]
        mock_oc.return_value = []
        fetch_citers_batch([f"10.0/{i}" for i in range(6)], cache_path=None)
        assert mock_ss.call_count == 6

    @patch("scilex.citations.reference_fetcher._fetch_references_oc")
    @patch("scilex.citations.reference_fetcher._fetch_references_crossref")
    @patch("scilex.citations.reference_fetcher._fetch_ss_no_key")
    def test_client_errors_do_not_open_it(self, mock_ss, mock_cr, mock_oc):
        mock_ss.side_effect = _http_error(400)
        mock_cr.return_value = []
        mock_oc.return_value = []
        fetch_references_batch([f"10.0/{i}" for i in range(5)], cache_path=None)
        assert mock_ss.call_count == 5
