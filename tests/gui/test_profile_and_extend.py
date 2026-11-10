"""ORCID gate, step layout and ⑤ Extend (add new papers / re-aggregate)."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.components.stepper import PIPELINE_STEPS, STEPS
from scilex.gui.services import extend
from scilex.user_profile import (
    InvalidOrcidError,
    UserProfile,
    normalize_orcid,
)

pytestmark = pytest.mark.anyio


# --- ORCID ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["0000-0002-1825-0097", "https://orcid.org/0000-0002-1825-0097", "0000000218250097"],
)
def test_normalize_orcid_accepts_the_usual_forms(text):
    assert normalize_orcid(text) == "0000-0002-1825-0097"


def test_normalize_orcid_checks_the_check_digit():
    assert normalize_orcid("0000-0002-1694-233X") == "0000-0002-1694-233X"
    with pytest.raises(InvalidOrcidError, match="check digit"):
        normalize_orcid("0000-0002-1825-0098")
    with pytest.raises(InvalidOrcidError):
        normalize_orcid("1234")


def test_profile_round_trip(tmp_path):
    profile = UserProfile(path=tmp_path / "user.yml")
    assert not profile.is_complete
    profile.set("https://orcid.org/0000-0002-1825-0097", "Josiah Carberry")
    loaded = UserProfile.load(tmp_path / "user.yml")
    assert loaded.orcid == "0000-0002-1825-0097"
    assert loaded.orcid_uri == "https://orcid.org/0000-0002-1825-0097"
    assert loaded.is_complete


async def test_app_is_locked_without_orcid(ctx, tmp_path):
    ctx.profile = UserProfile(path=tmp_path / "nobody.yml")
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        await user.should_see(marker="orcid-input")
        await user.should_not_see(marker="new-review")
        await user.open(f"/review/{review.id}/configure")
        await user.should_see(marker="orcid-input")
        user.find(marker="orcid-input").type("0000-0002-1825-0098")
        user.find(marker="orcid-save").click()
        await user.should_see("check digit")
        user.find(marker="orcid-input").clear().type("0000-0002-1825-0097")
        user.find(marker="orcid-save").click()
        await user.should_see(marker="new-review")
    assert ctx.profile.orcid == "0000-0002-1825-0097"


# --- steps ---------------------------------------------------------------------


def test_step_order():
    assert [step.key for step in PIPELINE_STEPS] == [
        "overview", "explore", "configure", "collect", "screen", "annotate", "extend",
        "consolidate", "enrich", "analyses", "export",
    ]


def test_collect_becomes_extend_collect_once_there_are_papers(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    assert STEPS["collect"].label_for(review) == "② Collect"
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title\nA\n")
    assert STEPS["collect"].label_for(review) == "⑤ Extend"


async def test_extend_collect_page(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title\nA\n")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="extend-title")
        await user.should_see(marker="extend-add")
        await user.should_see(marker="extend-reaggregate")
        await user.should_see(marker="analysis-tab-snowball")


# --- extension merges ------------------------------------------------------------


def _frame(rows):
    return pd.DataFrame(rows, columns=["title", "DOI", "date", "archive", "relevance_score"])


def test_add_new_only_keeps_existing_rows_and_appends_the_others():
    previous = _frame([["Old A", "10.1/a", "2020", "OpenAlex", "9"]])
    current = _frame([
        ["Old A (re-ranked)", "10.1/A", "2020", "OpenAlex", "1"],  # same DOI
        ["New B", "10.1/b", "2024", "OpenAlex", "5"],
        ["New B", "10.1/b", "2024", "Arxiv", "5"],  # duplicate in the new batch
    ])
    merged, added = extend.add_new_only(previous, current, origin="query test")
    assert added == 1
    assert merged["title"].tolist() == ["Old A", "New B"]
    assert merged.loc[0, "relevance_score"] == "9"  # ranking of existing papers kept
    assert merged.loc[1, extend.ORIGIN_COLUMN] == "query test"


def test_reaggregate_keeps_imported_and_snowballed_papers():
    previous = pd.DataFrame(
        {
            "title": ["From collect", "From Zotero", "From snowball", "Dropped by filter"],
            "DOI": ["10.1/c", "10.1/z", "10.1/s", "10.1/d"],
            "archive": ["OpenAlex", "Zotero", "SemanticScholar", "OpenAlex"],
            "snowball_depth": ["0", "0", "1", "0"],
        }
    )
    current = pd.DataFrame({"title": ["From collect"], "DOI": ["10.1/c"], "archive": ["OpenAlex"]})
    merged, carried = extend.keep_outside_rows(previous, current)
    assert carried == 2
    assert sorted(merged["title"]) == ["From Zotero", "From collect", "From snowball"]


def test_pipeline_extension_adds_to_existing_results(ctx, tmp_path):
    import time

    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    review.results_path.write_text(
        "itemType;title;DOI;date;relevance_score\n"
        "journalArticle;Existing paper;10.9/old;2020;9\n"
    )
    config = ctx.workspace.load_config(review)
    job = ctx.runner.start_pipeline(review, config, extend=extend.ADD_NEW)
    for _ in range(200):
        if not job.is_active:
            break
        time.sleep(0.05)
    assert job.error is None, job.error
    data = extend.read_results(review.results_path)
    assert sorted(data["title"]) == ["Existing paper", "Graph RAG for metabolomics"]
    assert "1 new papers added" in job.message
    assert (review.collection_dir / extend.BACKUP_DIRNAME / extend.BACKUP_FILENAME).is_file()
