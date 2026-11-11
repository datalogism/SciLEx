"""Safety tests: the GUI never uses legacy credentials and confirms Zotero pushes."""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import exports
from scilex.gui.services.workspace import Workspace

pytestmark = pytest.mark.anyio


@pytest.fixture
def review(ctx, tmp_path):
    """Review with two aggregated papers."""
    review = ctx.workspace.create_review(tmp_path / "rev", name="rev")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"itemType": "journalArticle", "title": "A", "DOI": "10.1/a"},
            {"itemType": "journalArticle", "title": "B", "DOI": "10.1/b"},
        ]
    ).to_csv(review.collection_dir / "aggregated_results.csv", sep=";", index=False)
    return review


def _fake_legacy_keys(tmp_path, monkeypatch):
    """Point the legacy api.config.yml lookup to a temp file with fake Zotero keys."""
    legacy = tmp_path / "legacy_api.config.yml"
    legacy.write_text(
        "Zotero:\n  api_key: LEGACYKEY\n  user_id: '999'\n  user_mode: user\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("scilex.settings.loader.LEGACY_KEYS_PATH", legacy)
    monkeypatch.setattr("scilex.settings.loader.USER_KEYS_PATH", tmp_path / "nope.yml")


def test_load_config_ignores_legacy_keys_without_keys_file(
    review, tmp_path, monkeypatch
):
    _fake_legacy_keys(tmp_path, monkeypatch)
    monkeypatch.setenv("SCILEX_KEYS", str(tmp_path / "missing" / "keys.yml"))
    config = Workspace.load_config(review)
    assert not config.api.get("Zotero")
    assert exports.zotero_settings(config) is None


async def test_page_zotero_disabled_with_only_legacy_keys(
    ctx, review, tmp_path, monkeypatch
):
    _fake_legacy_keys(tmp_path, monkeypatch)
    monkeypatch.setenv("SCILEX_KEYS", str(tmp_path / "missing.yml"))
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/export")
        button = user.find(marker="export-zotero").elements.pop()
        assert not button.enabled


async def test_page_zotero_push_requires_confirmation(
    ctx, review, tmp_path, monkeypatch
):
    keys = tmp_path / "real_keys.yml"
    keys.write_text(
        "Zotero:\n  api_key: FAKE\n  user_id: '42'\n  user_mode: group\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCILEX_KEYS", str(keys))
    pushed = MagicMock(return_value={"success": 1, "failed": 0, "skipped": 0})
    monkeypatch.setattr("scilex.gui.services.exports.push_to_zotero", pushed)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/export")
        user.find(marker="export-zotero").click()
        await user.should_see(marker="zotero-confirm")
        await user.should_see('Push 2 papers to Zotero: group library 42 (collection "')
        pushed.assert_not_called()
        user.find(marker="zotero-push").click()
        await user.should_see(marker="export-result", retries=50)
        pushed.assert_called_once()
