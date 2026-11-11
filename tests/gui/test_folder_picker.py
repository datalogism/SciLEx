"""Tests of the in-page folder picker used when there is no native dialog."""

import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.components.folder_picker import _start_folder, list_subfolders

pytestmark = pytest.mark.anyio


def test_list_subfolders_hides_files_and_dot_folders(tmp_path):
    for name in ("b", "A", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("x")
    assert [path.name for path in list_subfolders(tmp_path)] == ["A", "b"]


def test_list_subfolders_of_missing_folder_is_empty(tmp_path):
    assert list_subfolders(tmp_path / "missing") == []


def test_start_folder_is_closest_existing_parent(tmp_path):
    assert _start_folder(str(tmp_path / "not" / "yet")) == tmp_path
    assert _start_folder(None).is_dir()


async def test_browse_fills_folder_in_browser_mode(ctx, tmp_path):
    (tmp_path / "reviews").mkdir()
    async with user_simulation(root=build_root(ctx)) as user:
        await user.open("/")
        user.find(marker="new-review").click()
        user.find(marker="folder").type(str(tmp_path))
        user.find(marker="browse").click()
        await user.should_see(marker="picker-reviews")
        user.find(marker="picker-reviews").click()
        await user.should_see(str(tmp_path / "reviews"))
        user.find(marker="picker-select").click()
        await user.should_not_see(marker="picker-select")
        folder_input = user.find(marker="folder").elements.pop()
        assert folder_input.value == str(tmp_path / "reviews")
