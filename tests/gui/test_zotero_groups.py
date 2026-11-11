"""Global Zotero key, dedicated group per review, group page."""

from unittest.mock import patch

import pytest
import yaml
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import keys_editor, members
from scilex.gui.services import zotero_library as zl

KEY_ANSWER = {
    "key": "SECRET",
    "userID": 12,
    "username": "ada",
    "access": {
        "user": {"library": True, "write": True},
        "groups": {"42": {"library": True, "write": True}, "7": {"library": False}},
    },
}
GROUP_ANSWER = {
    "id": 42,
    "meta": {"numItems": 31, "created": "2025-01-02T10:00:00Z"},
    "data": {
        "id": 42,
        "name": "RAG review",
        "type": "Private",
        "description": "<p>Shared <b>review</b></p>",
        "owner": 12,
        "admins": [13],
        "members": [14, 15],
        "libraryReading": "members",
        "libraryEditing": "members",
        "fileEditing": "admins",
    },
}


class _Response:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _no_cache():
    zl._KEY_INFO_CACHE.clear()
    yield
    zl._KEY_INFO_CACHE.clear()


def test_key_info_reads_owner_and_rights_and_drops_the_key():
    with patch("requests.get", return_value=_Response(200, KEY_ANSWER)) as get:
        info = zl.key_info("SECRET")
    assert get.call_args.kwargs["headers"]["Zotero-API-Key"] == "SECRET"
    assert (info.user_id, info.username) == ("12", "ada")
    assert info.group_access("42") == "write" and info.group_access("7") == ""
    assert "SECRET" not in repr(info) and "SECRET" not in info.describe()


def test_refused_key_is_not_configured():
    with (
        patch("requests.get", return_value=_Response(403)),
        pytest.raises(zl.ZoteroNotConfiguredError),
    ):
        zl.key_info("bad")
    ok, message, info = keys_editor.check_zotero_key("")
    assert not ok and info is None and "Enter" in message


def test_global_key_alone_gives_the_owner_library():
    with patch("requests.get", return_value=_Response(200, KEY_ANSWER)):
        assert zl.zotero_credentials({"Zotero": {"api_key": "k"}}) == (
            "k",
            "12",
            "user",
        )


class _Api:
    def __init__(self, groups):
        self.groups = groups

    def get_groups(self):
        return self.groups


def test_list_libraries_keeps_groups_the_key_reaches(monkeypatch):
    monkeypatch.setattr(
        zl, "key_info", lambda key, refresh=False: zl.parse_key_info(KEY_ANSWER)
    )
    groups = [
        {"id": 42, "data": {"name": "RAG review"}},
        {"id": 7, "data": {"name": "Not for this key"}},
    ]
    monkeypatch.setattr(zl, "client", lambda keys=None, library=None: _Api(groups))
    keys = {"Zotero": {"api_key": "k"}}
    found = zl.list_libraries(keys)
    assert [(lib.library_type, lib.library_id) for lib in found] == [
        ("user", "12"),
        ("group", "42"),
    ]
    assert [lib.library_id for lib in zl.list_libraries(keys, groups_only=True)] == [
        "42"
    ]


def test_group_details_and_roster():
    group = zl.parse_group(GROUP_ANSWER)
    assert group.description == "Shared review"
    assert group.people == 4 and group.role_of("13") == "admin"
    assert group.web_url.endswith("/groups/42")
    saved = [
        members.Member(
            name="Ada", username="ada", zotero_id="12", orcid="0000-0002-1825-0097"
        ),
        members.Member(name="Guest", role="manual"),
    ]
    roster = members.group_roster(group, saved)
    assert [(r.label, r.role, r.in_group) for r in roster] == [
        ("Ada", "owner", True),
        ("Zotero user 13", "admin", True),
        ("Zotero user 14", "member", True),
        ("Zotero user 15", "member", True),
        ("Guest", "manual", False),
    ]


def test_group_details_refuses_a_personal_library():
    with pytest.raises(ValueError):
        zl.group_details(zl.ZoteroSource("1", "user", None, ""))


@pytest.mark.anyio
async def test_global_page_detects_the_key_owner(ctx, isolated_scilex_env, monkeypatch):
    monkeypatch.setattr(
        zl, "key_info", lambda key, refresh=False: zl.parse_key_info(KEY_ANSWER)
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/keys")
        user.find(marker="key-Zotero").type("global-key")
        user.find(marker="key-test-Zotero").click()
        await user.should_see("Key of ada (user 12)", retries=20)
        user.find(marker="keys-save").click()
        await user.should_see("Keys saved", retries=20)
    saved = yaml.safe_load(isolated_scilex_env.read_text())
    assert saved["Zotero"] == {
        "api_key": "global-key",
        "user_id": "12",
        "user_mode": "user",
    }


@pytest.mark.anyio
async def test_group_page_shows_details_and_members(
    ctx, tmp_path, isolated_scilex_env, monkeypatch
):
    isolated_scilex_env.write_text("Zotero:\n  api_key: k\n")
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/group")
        await user.should_see(marker="group-problem")  # no group yet

    zl.save_source(
        review.folder,
        zl.ZoteroSource("42", "group", None, "", library_name="Group: RAG review"),
    )
    monkeypatch.setattr(
        zl, "group_details", lambda source, keys=None: zl.parse_group(GROUP_ANSWER)
    )
    monkeypatch.setattr(
        zl, "key_info", lambda key, refresh=False: zl.parse_key_info(KEY_ANSWER)
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/group")
        await user.should_see(marker="group-details", retries=20)
        await user.should_see("RAG review")
        await user.should_see("read and write")
        await user.should_see(marker="group-members-table")
        await user.should_not_see(marker="group-problem")
