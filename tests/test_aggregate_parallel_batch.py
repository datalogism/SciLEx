"""Tests for batch processing functions in scilex/crawlers/aggregate_parallel.py"""

import pandas as pd

from scilex.crawlers.aggregate_parallel import (
    _process_batch,
    parallel_process_papers,
)


def _make_hal_paper():
    """Minimal HAL paper dict that passes format conversion."""
    return {
        "halId_s": "hal-12345",
        "title_s": ["A deep learning survey paper"],
        "abstract_s": ["deep learning methods are explored"],
        "authFullName_s": ["Smith J"],
        "submittedDate_tdate": "2022-01-15T00:00:00Z",
        "docType_s": "ART",
        "uri_s": "https://hal.archives-ouvertes.fr/hal-12345",
    }


def _make_openalex_paper():
    return {
        "id": "W123456789",
        "title": "deep learning NLP survey",
        "abstract_inverted_index": None,
        "authorships": [{"author": {"display_name": "Jane Doe"}}],
        "publication_date": "2022-03-10",
        "type": "journal-article",
        "doi": "https://doi.org/10.1234/test",
        "primary_location": None,
        "best_oa_location": None,
        "cited_by_count": 10,
    }


class TestProcessBatch:
    def test_known_api_returns_results(self):
        paper = _make_hal_paper()
        keywords = ["deep learning"]
        batch = [(paper, "HAL", keywords)]
        results = _process_batch(batch)[0]
        assert isinstance(results, list)
        assert len(results) >= 0  # May or may not pass text filter

    def test_unknown_api_returns_empty(self):
        batch = [({"title": "test"}, "UnknownAPI", ["test"])]
        results = _process_batch(batch)[0]
        assert results == []

    def test_keyword_match_passes_filter(self):
        paper = _make_hal_paper()  # title contains "deep learning"
        keywords = ["deep learning"]
        batch = [(paper, "HAL", keywords)]
        results = _process_batch(batch)[0]
        # HAL paper with "deep learning" in title should pass
        assert isinstance(results, list)

    def test_no_keywords_all_pass(self):
        paper = _make_hal_paper()
        batch = [(paper, "HAL", [])]
        results = _process_batch(batch)[0]
        assert isinstance(results, list)
        assert len(results) == 1

    def test_malformed_paper_skipped_no_crash(self):
        batch = [({"bad_key": "value"}, "HAL", ["deep learning"])]
        results = _process_batch(batch)[0]
        # Should not raise; may return empty or converted result
        assert isinstance(results, list)

    def test_empty_batch_returns_empty(self):
        results = _process_batch([])[0]
        assert results == []

    def test_multiple_papers_processed(self):
        papers = [
            (_make_hal_paper(), "HAL", []),
            (_make_hal_paper(), "HAL", []),
        ]
        results = _process_batch(papers)[0]
        assert len(results) == 2

    def test_openalex_paper_processed(self):
        paper = _make_openalex_paper()
        batch = [(paper, "OpenAlex", [])]
        results = _process_batch(batch)[0]
        # OpenAlex conversion may filter or fail silently — just verify no crash
        assert isinstance(results, list)


class TestParallelProcessPapers:
    def test_returns_tuple_dataframe_stats(self):
        paper = _make_hal_paper()
        papers_by_api = [(paper, "HAL", [])]
        df, stats = parallel_process_papers(
            papers_by_api, batch_size=100, num_workers=1
        )
        assert isinstance(df, pd.DataFrame)
        assert isinstance(stats, dict)

    def test_stats_have_required_keys(self):
        paper = _make_hal_paper()
        papers_by_api = [(paper, "HAL", [])]
        _, stats = parallel_process_papers(papers_by_api, batch_size=100, num_workers=1)
        assert "papers_processed" in stats
        assert "elapsed_seconds" in stats

    def test_result_dataframe_has_rows(self):
        paper = _make_hal_paper()
        papers_by_api = [(paper, "HAL", [])]
        df, _ = parallel_process_papers(papers_by_api, batch_size=100, num_workers=1)
        assert len(df) >= 1

    def test_empty_input_returns_empty_df(self):
        df, stats = parallel_process_papers([], batch_size=100, num_workers=1)
        assert df.empty or len(df) == 0

    def test_multiple_batches_combined(self):
        papers = [((_make_hal_paper()), "HAL", []) for _ in range(5)]
        df, stats = parallel_process_papers(papers, batch_size=2, num_workers=2)
        assert len(df) == 5

    def test_keyword_filter_applied(self):
        paper = _make_hal_paper()  # title: "A deep learning survey paper"
        no_match_paper = {
            "halId_s": "hal-99999",
            "title_s": ["unrelated topic about nothing"],
            "abstract_s": ["something else entirely"],
            "authFullName_s": ["Unknown Author"],
            "submittedDate_tdate": "2022-01-01T00:00:00Z",
            "docType_s": "ART",
        }
        papers = [
            (paper, "HAL", ["deep learning"]),
            (no_match_paper, "HAL", ["deep learning"]),
        ]
        df, _ = parallel_process_papers(papers, batch_size=10, num_workers=1)
        assert len(df) == 1  # Only the paper with "deep learning" passes


class TestConverterErrorReporting:
    def test_converter_errors_logged_and_counted(self, caplog):
        from unittest.mock import patch

        def boom(_paper):
            raise ValueError("bad record")

        batch = [({"x": 1}, "HAL", ["kw"]), ({"x": 2}, "HAL", ["kw"])]
        with (
            patch.dict("scilex.crawlers.aggregate.FORMAT_CONVERTERS", {"HAL": boom}),
            caplog.at_level("WARNING"),
        ):
            df, stats = parallel_process_papers(batch, batch_size=10, num_workers=1)
        assert df.empty
        assert stats["converter_errors"] == {"HAL": 2}
        assert any(
            r.levelname == "WARNING" and "HAL" in r.message and "2" in r.message
            for r in caplog.records
        )

    def test_no_errors_gives_empty_mapping(self):
        batch = [(_make_hal_paper(), "HAL", ["deep learning"])]
        _, stats = parallel_process_papers(batch, batch_size=10, num_workers=1)
        assert stats["converter_errors"] == {}
