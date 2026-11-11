"""Tests for the scilex.snowball module.

All tests use synthetic data and mock HTTP calls — no real API requests.
"""

from unittest.mock import patch

import pandas as pd

from scilex.snowball.candidates import extract_candidates
from scilex.snowball.filter import apply_snowball_filters
from scilex.snowball.merge import merge_with_corpus

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

CORPUS_DOIS = {"10.1/a", "10.1/b", "10.1/c"}

REFERENCES = {
    "10.1/a": ["10.9/ext1", "10.9/ext2", "10.9/ext3"],
    "10.1/b": ["10.9/ext1", "10.9/ext2"],
    "10.1/c": ["10.9/ext3", "10.9/ext4"],
}

CITERS = {
    "10.1/a": ["10.8/cit1", "10.8/cit2"],
    "10.1/b": ["10.8/cit1"],
    "10.1/c": ["10.8/cit3"],
}


# ---------------------------------------------------------------------------
# Candidate extraction tests
# ---------------------------------------------------------------------------


class TestExtractCandidates:
    def test_backward_direction(self):
        """Backward = only references (what corpus cites)."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="backward", min_frequency=1
        )
        dois = {d for d, _ in candidates}
        # ext1 cited by a and b => freq 2
        assert "10.9/ext1" in dois
        # No citers should appear
        assert "10.8/cit1" not in dois

    def test_forward_direction(self):
        """Forward = only citers (who cites corpus)."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="forward", min_frequency=1
        )
        dois = {d for d, _ in candidates}
        assert "10.8/cit1" in dois
        assert "10.9/ext1" not in dois

    def test_both_direction(self):
        """Both = references + citers."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="both", min_frequency=1
        )
        dois = {d for d, _ in candidates}
        assert "10.9/ext1" in dois
        assert "10.8/cit1" in dois

    def test_frequency_ranking(self):
        """Candidates should be ranked by frequency descending."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="backward", min_frequency=1
        )
        freqs = [f for _, f in candidates]
        assert freqs == sorted(freqs, reverse=True)

    def test_min_frequency_filter(self):
        """Only candidates with freq >= min_frequency are returned."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="backward", min_frequency=2
        )
        for _, freq in candidates:
            assert freq >= 2

    def test_top_k_limit(self):
        """No more than top_k candidates returned."""
        candidates = extract_candidates(
            REFERENCES,
            CITERS,
            CORPUS_DOIS,
            direction="both",
            min_frequency=1,
            top_k=2,
        )
        assert len(candidates) <= 2

    def test_corpus_dois_excluded(self):
        """Corpus DOIs should never appear as candidates."""
        candidates = extract_candidates(
            REFERENCES, CITERS, CORPUS_DOIS, direction="both", min_frequency=1
        )
        dois = {d for d, _ in candidates}
        assert CORPUS_DOIS.isdisjoint(dois)

    def test_empty_caches(self):
        """Empty caches return no candidates."""
        candidates = extract_candidates({}, {}, CORPUS_DOIS, min_frequency=1)
        assert candidates == []


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


class TestCandidatesDoiCase:
    def test_case_variants_are_one_candidate(self):
        refs = {"10.1/a": ["10.18653/V1/X"], "10.1/b": ["10.18653/v1/x"]}
        result = extract_candidates(refs, {}, {"10.1/a", "10.1/b"}, min_frequency=2)
        assert result == [("10.18653/v1/x", 2)]

    def test_corpus_paper_cited_in_other_case_is_not_a_candidate(self):
        refs = {"10.1/a": ["10.1/B"], "10.1/c": ["10.1/B"]}
        corpus = {"10.1/a", "10.1/b", "10.1/c"}
        assert extract_candidates(refs, {}, corpus, min_frequency=1) == []


class TestSnowballFilters:
    def _make_papers(self):
        return [
            {
                "DOI": "10.9/ext1",
                "title": "A Good Paper",
                "abstract": "This is a sufficiently long abstract for testing "
                "that has more than fifty words to pass the filter. " * 2,
                "authors": "Smith, John;Doe, Jane",
                "itemType": "journalArticle",
            },
            {
                "DOI": "10.9/ext2",
                "title": "No Abstract Paper",
                "abstract": "NA",
                "authors": "Brown, Bob",
                "itemType": "conferencePaper",
            },
            {
                "DOI": "NA",
                "title": "No DOI Paper",
                "abstract": "A decent abstract " * 10,
                "authors": "Green, Alice",
                "itemType": "journalArticle",
            },
        ]

    def test_filters_remove_invalid(self):
        """Papers without DOI or abstract should be filtered out."""
        df = apply_snowball_filters(self._make_papers())
        assert len(df) == 1
        assert df.iloc[0]["DOI"] == "10.9/ext1"

    def test_no_doi_requirement(self):
        """With require_doi=False, DOI-less papers pass."""
        df = apply_snowball_filters(self._make_papers(), require_doi=False)
        assert len(df) >= 2

    def test_no_abstract_requirement(self):
        """With require_abstract=False, abstract-less papers pass."""
        df = apply_snowball_filters(self._make_papers(), require_abstract=False)
        assert len(df) >= 2

    def test_empty_input(self):
        """Empty input returns empty DataFrame."""
        df = apply_snowball_filters([])
        assert df.empty


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------


class TestMergeWithCorpus:
    def _corpus_df(self):
        return pd.DataFrame(
            {
                "DOI": ["10.1/a", "10.1/b", "10.1/c"],
                "title": ["Paper A", "Paper B", "Paper C"],
            }
        )

    def _snowball_df(self):
        return pd.DataFrame(
            {
                "DOI": ["10.9/ext1", "10.1/a"],  # ext1 is new, 10.1/a is duplicate
                "title": ["External 1", "Paper A (duplicate)"],
            }
        )

    def test_deduplication(self):
        """Snowball papers already in corpus are removed."""
        merged = merge_with_corpus(self._corpus_df(), self._snowball_df())
        dois = list(merged["DOI"])
        # 10.1/a should appear only once (from corpus)
        assert dois.count("10.1/a") == 1
        assert "10.9/ext1" in dois
        assert len(merged) == 4  # 3 corpus + 1 new

    def test_snowball_depth_column(self):
        """Merged DataFrame should have snowball_depth column."""
        merged = merge_with_corpus(self._corpus_df(), self._snowball_df())
        assert "snowball_depth" in merged.columns
        # Corpus papers have depth 0
        corpus_rows = merged[merged["snowball_depth"] == 0]
        assert len(corpus_rows) == 3
        # New papers have depth 1
        snowball_rows = merged[merged["snowball_depth"] == 1]
        assert len(snowball_rows) == 1

    def test_empty_snowball(self):
        """Empty snowball returns corpus with depth column."""
        merged = merge_with_corpus(self._corpus_df(), pd.DataFrame())
        assert len(merged) == 3
        assert all(merged["snowball_depth"] == 0)

    def test_case_insensitive_dedup(self):
        """DOI deduplication should be case-insensitive."""
        snowball = pd.DataFrame(
            {
                "DOI": ["10.1/A"],  # uppercase version of 10.1/a
                "title": ["Dup"],
            }
        )
        merged = merge_with_corpus(self._corpus_df(), snowball)
        assert len(merged) == 3  # no new papers added


# ---------------------------------------------------------------------------
# Fetcher tests (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchMetadataBatch:
    @patch("scilex.snowball.fetcher._batch_request_no_key")
    def test_basic_fetch(self, mock_batch):
        """Fetch converts SS response to internal format."""
        from scilex.snowball.fetcher import fetch_metadata_batch

        mock_batch.return_value = [
            {
                "paperId": "abc123",
                "title": "Test Paper",
                "abstract": "A test abstract.",
                "authors": [{"name": "Smith, John"}],
                "DOI": "10.9/ext1",
                "publicationDate": "2024-01-15",
                "publicationTypes": ["JournalArticle"],
                "publicationVenue": None,
                "journal": {"name": "Test Journal", "pages": "1-10", "volume": "1"},
                "venue": None,
                "url": "https://example.com",
                "openAccessPdf": {"url": "https://example.com/paper.pdf"},
                "citationCount": 5,
                "referenceCount": 10,
                "externalIds": {"DOI": "10.9/ext1"},
            }
        ]

        results = fetch_metadata_batch(["10.9/ext1"])
        assert len(results) == 1
        assert results[0]["title"] == "Test Paper"
        assert results[0]["archive"] == "SemanticScholar"

    @patch("scilex.snowball.fetcher._batch_request_no_key")
    def test_skips_none_results(self, mock_batch):
        """None entries (not found) are silently skipped."""
        from scilex.snowball.fetcher import fetch_metadata_batch

        mock_batch.return_value = [None, None]
        results = fetch_metadata_batch(["10.9/missing1", "10.9/missing2"])
        assert results == []

    @patch("scilex.snowball.fetcher._batch_request_no_key")
    def test_handles_request_error(self, mock_batch):
        """Request exceptions are caught and logged, not raised."""
        import requests

        from scilex.snowball.fetcher import fetch_metadata_batch

        mock_batch.side_effect = requests.exceptions.ConnectionError("timeout")
        results = fetch_metadata_batch(["10.9/ext1"])
        assert results == []


class TestSnowballPersistence:
    """The snowballed papers must land in the aggregated file itself."""

    def test_previous_depths_are_kept(self):
        corpus = pd.DataFrame(
            {"DOI": ["10.1/a", "10.1/b"], "title": ["A", "B"], "snowball_depth": [0, 1]}
        )
        new = pd.DataFrame({"DOI": ["10.1/c"], "title": ["C"]})
        merged = merge_with_corpus(corpus, new)
        assert merged["snowball_depth"].tolist() == [0, 1, 2]

    def test_save_overwrites_aggregated_file_and_backs_up_once(self, tmp_path):
        from scilex.io_utils import AGGREGATED_CSV_SEP
        from scilex.snowball.merge import save_merged_corpus

        aggregated = tmp_path / "aggregated_results.csv"
        aggregated.write_text("title;DOI\nA;10.1/a\n", encoding="utf-8")
        first = pd.DataFrame({"title": ["A", "B"], "DOI": ["10.1/a", "10.1/b"]})
        backup = save_merged_corpus(first, str(aggregated))

        assert backup == str(tmp_path / "aggregated_results_pre_snowball.csv")
        assert pd.read_csv(backup, sep=AGGREGATED_CSV_SEP)["title"].tolist() == ["A"]
        assert pd.read_csv(aggregated, sep=AGGREGATED_CSV_SEP)["title"].tolist() == [
            "A",
            "B",
        ]

        second = pd.DataFrame({"title": ["A", "B", "C"], "DOI": ["1", "2", "3"]})
        save_merged_corpus(second, str(aggregated))
        assert pd.read_csv(backup, sep=AGGREGATED_CSV_SEP)["title"].tolist() == ["A"]
        assert len(pd.read_csv(aggregated, sep=AGGREGATED_CSV_SEP)) == 3
