"""Tests for scilex.enrich_with_citations module.

All network calls and file I/O are mocked; no real API calls.
"""

from unittest.mock import patch

import pandas as pd
import pytest

_MOCK_MAIN_CONFIG = {
    "collect_name": "test_collect",
    "keywords": [["test"], []],
    "years": [2024],
    "apis": ["SemanticScholar"],
}

_MOCK_API_CONFIG = {
    "SemanticScholar": {"api_key": "test-key"},
    "CrossRef": {"mailto": "test@example.org"},
}

_MOCK_CONFIGS = {
    "main_config": _MOCK_MAIN_CONFIG,
    "api_config": _MOCK_API_CONFIG,
}


def _make_df():
    """Minimal two-row DataFrame: one with DOI, one without."""
    return pd.DataFrame(
        [
            {
                "DOI": "10.1234/paper.1",
                "title": "Paper One",
                "year": "2022",
                "authors": "Smith, John",
                "abstract": "An abstract.",
                "itemType": "journalArticle",
                "journalAbbreviation": "J. Test",
                "volume": "1",
                "issue": "1",
                "pages": "1-10",
                "publisher": "Test Pub",
                "url": "NA",
                "pdf_url": "NA",
                "language": "en",
                "rights": "NA",
                "archive": "SemanticScholar",
                "archiveID": "abc",
                "serie": "NA",
                "conferenceName": "NA",
                "tags": "NA",
                "pwc_url": "NA",
                "github_repo": "NA",
                "nb_citation": "5",
                "date": "2022-01-01",
            },
            {
                "DOI": "NA",
                "title": "Paper Without DOI",
                "year": "2021",
                "authors": "Doe, Jane",
                "abstract": "Another abstract.",
                "itemType": "journalArticle",
                "journalAbbreviation": "J. Other",
                "volume": "2",
                "issue": "2",
                "pages": "11-20",
                "publisher": "Other Pub",
                "url": "NA",
                "pdf_url": "NA",
                "language": "en",
                "rights": "NA",
                "archive": "OpenAlex",
                "archiveID": "def",
                "serie": "NA",
                "conferenceName": "NA",
                "tags": "NA",
                "pwc_url": "NA",
                "github_repo": "NA",
                "nb_citation": "0",
                "date": "2021-06-01",
            },
        ]
    )


class TestMain:
    @patch(
        "scilex.enrich_with_citations.format_bibtex_entry", return_value="@article{}"
    )
    @patch("scilex.enrich_with_citations.load_aggregated_data")
    @patch("scilex.enrich_with_citations.fetch_references_batch")
    @patch("scilex.enrich_with_citations.fetch_citers_batch")
    @patch("scilex.enrich_with_citations.load_config")
    def test_main_runs_without_error(
        self,
        mock_load_config,
        mock_citers,
        mock_refs,
        mock_load_data,
        mock_format,
        tmp_path,
    ):
        config = dict(_MOCK_MAIN_CONFIG, output_dir=str(tmp_path))
        mock_load_config.return_value = (config, _MOCK_API_CONFIG)
        mock_load_data.return_value = _make_df()
        mock_refs.return_value = {"10.1234/paper.1": ["10.5678/cited"]}
        mock_citers.return_value = {"10.1234/paper.1": ["10.9999/citer"]}

        from scilex.enrich_with_citations import main

        with patch("sys.argv", ["scilex-enrich-citations"]):
            main()  # must not raise

    @patch(
        "scilex.enrich_with_citations.format_bibtex_entry", return_value="@article{}"
    )
    @patch("scilex.enrich_with_citations.load_aggregated_data")
    @patch("scilex.enrich_with_citations.fetch_citers_batch")
    @patch("scilex.enrich_with_citations.fetch_references_batch")
    @patch("scilex.enrich_with_citations.load_config")
    def test_skip_citers_flag(
        self,
        mock_load_config,
        mock_refs,
        mock_citers,
        mock_load_data,
        mock_format,
        tmp_path,
    ):
        config = dict(_MOCK_MAIN_CONFIG, output_dir=str(tmp_path))
        mock_load_config.return_value = (config, _MOCK_API_CONFIG)
        mock_load_data.return_value = _make_df()
        mock_refs.return_value = {}

        from scilex.enrich_with_citations import main

        with patch("sys.argv", ["scilex-enrich-citations", "--skip-citers"]):
            main()

        mock_citers.assert_not_called()

    @patch("scilex.enrich_with_citations.load_config")
    def test_exits_on_missing_collect_name(self, mock_load_config):
        mock_load_config.return_value = ({"output_dir": "/tmp"}, {})

        from scilex.enrich_with_citations import main

        with patch("sys.argv", ["scilex-enrich-citations"]), pytest.raises(SystemExit):
            main()

    @patch(
        "scilex.enrich_with_citations.format_bibtex_entry", return_value="@article{}"
    )
    @patch("scilex.enrich_with_citations.load_aggregated_data")
    @patch("scilex.enrich_with_citations.fetch_references_batch")
    @patch("scilex.enrich_with_citations.fetch_citers_batch")
    @patch("scilex.enrich_with_citations.load_config")
    def test_doi_raw_is_string_not_none(
        self,
        mock_load_config,
        mock_citers,
        mock_refs,
        mock_load_data,
        mock_format,
        tmp_path,
    ):
        """generate_citation_key receives '' for missing DOI, never None."""
        config = dict(_MOCK_MAIN_CONFIG, output_dir=str(tmp_path))
        mock_load_config.return_value = (config, _MOCK_API_CONFIG)
        mock_load_data.return_value = _make_df()
        mock_refs.return_value = {}
        mock_citers.return_value = {}

        captured_dois = []

        def capture_key(doi, row, used_keys):
            captured_dois.append(doi)
            key = f"key{len(used_keys)}"
            used_keys.add(key)
            return key

        from scilex.enrich_with_citations import main

        with (
            patch(
                "scilex.enrich_with_citations.generate_citation_key",
                side_effect=capture_key,
            ),
            patch("sys.argv", ["scilex-enrich-citations"]),
        ):
            main()

        # Paper with valid DOI passes the DOI string
        assert "10.1234/paper.1" in captured_dois
        # Paper with missing DOI passes "" (empty string), never None
        assert "" in captured_dois
        assert None not in captured_dois

    @patch(
        "scilex.enrich_with_citations.format_bibtex_entry", return_value="@article{}"
    )
    @patch("scilex.enrich_with_citations.load_aggregated_data")
    @patch("scilex.enrich_with_citations.fetch_references_batch")
    @patch("scilex.enrich_with_citations.fetch_citers_batch")
    @patch("scilex.enrich_with_citations.load_config")
    def test_limit_flag_restricts_papers(
        self,
        mock_load_config,
        mock_citers,
        mock_refs,
        mock_load_data,
        mock_format,
        tmp_path,
    ):
        config = dict(_MOCK_MAIN_CONFIG, output_dir=str(tmp_path))
        mock_load_config.return_value = (config, _MOCK_API_CONFIG)
        mock_load_data.return_value = _make_df()
        mock_refs.return_value = {}
        mock_citers.return_value = {}

        from scilex.enrich_with_citations import main

        with patch("sys.argv", ["scilex-enrich-citations", "--limit", "1"]):
            main()

        # With --limit 1, only 1 DOI should be sent to fetch_references_batch
        dois_fetched = mock_refs.call_args[0][0]
        assert len(dois_fetched) == 1
