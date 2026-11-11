"""Regression tests for Zotero client robustness (per-item failures, tokens, paging)."""

from unittest.mock import MagicMock, patch

import pandas as pd

from scilex.Zotero.zotero_api import ZoteroAPI, prepare_zotero_item


def _api():
    return ZoteroAPI(user_id="1", user_role="user", api_key="k")


def _response(body=None, status=200, headers=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.headers = headers or {}
    return response


def test_per_item_failures_are_not_counted_as_success():
    api = _api()
    body = {
        "successful": {"0": {"key": "A"}},
        "unchanged": {"1": "B"},
        "failed": {"2": {"code": 400, "message": "bad item"}},
    }
    api._post = MagicMock(return_value=_response(body))
    result = api.post_items_bulk([{"title": str(i)} for i in range(3)])
    assert result == {"success": 2, "failed": 1}


def test_same_write_token_reused_when_batch_is_resent():
    api = _api()
    api._post = MagicMock(side_effect=[None, _response({"successful": {"0": {}}})])
    api.post_items_bulk([{"title": "a"}])
    tokens = [call.kwargs.get("write_token") for call in api._post.call_args_list]
    assert len(tokens) == 2
    assert tokens[0] and tokens[0] == tokens[1]
    assert len(tokens[0]) == 32 and tokens[0].isalpha()


def test_post_retries_429_with_same_token():
    api = _api()
    limited = _response(status=429, headers={"Retry-After": "0"})
    ok = _response({"successful": {}})
    with (
        patch(
            "scilex.Zotero.zotero_api.requests.post", side_effect=[limited, ok]
        ) as post,
        patch("scilex.Zotero.zotero_api.time.sleep"),
    ):
        assert api._post("/items", [{}]) is ok
    sent_tokens = {
        c.kwargs["headers"]["Zotero-Write-Token"] for c in post.call_args_list
    }
    assert len(sent_tokens) == 1


def test_get_collections_follows_pagination():
    api = _api()
    pages = [
        _response([{"n": i} for i in range(2)], headers={"Total-Results": "3"}),
        _response([{"n": 2}], headers={"Total-Results": "3"}),
    ]
    api._get = MagicMock(side_effect=pages)
    assert len(api.get_collections(limit=2)) == 3
    assert api._get.call_args_list[1].kwargs["params"]["start"] == 2


def test_create_collection_uses_key_from_response():
    api = _api()
    body = {"successful": {"0": {"key": "NEWKEY", "data": {"key": "NEWKEY"}}}}
    api._post = MagicMock(return_value=_response(body))
    api.find_collection_by_name = MagicMock()
    created = api.create_collection("c")
    assert created["data"]["key"] == "NEWKEY"
    api.find_collection_by_name.assert_not_called()


def test_prepare_item_fetches_template_without_zotero_client():
    template = {"itemType": "journalArticle", "title": "", "url": "", "DOI": ""}
    row = pd.Series({"itemType": "journalArticle", "title": "T", "DOI": "10.1/x"})
    with patch(
        "scilex.Zotero.zotero_api.requests.get",
        return_value=_response(template),
    ):
        item = prepare_zotero_item(row, "COLL", {})
    assert item is not None
    assert item["url"] == "https://doi.org/10.1/x"
