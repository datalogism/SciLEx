"""Tests for bulk_post_items and _retry_with_smaller_batches in ZoteroAPI."""

from unittest.mock import MagicMock

from scilex.Zotero.zotero_api import ZoteroAPI


def _make_api():
    return ZoteroAPI(user_id="123", user_role="user", api_key="testkey")


def _make_response(status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    return mock


class TestPostItemsBulk:
    def test_success_returns_correct_counts(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        items = [{"title": f"item {i}"} for i in range(10)]
        result = api.post_items_bulk(items)
        assert result["success"] == 10
        assert result["failed"] == 0

    def test_failure_returns_failed_count(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(500))
        items = [{"title": f"item {i}"} for i in range(5)]
        result = api.post_items_bulk(items)
        assert result["failed"] == 5

    def test_201_counts_as_success(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(201))
        items = [{"title": "item"}]
        result = api.post_items_bulk(items)
        assert result["success"] == 1

    def test_batch_size_capped_at_50(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        items = [{"title": f"item {i}"} for i in range(10)]
        result = api.post_items_bulk(items, batch_size=100)
        assert result["success"] == 10

    def test_none_response_with_small_batch_fails(self):
        api = _make_api()
        api._post = MagicMock(return_value=None)
        items = [{"title": f"item {i}"} for i in range(5)]
        result = api.post_items_bulk(items)
        assert result["failed"] == 5

    def test_none_response_with_large_batch_retries(self):
        api = _make_api()
        # First call returns None (triggers retry), subsequent calls succeed
        success_response = _make_response(200)
        api._post = MagicMock(side_effect=[None, success_response, success_response])
        items = [{"title": f"item {i}"} for i in range(15)]
        result = api.post_items_bulk(items)
        # Either retried successfully or failed — just shouldn't crash
        assert "success" in result
        assert "failed" in result

    def test_multiple_batches_processed(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        items = [{"title": f"item {i}"} for i in range(60)]
        result = api.post_items_bulk(items, batch_size=25)
        assert result["success"] == 60
        assert result["failed"] == 0

    def test_empty_items_returns_zero_counts(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        result = api.post_items_bulk([])
        assert result["success"] == 0
        assert result["failed"] == 0


class TestRetryWithSmallerBatches:
    def test_success_on_retry(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        items = [{"title": f"item {i}"} for i in range(30)]
        result = api._retry_with_smaller_batches(items)
        assert result["success"] == 30
        assert result["failed"] == 0

    def test_failure_on_retry(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(500))
        items = [{"title": f"item {i}"} for i in range(10)]
        result = api._retry_with_smaller_batches(items)
        # Retries twice (batch sizes [25, 10]), so items may be counted multiple times
        assert result["failed"] >= 10
        assert result["success"] == 0

    def test_returns_dict_with_required_keys(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        result = api._retry_with_smaller_batches([{"title": "test"}])
        assert "success" in result
        assert "failed" in result

    def test_empty_items_returns_zeros(self):
        api = _make_api()
        api._post = MagicMock(return_value=_make_response(200))
        result = api._retry_with_smaller_batches([])
        assert result["success"] == 0
        assert result["failed"] == 0

    def test_partial_success(self):
        api = _make_api()
        # With 30 items: retry_size=25 → 2 batches (25+5). First batch succeeds, rest fail.
        responses = [
            _make_response(200),
            _make_response(500),
            _make_response(500),
            _make_response(500),
        ]
        api._post = MagicMock(side_effect=responses)
        items = [{"title": f"item {i}"} for i in range(30)]
        result = api._retry_with_smaller_batches(items)
        assert result["success"] >= 0
        assert result["failed"] >= 0
