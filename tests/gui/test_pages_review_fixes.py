"""Regression tests for the GUI page issues found on 2026-10-25."""

import asyncio

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.components import dialogs
from scilex.gui.pages import home
from scilex.gui.pages.configure import _review_changed
from scilex.gui.services import config_editor

pytestmark = pytest.mark.anyio


def _dialogs(user) -> list:
    return [e for e in user.client.elements.values() if isinstance(e, ui.dialog)]


async def test_closed_dialog_is_deleted(ctx, monkeypatch):
    monkeypatch.setattr(dialogs, "DELETE_DELAY_SECONDS", 0.05)
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        user.find(marker="new-review").click()
        (dialog,) = _dialogs(user)
        dialog.close()
        # Still there while the click handler finishes (it may navigate next).
        assert _dialogs(user) == [dialog]
        await asyncio.sleep(0.2)
        assert _dialogs(user) == []


async def test_home_card_follows_new_results(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(home, "CARDS_POLL_SECONDS", 0.1)
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        await user.should_see("Not collected yet")
        review.collection_dir.mkdir(parents=True)
        review.results_path.write_text("title\nA\n")
        await user.should_see("Results available", retries=30)


async def test_analysis_tabs_are_drawn_when_opened(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title\nA\n")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        await user.should_see(marker="analysis-run-report")
        await user.should_not_see(marker="analysis-run-graph")
        user.find(marker="analysis-tab-graph").click()
        await user.should_see(marker="analysis-run-graph")


def test_renaming_the_review_is_detected(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    assert not _review_changed(ctx, review)
    data = config_editor.load_editable(review)
    data["name"] = "renamed"
    config_editor.save(review, data)
    assert _review_changed(ctx, review)
