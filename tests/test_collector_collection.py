"""Tests for scilex.crawlers.collector_collection module.

Uses __new__ to bypass __init__ (which creates directories and writes YAML).
"""

from scilex.crawlers.collector_collection import CollectCollection
from scilex.crawlers.utils import sanitize_secrets


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _make_collection(main_config=None, api_config=None):
    """Build a CollectCollection without triggering filesystem side effects."""
    coll = CollectCollection.__new__(CollectCollection)
    coll.main_config = main_config or {
        "collect_name": "test_collect",
        "keywords": [["machine learning"], []],
        "years": [2024],
        "apis": ["SemanticScholar"],
        "output_dir": "/tmp/test",
        "max_articles_per_query": -1,
    }
    coll.api_config = api_config or {}
    return coll


# -------------------------------------------------------------------------
# TestSanitizeErrorMessage
# -------------------------------------------------------------------------
class TestSanitizeErrorMessage:
    def test_api_key_redacted(self):
        msg = "Error: GET https://api.example.com?apiKey=SECRET123 failed"
        result = sanitize_secrets(msg)
        assert "SECRET123" not in result
        assert "***REDACTED***" in result

    def test_mixed_case_api_key_redacted(self):
        msg = "GET https://api.example.com?apikey=mysecret failed"
        result = sanitize_secrets(msg)
        assert "mysecret" not in result

    def test_key_param_redacted(self):
        msg = "Error at https://api.example.com?key=topsecret"
        result = sanitize_secrets(msg)
        assert "topsecret" not in result

    def test_token_param_redacted(self):
        msg = "Error at https://api.example.com?token=mytoken"
        result = sanitize_secrets(msg)
        assert "mytoken" not in result

    def test_clean_message_unchanged(self):
        msg = "Error: Connection timed out after 30 seconds"
        result = sanitize_secrets(msg)
        assert result == msg


# -------------------------------------------------------------------------
# TestQueryCompositor
# -------------------------------------------------------------------------
class TestQueryCompositor:
    def test_single_keyword_mode_wraps_in_list(self):
        coll = _make_collection(
            main_config={
                "keywords": [["machine learning"], []],
                "years": [2024],
                "apis": ["SemanticScholar"],
                "max_articles_per_query": -1,
            }
        )
        result = coll.queryCompositor()
        assert "SemanticScholar" in result
        queries = result["SemanticScholar"]
        assert len(queries) == 1
        q = queries[0]
        assert q["keyword"] == ["machine learning"]
        assert q["year"] == 2024
        assert "max_articles_per_query" in q

    def test_dual_keyword_cartesian_product(self):
        coll = _make_collection(
            main_config={
                "keywords": [["LLM", "GPT"], ["knowledge graph"]],
                "years": [2024],
                "apis": ["SemanticScholar"],
                "max_articles_per_query": -1,
            }
        )
        result = coll.queryCompositor()
        queries = result["SemanticScholar"]
        # 2 × 1 = 2 combinations
        assert len(queries) == 2

    def test_multiple_apis_each_get_queries(self):
        coll = _make_collection(
            main_config={
                "keywords": [["ml"], []],
                "years": [2024],
                "apis": ["SemanticScholar", "OpenAlex"],
                "max_articles_per_query": -1,
            }
        )
        result = coll.queryCompositor()
        assert "SemanticScholar" in result
        assert "OpenAlex" in result

    def test_semantic_scholar_gets_mode_field(self):
        coll = _make_collection(
            main_config={
                "keywords": [["ml"], []],
                "years": [2024],
                "apis": ["SemanticScholar"],
                "max_articles_per_query": -1,
                "semantic_scholar_mode": "regular",
            }
        )
        result = coll.queryCompositor()
        query = result["SemanticScholar"][0]
        assert "semantic_scholar_mode" in query

    def test_non_semantic_scholar_no_mode_field(self):
        coll = _make_collection(
            main_config={
                "keywords": [["ml"], []],
                "years": [2024],
                "apis": ["OpenAlex"],
                "max_articles_per_query": -1,
            }
        )
        result = coll.queryCompositor()
        query = result["OpenAlex"][0]
        assert "semantic_scholar_mode" not in query

    def test_max_articles_propagated(self):
        coll = _make_collection(
            main_config={
                "keywords": [["ml"], []],
                "years": [2024],
                "apis": ["SemanticScholar"],
                "max_articles_per_query": 500,
            }
        )
        result = coll.queryCompositor()
        query = result["SemanticScholar"][0]
        assert query["max_articles_per_query"] == 500

    def test_year_in_every_query(self):
        coll = _make_collection(
            main_config={
                "keywords": [["ml"], []],
                "years": [2024],
                "apis": ["SemanticScholar"],
                "max_articles_per_query": -1,
            }
        )
        result = coll.queryCompositor()
        for query in result["SemanticScholar"]:
            assert query["year"] == 2024

    def test_all_required_fields_present_in_every_query(self):
        """Every query dict must contain keyword, year and max_articles_per_query."""
        coll = _make_collection(
            main_config={
                "keywords": [["a", "b"], []],
                "years": [2023, 2024],
                "apis": ["SemanticScholar", "OpenAlex"],
                "max_articles_per_query": 200,
            }
        )
        result = coll.queryCompositor()
        for api, queries in result.items():
            for q in queries:
                assert "keyword" in q, f"Missing 'keyword' in {api} query"
                assert "year" in q, f"Missing 'year' in {api} query"
                assert "max_articles_per_query" in q, (
                    f"Missing 'max_articles_per_query' in {api} query"
                )
                assert q["max_articles_per_query"] == 200


