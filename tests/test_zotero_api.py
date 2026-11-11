"""Tests for scilex.Zotero.zotero_api module.

All HTTP calls are mocked via patch('scilex.Zotero.zotero_api.requests').
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.Zotero.zotero_api import ZoteroAPI


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _make_api(user_id="12345", role="user", api_key="test-api-key"):
    return ZoteroAPI(user_id=user_id, user_role=role, api_key=api_key)


# -------------------------------------------------------------------------
# TestZoteroAPIInit
# -------------------------------------------------------------------------
class TestZoteroAPIInit:
    def test_user_role_sets_user_endpoint(self):
        api = _make_api(user_id="100", role="user")
        assert api.base_endpoint == "/users/100"

    def test_group_role_sets_group_endpoint(self):
        api = _make_api(user_id="999", role="group")
        assert api.base_endpoint == "/groups/999"

    def test_invalid_role_raises_value_error(self):
        with pytest.raises(ValueError):
            ZoteroAPI("123", "admin", "key")

    def test_api_key_in_headers(self):
        api = _make_api(api_key="my-secret-key")
        assert api.headers["Zotero-API-Key"] == "my-secret-key"

    def test_user_id_stored(self):
        api = _make_api(user_id="42")
        assert api.user_id == "42"


# -------------------------------------------------------------------------
# TestGetWriteToken
# -------------------------------------------------------------------------
class TestGetWriteToken:
    def test_token_length_32(self):
        api = _make_api()
        token = api._get_write_token()
        assert len(token) == 32

    def test_token_is_alphanumeric(self):
        api = _make_api()
        token = api._get_write_token()
        assert token.isalnum()
        assert any(c.isalpha() for c in token)

    def test_two_tokens_differ(self):
        api = _make_api()
        t1 = api._get_write_token()
        t2 = api._get_write_token()
        # Extremely unlikely to be identical for 32 char tokens
        assert t1 != t2


# -------------------------------------------------------------------------
# TestZoteroGet
# -------------------------------------------------------------------------
class TestZoteroGet:
    def test_successful_get_returns_response(self):
        api = _make_api()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        with patch("scilex.Zotero.zotero_api.requests.get", return_value=mock_response):
            result = api._get("/collections")
        assert result is mock_response

    def test_timeout_returns_none(self):
        api = _make_api()
        with patch(
            "scilex.Zotero.zotero_api.requests.get",
            side_effect=requests.exceptions.Timeout,
        ):
            result = api._get("/collections")
        assert result is None

    def test_http_error_returns_none(self):
        api = _make_api()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        with patch("scilex.Zotero.zotero_api.requests.get", return_value=mock_response):
            result = api._get("/collections")
        assert result is None

    def test_url_constructed_correctly(self):
        api = _make_api(user_id="123", role="user")
        calls = []
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        def capture_call(url, **kwargs):
            calls.append(url)
            return mock_response

        with patch("scilex.Zotero.zotero_api.requests.get", side_effect=capture_call):
            api._get("/collections")

        assert calls[0] == "https://api.zotero.org/users/123/collections"


# -------------------------------------------------------------------------
# TestGetCollections
# -------------------------------------------------------------------------
class TestGetCollections:
    def test_returns_list_on_success(self):
        api = _make_api()
        collections_data = [{"key": "A1", "data": {"name": "My Collection"}}]
        mock_response = MagicMock()
        mock_response.json.return_value = collections_data
        with patch.object(api, "_get", return_value=mock_response):
            result = api.get_collections()
        assert result == collections_data

    def test_returns_none_on_get_failure(self):
        api = _make_api()
        with patch.object(api, "_get", return_value=None):
            result = api.get_collections()
        assert result is None


# -------------------------------------------------------------------------
# TestFindCollectionByName
# -------------------------------------------------------------------------
class TestFindCollectionByName:
    def test_finds_existing_collection(self):
        api = _make_api()
        collections = [
            {"key": "A1", "data": {"name": "My Collection"}},
            {"key": "B2", "data": {"name": "Other Collection"}},
        ]
        with patch.object(api, "get_collections", return_value=collections):
            result = api.find_collection_by_name("My Collection")
        assert result is not None
        assert result["key"] == "A1"

    def test_returns_none_when_not_found(self):
        api = _make_api()
        collections = [{"key": "A1", "data": {"name": "My Collection"}}]
        with patch.object(api, "get_collections", return_value=collections):
            result = api.find_collection_by_name("Nonexistent")
        assert result is None

    def test_returns_none_when_collections_none(self):
        api = _make_api()
        with patch.object(api, "get_collections", return_value=None):
            result = api.find_collection_by_name("Any")
        assert result is None


# -------------------------------------------------------------------------
# TestGetOrCreateCollection
# -------------------------------------------------------------------------
class TestGetOrCreateCollection:
    def test_returns_existing_without_creating(self):
        api = _make_api()
        existing = {"key": "A1", "data": {"name": "ExistingCollection"}}
        with (
            patch.object(api, "find_collection_by_name", return_value=existing),
            patch.object(api, "create_collection") as mock_create,
        ):
            result = api.get_or_create_collection("ExistingCollection")
        assert result is existing
        mock_create.assert_not_called()

    def test_creates_when_not_found(self):
        api = _make_api()
        new_collection = {"key": "C3", "data": {"name": "NewCollection"}}
        with (
            patch.object(api, "find_collection_by_name", return_value=None),
            patch.object(api, "create_collection", return_value=new_collection),
        ):
            result = api.get_or_create_collection("NewCollection")
        assert result is new_collection
