"""Tests for the review registry of the desktop GUI."""

from pathlib import Path

import pytest

from scilex.gui.services.workspace import Workspace, read_review
from scilex.settings.schema import SettingsError


@pytest.fixture
def workspace(tmp_path):
    """Workspace backed by a temporary registry."""
    return Workspace(registry_path=tmp_path / "registry" / "gui_reviews.yml")


def test_create_then_list(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")

    assert review.name == "rag_kg"
    assert review.config_path.is_file()
    assert not review.has_results
    assert [r.folder for r in workspace.list_reviews()] == [review.folder]


def test_registry_persists_between_instances(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")

    reopened = Workspace(registry_path=workspace.registry_path)

    assert reopened.get(review.id) == review


def test_create_from_template_keeps_comments_and_sets_name(workspace, tmp_path):
    review = workspace.create_review(
        tmp_path / "ml", name="my ml review", template="machine-learning"
    )

    text = review.config_path.read_text(encoding="utf-8")
    assert review.name == "my ml review"
    assert text.startswith("# SciLEx domain template")
    assert "Arxiv" in text


def test_create_refuses_existing_config(workspace, tmp_path):
    workspace.create_review(tmp_path / "rag", name="rag_kg")

    with pytest.raises(FileExistsError):
        workspace.create_review(tmp_path / "rag", name="other")


def test_open_is_idempotent(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")

    workspace.open_review(review.folder)

    assert len(workspace.list_reviews()) == 1


def test_open_folder_without_config(workspace, tmp_path):
    with pytest.raises(FileNotFoundError):
        workspace.open_review(tmp_path)


def test_open_invalid_config(workspace, tmp_path):
    (tmp_path / "scilex.yml").write_text("name: x\nunknown_block: 1\n")

    with pytest.raises(SettingsError):
        workspace.open_review(tmp_path)


def test_vanished_folder_is_skipped(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.config_path.unlink()

    assert workspace.list_reviews() == []


def test_forget_review_keeps_files(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")

    workspace.forget_review(review.folder)

    assert workspace.list_reviews() == []
    assert review.config_path.is_file()


def test_output_dir_resolved_against_review_folder(workspace, tmp_path, monkeypatch):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    monkeypatch.chdir(tmp_path.parent)  # anywhere but the review folder

    config = Workspace.load_config(review)

    expected = (tmp_path / "rag" / "output").resolve()
    assert review.output_root == expected
    assert Path(config.main["output_dir"]) == expected
    assert config.main["collect_name"] == "rag_kg"


def test_has_results_once_aggregated(workspace, tmp_path):
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title;year\n")

    assert read_review(review.folder).has_results


def test_relative_folder_starts_in_scilex_folder(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # "~" on Windows
    monkeypatch.chdir("/")  # like a macOS app bundle: read-only working directory

    review = workspace.create_review(Path("Test"), name="test")

    assert review.folder == (tmp_path / "home" / "SciLEx" / "Test").resolve()
    assert review.config_path.is_file()


def test_invalid_config_keeps_review_listed_with_error(tmp_path):
    workspace = Workspace(registry_path=tmp_path / "registry.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.config_path.write_text("search:\n  keywords: [[a]]\n  yearz: [2024]\n")

    listed = workspace.list_reviews()
    assert [r.id for r in listed] == [review.id]
    assert listed[0].error
    assert workspace.get(review.id).name == "rag"


def test_corrupt_registry_is_kept_and_does_not_crash(workspace):
    workspace.registry_path.parent.mkdir(parents=True)
    workspace.registry_path.write_text("reviews: [unclosed\n  - a: b: c\n")
    assert workspace.list_reviews() == []
    corrupt = workspace.registry_path.with_name("gui_reviews.yml.corrupt")
    assert "unclosed" in corrupt.read_text()


def test_registry_write_is_atomic(workspace, tmp_path, monkeypatch):
    workspace.create_review(tmp_path / "rag", name="rag_kg")
    before = workspace.registry_path.read_text()

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("scilex.gui.services.workspace.os.replace", boom)
    with pytest.raises(OSError):
        workspace._save_folders([])
    assert workspace.registry_path.read_text() == before
    assert not list(workspace.registry_path.parent.glob("*.tmp"))


def test_open_review_without_keys_file(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv("SCILEX_KEYS", str(tmp_path / "missing-keys.yml"))
    review = workspace.create_review(tmp_path / "nokeys", name="nokeys")
    assert review.name == "nokeys"
    assert workspace.get(review.id) is not None


def test_failed_registration_rolls_back_new_config(workspace, tmp_path, monkeypatch):
    def boom(_folders):
        raise OSError("registry not writable")

    monkeypatch.setattr(workspace, "_save_folders", boom)
    folder = tmp_path / "rollback"
    with pytest.raises(OSError):
        workspace.create_review(folder, name="rollback")
    assert not (folder / "scilex.yml").exists()
    monkeypatch.undo()
    assert workspace.create_review(folder, name="rollback").name == "rollback"


def test_invalid_review_shows_name_from_raw_yaml(workspace, tmp_path):
    folder = tmp_path / "folder_name"
    folder.mkdir()
    (folder / "scilex.yml").write_text("name: pretty name\nbogus: 1\n")
    workspace._save_folders([folder])
    (review,) = workspace.list_reviews()
    assert review.error
    assert review.name == "pretty name"