# -------------------------------------------------------------------------
# TestQueryIsComplete
# -------------------------------------------------------------------------
class TestQueryIsComplete:
    def test_missing_dir_returns_false(self, tmp_path):
        coll = _make_collection()
        result = coll._query_is_complete(str(tmp_path), "SemanticScholar", 0)
        assert result is False

    def test_empty_dir_returns_false(self, tmp_path):
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        coll = _make_collection()
        result = coll._query_is_complete(str(tmp_path), "SemanticScholar", 0)
        assert result is False

    def test_dir_with_pages_and_state_but_no_sentinel_returns_false(self, tmp_path):
        # Partial/failed run: runCollect wrote _state, never _complete → resume
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        (query_dir / "page_1").write_text("{}")
        (query_dir / "_state").write_text("incomplete")
        coll = _make_collection()
        result = coll._query_is_complete(str(tmp_path), "SemanticScholar", 0)
        assert result is False

    def test_legacy_dir_with_pages_and_no_marker_is_complete(self, tmp_path):
        # Collections from older versions have neither marker: keep them
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        (query_dir / "page_1").write_text("{}")
        coll = _make_collection()
        result = coll._query_is_complete(str(tmp_path), "SemanticScholar", 0)
        assert result is True

    def test_dir_with_sentinel_returns_true(self, tmp_path):
        # Complete collection: has _complete sentinel
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        (query_dir / "page_1").write_text("{}")
        (query_dir / "_complete").write_text("1")
        coll = _make_collection()
        result = coll._query_is_complete(str(tmp_path), "SemanticScholar", 0)
        assert result is True


class TestGetLastCollectedPage:
    def test_missing_dir_returns_zero(self, tmp_path):
        coll = _make_collection()
        assert coll._get_last_collected_page(str(tmp_path), "SemanticScholar", 0) == 0

    def test_empty_dir_returns_zero(self, tmp_path):
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        coll = _make_collection()
        assert coll._get_last_collected_page(str(tmp_path), "SemanticScholar", 0) == 0

    def test_returns_highest_page_number(self, tmp_path):
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        for p in [1, 2, 3]:
            (query_dir / f"page_{p}").write_text("{}")
        coll = _make_collection()
        assert coll._get_last_collected_page(str(tmp_path), "SemanticScholar", 0) == 3

    def test_ignores_non_page_files(self, tmp_path):
        query_dir = tmp_path / "SemanticScholar" / "0"
        query_dir.mkdir(parents=True)
        (query_dir / "page_2").write_text("{}")
        (query_dir / "_complete").write_text("1")
        (query_dir / "readme.txt").write_text("x")
        coll = _make_collection()
        assert coll._get_last_collected_page(str(tmp_path), "SemanticScholar", 0) == 2


# -------------------------------------------------------------------------
# TestValidateApiKeys
# -------------------------------------------------------------------------
class TestValidateApiKeys:
    def test_ieee_without_key_returns_false(self):
        coll = _make_collection(
            main_config={"apis": ["IEEE"]},
            api_config={"IEEE": {}},  # No api_key
        )
        assert coll.validate_api_keys() is False

    def test_ieee_with_key_returns_true(self):
        coll = _make_collection(
            main_config={"apis": ["IEEE"]},
            api_config={"IEEE": {"api_key": "my-ieee-key"}},
        )
        assert coll.validate_api_keys() is True

    def test_semantic_scholar_no_key_needed(self):
        coll = _make_collection(
            main_config={"apis": ["SemanticScholar"]},
            api_config={},
        )
        assert coll.validate_api_keys() is True

    def test_springer_without_key_returns_false(self):
        coll = _make_collection(
            main_config={"apis": ["Springer"]},
            api_config={"Springer": {}},
        )
        assert coll.validate_api_keys() is False

    def test_multiple_apis_one_missing_key_returns_false(self):
        coll = _make_collection(
            main_config={"apis": ["SemanticScholar", "IEEE"]},
            api_config={"IEEE": {}},  # Missing IEEE key
        )
        assert coll.validate_api_keys() is False
