"""Additional tests for scilex/crawlers/collector_collection.py — CollectCollection methods."""

from scilex.crawlers.collector_collection import CollectCollection


def _make_collection(main_config=None, api_config=None):
    """Build CollectCollection without triggering __init__ side effects."""
    coll = CollectCollection.__new__(CollectCollection)
    coll.main_config = main_config or {
        "keywords": [["deep learning"], []],
        "years": [2022],
        "apis": ["HAL"],
        "max_articles_per_query": 100,
        "output_dir": "/tmp/test_scilex",
        "collect_name": "test_run",
    }
    coll.api_config = api_config or {}
    return coll


class TestValidateApiKeysMethod:
    def test_no_keys_needed_returns_true(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["HAL", "Arxiv"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {}
        assert coll.validate_api_keys() is True

    def test_ieee_without_key_returns_false(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["IEEE"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {}
        assert coll.validate_api_keys() is False

    def test_ieee_with_key_returns_true(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["IEEE"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {"IEEE": {"api_key": "mykey"}}
        assert coll.validate_api_keys() is True

    def test_springer_without_key_returns_false(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["Springer"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {}
        assert coll.validate_api_keys() is False

    def test_springer_with_key_returns_true(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["Springer"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {"Springer": {"api_key": "springerkey"}}
        assert coll.validate_api_keys() is True

    def test_elsevier_without_key_returns_false(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["Elsevier"],
                "max_articles_per_query": 100,
            }
        )
        coll.api_config = {}
        assert coll.validate_api_keys() is False


class TestQueryIsCompleteMethod:
    def test_missing_dir_returns_false(self, tmp_path):
        coll = _make_collection()
        assert coll._query_is_complete(str(tmp_path), "HAL", 0) is False

    def test_empty_dir_returns_false(self, tmp_path):
        d = tmp_path / "HAL" / "query_1"
        d.mkdir(parents=True)
        coll = _make_collection()
        assert coll._query_is_complete(str(tmp_path), "HAL", 0) is False

    def test_dir_with_pages_but_no_sentinel_returns_false(self, tmp_path):
        # Partial collection: page files exist, _state written, _complete absent
        d = tmp_path / "HAL" / "0"
        d.mkdir(parents=True)
        (d / "page_1").write_text("{}")
        (d / "_state").write_text("incomplete")
        coll = _make_collection()
        assert coll._query_is_complete(str(tmp_path), "HAL", 0) is False

    def test_dir_with_sentinel_returns_true(self, tmp_path):
        d = tmp_path / "HAL" / "0"
        d.mkdir(parents=True)
        (d / "page_1.json").write_text("{}")
        (d / "_complete").write_text("1")
        coll = _make_collection()
        assert coll._query_is_complete(str(tmp_path), "HAL", 0) is True


class TestGetCurrentRepo:
    def test_returns_path_combining_output_and_collect_name(self):
        coll = _make_collection(
            main_config={
                "keywords": [["NLP"], []],
                "years": [2022],
                "apis": ["HAL"],
                "max_articles_per_query": 100,
                "output_dir": "/tmp/out",
                "collect_name": "my_review",
            }
        )
        result = coll.get_current_repo()
        assert "my_review" in result
        assert "/tmp/out" in result
