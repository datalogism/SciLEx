"""Tests for scilex/citations/citations_tools.py (mocked network calls)."""

from unittest.mock import MagicMock, patch

import requests

from scilex.citations.citations_tools import _oc_url, getCitationCounts

OC_TOOLS = "scilex.citations.citations_tools"


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


def _counts_by_kind(citations, references):
    """Fake ``_oc_request`` answering the two v2 count operations."""

    def fake(kind, doi):
        value = {"citation-count": citations, "reference-count": references}[kind]
        return _mock_response([{"count": str(value)}])

    return fake


class TestOcUrl:
    def test_counts_use_v2_with_doi_prefix(self):
        assert _oc_url("citation-count", "10.1/a") == (
            "https://api.opencitations.net/index/v2/citation-count/doi:10.1/a"
        )

    def test_lists_use_v1_direct_host(self):
        assert _oc_url("references", "10.1/a") == (
            "https://api.opencitations.net/index/v1/references/10.1/a"
        )


class TestGetCitationCounts:
    def test_success_returns_counts(self):
        with patch(f"{OC_TOOLS}._oc_request", side_effect=_counts_by_kind(12, 3)):
            counts, stats = getCitationCounts("10.9999/test")
        assert counts == {"nb_citations": 12, "nb_cited": 3}
        assert stats == {"cit_status": "success", "ref_status": "success"}

    def test_doi_prefix_stripped(self):
        with patch(
            f"{OC_TOOLS}._oc_request", side_effect=_counts_by_kind(0, 0)
        ) as mock_request:
            getCitationCounts("https://doi.org/10.1/TEST")
        assert {call.args[1] for call in mock_request.call_args_list} == {"10.1/test"}

    def test_timeout_and_error_statuses(self):
        def fake(kind, doi):
            if kind == "citation-count":
                raise requests.exceptions.Timeout()
            raise requests.exceptions.ConnectionError()

        with patch(f"{OC_TOOLS}._oc_request", side_effect=fake):
            counts, stats = getCitationCounts("10.9999/fail")
        assert counts == {"nb_citations": 0, "nb_cited": 0}
        assert stats == {"cit_status": "timeout", "ref_status": "error"}

    def test_unexpected_json_is_an_error(self):
        with patch(f"{OC_TOOLS}._oc_request", return_value=_mock_response([])):
            counts, stats = getCitationCounts("10.9999/badjson")
        assert counts == {"nb_citations": 0, "nb_cited": 0}
        assert stats["cit_status"] == "error"

    def test_invalid_doi_makes_no_request(self):
        with patch(f"{OC_TOOLS}._oc_request") as mock_request:
            _, stats = getCitationCounts("")
        mock_request.assert_not_called()
        assert stats == {"cit_status": "error", "ref_status": "error"}
