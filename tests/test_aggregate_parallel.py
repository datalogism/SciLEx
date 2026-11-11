"""Tests for scilex.crawlers.aggregate_parallel module.

Uses tmp_path for filesystem tests; no external HTTP calls.
"""

import json
from pathlib import Path

import pandas as pd

from scilex.crawlers.aggregate_parallel import (
    _load_json_file,
    discover_api_directories,
    reconstruct_query_to_keywords_mapping,
    simple_deduplicate,
)


# -------------------------------------------------------------------------
# TestDiscoverApiDirectories
# -------------------------------------------------------------------------
class TestDiscoverApiDirectories:
    def _make_dir(self, tmp_path: Path, api: str, query_indices: list):
        api_dir = tmp_path / api
        api_dir.mkdir()
        for idx in query_indices:
            (api_dir / str(idx)).mkdir()
        return api_dir

    def test_finds_api_directories(self, tmp_path):
        self._make_dir(tmp_path, "SemanticScholar", [0, 1, 2])
        result = discover_api_directories(str(tmp_path))
        assert "SemanticScholar" in result
        assert result["SemanticScholar"] == ["0", "1", "2"]

    def test_multiple_apis_discovered(self, tmp_path):
        self._make_dir(tmp_path, "SemanticScholar", [0])
        self._make_dir(tmp_path, "OpenAlex", [0, 1])
        result = discover_api_directories(str(tmp_path))
        assert "SemanticScholar" in result
        assert "OpenAlex" in result

    def test_skips_config_yml_file(self, tmp_path):
        self._make_dir(tmp_path, "SemanticScholar", [0])
        (tmp_path / "config_used.yml").touch()
        result = discover_api_directories(str(tmp_path))
        assert "config_used.yml" not in result

    def test_skips_citation_cache_db(self, tmp_path):
        self._make_dir(tmp_path, "SemanticScholar", [0])
        (tmp_path / "citation_cache.db").touch()
        result = discover_api_directories(str(tmp_path))
        assert "citation_cache.db" not in result

    def test_skips_non_numeric_query_dirs(self, tmp_path):
        api_dir = tmp_path / "IEEE"
        api_dir.mkdir()
        (api_dir / "0").mkdir()
        (api_dir / "metadata").mkdir()  # non-numeric, should be skipped
        result = discover_api_directories(str(tmp_path))
        assert result["IEEE"] == ["0"]

    def test_sorts_numerically(self, tmp_path):
        self._make_dir(tmp_path, "HAL", [0, 2, 10, 1])
        result = discover_api_directories(str(tmp_path))
        assert result["HAL"] == ["0", "1", "2", "10"]

    def test_nonexistent_dir_returns_empty(self):
        result = discover_api_directories("/nonexistent/path/that/does/not/exist")
        assert result == {}

    def test_empty_dir_returns_empty(self, tmp_path):
        result = discover_api_directories(str(tmp_path))
        assert result == {}

    def test_api_without_query_dirs_excluded(self, tmp_path):
        api_dir = tmp_path / "EmptyAPI"
        api_dir.mkdir()
        # No subdirectories
        result = discover_api_directories(str(tmp_path))
        assert "EmptyAPI" not in result


# -------------------------------------------------------------------------
# TestReconstructQueryToKeywordsMapping
# -------------------------------------------------------------------------
class TestReconstructQueryToKeywordsMapping:
    def test_single_keyword_mode(self):
        config = {
            "keywords": [["knowledge graph", "machine learning"], []],
            "years": [2024],
            "apis": ["SemanticScholar"],
        }
        result = reconstruct_query_to_keywords_mapping(config)
        assert "SemanticScholar" in result
        assert "0" in result["SemanticScholar"]
        assert result["SemanticScholar"]["0"] == ["knowledge graph"]
        assert result["SemanticScholar"]["1"] == ["machine learning"]

    def test_dual_keyword_cartesian_product(self):
        config = {
            "keywords": [["LLM", "GPT"], ["knowledge graph", "ontology"]],
            "years": [2024],
            "apis": ["SemanticScholar"],
        }
        result = reconstruct_query_to_keywords_mapping(config)
        ss = result["SemanticScholar"]
        # 2 × 2 = 4 combinations
        assert len(ss) == 4
        # Verify cartesian product keywords
        all_combos = list(ss.values())
        assert ["LLM", "knowledge graph"] in all_combos
        assert ["LLM", "ontology"] in all_combos
        assert ["GPT", "knowledge graph"] in all_combos
        assert ["GPT", "ontology"] in all_combos

    def test_multiple_apis_each_get_mapping(self):
        config = {
            "keywords": [["ml"], []],
            "years": [2024],
            "apis": ["SemanticScholar", "OpenAlex"],
        }
        result = reconstruct_query_to_keywords_mapping(config)
        assert "SemanticScholar" in result
        assert "OpenAlex" in result
        assert result["SemanticScholar"]["0"] == ["ml"]
        assert result["OpenAlex"]["0"] == ["ml"]

    def test_multiple_years_creates_more_queries(self):
        config = {
            "keywords": [["ml"], []],
            "years": [2023, 2024],
            "apis": ["SemanticScholar"],
        }
        result = reconstruct_query_to_keywords_mapping(config)
        # 1 keyword × 2 years = 2 queries
        assert len(result["SemanticScholar"]) == 2

    def test_index_order_is_sequential(self):
        config = {
            "keywords": [["a", "b", "c"], []],
            "years": [2024],
            "apis": ["SemanticScholar"],
        }
        result = reconstruct_query_to_keywords_mapping(config)
        assert set(result["SemanticScholar"].keys()) == {"0", "1", "2"}


