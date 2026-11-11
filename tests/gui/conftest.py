"""Shared fixtures for the desktop GUI tests."""

from pathlib import Path

import pytest

pytest.importorskip("nicegui", reason="GUI extra not installed (uv sync --extra gui)")

TEST_ORCID = "0000-0002-1825-0097"  # ORCID's documented example iD (valid check digit)


@pytest.fixture(autouse=True)
def isolated_scilex_env(tmp_path, monkeypatch):
    """Keep the user's real scilex.yml / keys.yml out of every GUI test."""
    keys_path = tmp_path / "keys.yml"
    keys_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("SCILEX_KEYS", str(keys_path))
    monkeypatch.delenv("SCILEX_CONFIG", raising=False)
    return keys_path


@pytest.fixture
def anyio_backend():
    """Run async GUI tests on asyncio only."""
    return "asyncio"


@pytest.fixture
def ctx(tmp_path):
    """App context on a temporary registry, with a fake pipeline writing a results file."""

    def fake_collection(config, progress_callback, cancel_event):
        progress_callback({"OpenAlex": {"articles": 2}}, 1, 1)

    def fake_aggregation(config, options, progress_callback):
        collection_dir = Path(config.main["output_dir"]) / config.main["collect_name"]
        collection_dir.mkdir(parents=True, exist_ok=True)
        (collection_dir / "aggregated_results.csv").write_text(
            "itemType;title;DOI;date;relevance_score\n"
            "journalArticle;Graph RAG for metabolomics;10.1/abc;2024;7.5\n"
        )
        progress_callback("done", 100, "Done")

    from scilex.gui.services.jobs import JobRunner
    from scilex.gui.services.workspace import Workspace
    from scilex.gui.state import AppContext
    from scilex.user_profile import UserProfile

    profile = UserProfile(path=tmp_path / "user.yml")
    profile.set(TEST_ORCID, "Test User")  # the app is locked without an ORCID iD
    return AppContext(
        workspace=Workspace(registry_path=tmp_path / "gui_reviews.yml"),
        runner=JobRunner(fake_collection, fake_aggregation),
        native=False,
        profile=profile,
    )


@pytest.fixture(autouse=True)
def _delete_closed_dialogs_at_once(monkeypatch):
    """Closed one-shot dialogs go away right after the click handler, not 1 s later."""
    from scilex.gui.components import dialogs

    monkeypatch.setattr(dialogs, "DELETE_DELAY_SECONDS", 0)
