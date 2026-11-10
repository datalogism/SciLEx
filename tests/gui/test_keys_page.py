"""Page test of the API keys screen."""

import pytest
import yaml
from nicegui.testing import user_simulation

from scilex.gui.app import build_root

pytestmark = pytest.mark.anyio


async def test_type_key_and_save(ctx, tmp_path, isolated_scilex_env):
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/keys")
        await user.should_see("the default of every review")
        user.find(marker="key-IEEE").type("abc123")
        user.find(marker="keys-save").click()
        await user.should_see("Keys saved", retries=20)
    saved = yaml.safe_load(isolated_scilex_env.read_text())
    assert saved["IEEE"]["api_key"] == "abc123"


async def test_review_keys_override_global_ones(ctx, tmp_path, isolated_scilex_env):
    from scilex.gui.services import keys_editor
    from scilex.gui.services.workspace import Workspace

    isolated_scilex_env.write_text(
        "IEEE:\n  api_key: global-ieee\nZotero:\n  api_key: zkey\n  user_id: '1'\n"
        "  user_mode: user\n"
    )
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/keys")
        await user.should_see("This review uses the global keys")
        user.find(marker="zotero-user-id").type("999")
        user.find(marker="keys-save").click()
        await user.should_see("Keys saved", retries=20)

    # The global file is untouched; the review stores only what differs.
    assert yaml.safe_load(isolated_scilex_env.read_text())["Zotero"]["user_id"] == "1"
    own = yaml.safe_load(keys_editor.review_keys_path(review.folder).read_text())
    assert own == {"Zotero": {"user_id": "999"}}
    effective = keys_editor.effective_keys(review.folder)
    assert effective["Zotero"] == {
        "api_key": "zkey",
        "user_id": "999",
        "user_mode": "user",
    }
    assert effective["IEEE"]["api_key"] == "global-ieee"
    config = Workspace.load_config(review)
    assert config.api["Zotero"]["user_id"] == "999"
    assert config.api["IEEE"]["api_key"] == "global-ieee"

    # Emptying every field brings the review back to the global keys only.
    assert keys_editor.save_review_keys(review.folder, {"Zotero": {}}) is None
    assert not keys_editor.review_keys_path(review.folder).exists()


async def test_legacy_keys_are_offered_and_imported(
    ctx, tmp_path, isolated_scilex_env, monkeypatch
):
    from scilex.gui.services import keys_editor

    legacy = tmp_path / "api.config.yml"
    legacy.write_text(
        "Zotero:\n  api_key: old\n  user_id: '7'\n  user_mode: group\n"
        "IEEE:\n  api_key: legacy-ieee\nvpn:\n  enabled: true\n"
    )
    isolated_scilex_env.write_text("IEEE:\n  api_key: kept\n")
    monkeypatch.setattr(keys_editor, "legacy_keys_path", lambda: legacy)
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        await user.should_see(marker="home-keys-banner")
        await user.open("/keys")
        await user.should_see(marker="keys-legacy-import")
        user.find(marker="keys-legacy-import-button").click()
        await user.should_see("Keys imported", retries=20)
    saved = yaml.safe_load(isolated_scilex_env.read_text())
    assert saved["IEEE"]["api_key"] == "kept"  # existing values win
    assert saved["Zotero"] == {"api_key": "old", "user_id": "7", "user_mode": "group"}
    assert "vpn" not in saved


async def test_zotero_mode_points_to_missing_keys(ctx):
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        user.find(marker="new-review").click()
        user.find(marker="new-review-start").elements.pop().value = "zotero"
        await user.should_see(marker="zotero-missing")
        await user.should_see(marker="zotero-go-keys")


async def test_unreadable_file_disables_save(ctx, tmp_path, isolated_scilex_env):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    isolated_scilex_env.write_text("IEEE: [unclosed\n  other: x: y\n")
    before = isolated_scilex_env.read_text()
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/keys")
        await user.should_see("could not be read")
        user.find(marker="key-IEEE").type("abc")
        user.find(marker="keys-save").click()
    assert isolated_scilex_env.read_text() == before