# -------------------------------------------------------------------------
# TestSimpleDeduplicate
# -------------------------------------------------------------------------
def _make_paper(
    doi="10.1234/test", title="Test Paper", archive="SemanticScholar", **extras
):
    row = {
        "DOI": doi,
        "title": title,
        "archive": archive,
        "abstract": "An abstract.",
        "authors": "Alice Smith",
        "date": "2024",
    }
    row.update(extras)
    return row


class TestSimpleDeduplicate:
    def test_no_duplicates_returns_same_count(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="10.1/a", title="Paper A"),
                _make_paper(doi="10.1/b", title="Paper B"),
                _make_paper(doi="10.1/c", title="Paper C"),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 3
        assert stats["doi_removed"] == 0
        assert stats["title_removed"] == 0

    def test_doi_duplicates_removed(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="10.1/a", title="Paper A", archive="SemanticScholar"),
                _make_paper(doi="10.1/a", title="Paper A (copy)", archive="OpenAlex"),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 1
        assert stats["doi_removed"] == 1

    def test_doi_dedup_keeps_better_quality(self):
        # High quality: has abstract + authors + DOI
        # Low quality: only DOI
        df = pd.DataFrame(
            [
                _make_paper(
                    doi="10.1/a",
                    title="Paper A",
                    archive="OpenAlex",
                    abstract="NA",
                    authors="NA",
                ),
                _make_paper(
                    doi="10.1/a",
                    title="Paper A",
                    archive="SemanticScholar",
                    abstract="Full abstract here.",
                    authors="John Smith",
                ),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 1
        # The one with the better quality should be kept
        assert result.iloc[0]["abstract"] == "Full abstract here."

    def test_doi_dedup_merges_archives(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="10.1/a", title="Paper A", archive="SemanticScholar"),
                _make_paper(doi="10.1/a", title="Paper A copy", archive="OpenAlex"),
            ]
        )
        result, _ = simple_deduplicate(df)
        archive_val = result.iloc[0]["archive"]
        # Both sources must be merged into the kept record
        assert "SemanticScholar" in archive_val and "OpenAlex" in archive_val

    def test_title_duplicates_removed(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="NA", title="Graph Neural Networks"),
                _make_paper(doi="NA", title="Graph Neural Networks"),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 1
        assert stats["title_removed"] == 1

    def test_title_normalization_strips_punctuation(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="NA", title="Graph Neural Networks!"),
                _make_paper(doi="NA", title="Graph Neural Networks"),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 1

    def test_title_normalization_case_insensitive(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="NA", title="Machine Learning"),
                _make_paper(doi="NA", title="machine learning"),
            ]
        )
        result, stats = simple_deduplicate(df)
        assert len(result) == 1

    def test_dedup_quality_column_removed(self):
        df = pd.DataFrame([_make_paper()])
        result, _ = simple_deduplicate(df)
        assert "_dedup_quality" not in result.columns

    def test_title_normalized_column_removed(self):
        df = pd.DataFrame([_make_paper()])
        result, _ = simple_deduplicate(df)
        assert "title_normalized" not in result.columns

    def test_stats_have_required_keys(self):
        df = pd.DataFrame([_make_paper()])
        _, stats = simple_deduplicate(df)
        assert "initial_count" in stats
        assert "final_count" in stats
        assert "doi_removed" in stats
        assert "title_removed" in stats

    def test_missing_doi_not_deduped_by_doi(self):
        df = pd.DataFrame(
            [
                _make_paper(doi="NA", title="Paper A"),
                _make_paper(doi="NA", title="Paper B"),
            ]
        )
        result, stats = simple_deduplicate(df)
        # Both should survive DOI dedup (NA is not a valid DOI)
        assert stats["doi_removed"] == 0


# -------------------------------------------------------------------------
# TestLoadJsonFile
# -------------------------------------------------------------------------
class TestLoadJsonFile:
    def test_valid_json_with_results(self, tmp_path):
        data = {"results": [{"title": "Paper 1"}, {"title": "Paper 2"}]}
        f = tmp_path / "page_0"
        f.write_text(json.dumps(data))
        papers, api, kws, count = _load_json_file(str(f), "SemanticScholar", ["ml"])
        assert len(papers) == 2
        assert api == "SemanticScholar"
        assert kws == ["ml"]
        assert count == 2

    def test_missing_results_key_returns_empty(self, tmp_path):
        data = {"total": 10}  # No "results" key
        f = tmp_path / "page_0"
        f.write_text(json.dumps(data))
        papers, api, kws, count = _load_json_file(str(f), "API", ["kw"])
        assert papers == []
        assert count == 0

    def test_invalid_json_returns_empty(self, tmp_path):
        f = tmp_path / "page_corrupt"
        f.write_text("{not valid json}")
        papers, api, kws, count = _load_json_file(str(f), "API", ["kw"])
        assert papers == []
        assert api == "API"
        assert kws == ["kw"]
        assert count == 0

    def test_empty_results_list(self, tmp_path):
        data = {"results": []}
        f = tmp_path / "page_0"
        f.write_text(json.dumps(data))
        papers, _, _, count = _load_json_file(str(f), "API", ["kw"])
        assert papers == []
        assert count == 0

    def test_file_not_found_returns_empty(self, tmp_path):
        papers, api, kws, count = _load_json_file(
            str(tmp_path / "nonexistent"), "API", ["kw"]
        )
        assert papers == []
        assert count == 0
