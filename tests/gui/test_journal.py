"""Workflow journal, stable results folder and consistency checks of a review."""

import json
import time

import pandas as pd
import pytest
import yaml
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import config_editor, consistency, journal, zotero_library
from scilex.gui.services.workspace import (
    STATE_FILENAME,
    Workspace,
    adopt_folder,
    load_state,
    read_review,
)
from scilex.init_templates import skeleton_text

RESULTS = "itemType;title;DOI;date\njournalArticle;Graph RAG;10.1/a;2024\n"


def write_results(folder, rows=RESULTS):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "aggregated_results.csv").write_text(rows, encoding="utf-8")


def rename(review, new_name):
    path = review.config_path
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    path.write_text(
        text.replace(f"name: {json.dumps(data['name'])}", f"name: {new_name}").replace(
            f"name: {data['name']}\n", f"name: {new_name}\n"
        ),
        encoding="utf-8",
    )


# --- journal ------------------------------------------------------------------


def test_append_load_skips_damaged_lines_and_masks_secrets(tmp_path):
    journal.set_agent("https://orcid.org/0000-0002-1825-0097", "Ada Lovelace")
    event = journal.append(
        tmp_path,
        "extend-zotero",
        used={"zotero": {"library_id": "1", "api_key": "SECRETKEY123"}},
        message="GET https://api.example.org/items?api_key=SECRETKEY123&q=re",
    )
    assert event["agent"] == {
        "id": "https://orcid.org/0000-0002-1825-0097",
        "name": "Ada Lovelace",
    }
    with open(journal.journal_path(tmp_path), "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    text = journal.journal_path(tmp_path).read_text(encoding="utf-8")
    assert "SECRETKEY123" not in text
    events = journal.load(tmp_path)
    assert [e["activity"] for e in events] == ["extend-zotero"]
    assert events[0]["used"]["zotero"]["api_key"] == "***"
    journal.set_agent("")


def test_backfill_reconstructs_the_past_once(tmp_path):
    (tmp_path / "scilex.yml").write_text(
        "# scilex.yml: created from the Zotero collection 'datasets' on 2026-11-10.\n"
        + skeleton_text("re"),
        encoding="utf-8",
    )
    (tmp_path / "zotero_source.yml").write_text(
        "library_id: '6070963'\nlibrary_type: group\ncollection_key: null\n"
        "collection_name: ''\nlibrary_name: Group 6070963\n",
        encoding="utf-8",
    )
    (tmp_path / "gui_run_history.json").write_text(
        json.dumps(
            {"analysis-tags": {"finished_at": "2026-11-10T17:01:27", "message": "ok"}}
        ),
        encoding="utf-8",
    )
    (tmp_path / "annotation_history.jsonl").write_text(
        json.dumps({"at": "2026-11-10T16:46:08", "origin": "import", "papers": 210})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "paper_log.json").write_text(
        json.dumps({"doi:a": {"imported_at": "2026-11-10", "origin": "Zotero import"}}),
        encoding="utf-8",
    )
    collect = tmp_path / "output" / "SurveyREALL"
    collect.mkdir(parents=True)
    (collect / "config_used.yml").write_text("collect_name: SurveyREALL\napis: [HAL]\n")

    assert journal.backfill(tmp_path) == 6
    events = journal.load(tmp_path)
    assert all(e["inferred"] for e in events)
    assert [e["at"] for e in events] == sorted(e["at"] for e in events)
    activities = {e["activity"] for e in events}
    assert {
        "created",
        "link",
        "job:analysis-tags",
        "annotation-snapshot",
        "papers-added",
        "collect-started",
    } <= activities
    assert journal.backfill(tmp_path) == 0  # only once

    journal.append(tmp_path, "configure")
    assert len(journal.load(tmp_path)) == 7


# --- stable results folder ------------------------------------------------------


def test_rename_keeps_the_results_folder(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    write_results(review.collection_dir)
    rename(review, "rag_kg_v2")

    renamed = read_review(review.folder)
    assert renamed.name == "rag_kg_v2"
    assert renamed.collection_dir == review.collection_dir  # results did not move
    assert renamed.has_results
    config = Workspace.load_config(renamed)
    assert config.main["collect_name"] == "rag_kg"
    assert config.main["output_dir"] == str(review.collection_dir.parent)
    renames = [e for e in journal.load(review.folder) if e["activity"] == "rename"]
    assert renames[-1]["params"] == {"from": "rag_kg", "to": "rag_kg_v2"}
    assert load_state(review.folder)["names"] == ["rag_kg", "rag_kg_v2"]


def test_surveyreall_adopts_the_folder_named_after_the_review_folder(tmp_path):
    # Imported as TEST3, renamed SurveyREALL by an older SciLEx: the papers are
    # in output/TEST3 while output/SurveyREALL only holds a raw collection.
    folder = tmp_path / "TEST3"
    folder.mkdir()
    (folder / "scilex.yml").write_text(skeleton_text("SurveyREALL"), encoding="utf-8")
    write_results(folder / "output" / "TEST3")
    raw = folder / "output" / "SurveyREALL"
    raw.mkdir(parents=True)
    (raw / "config_used.yml").write_text("collect_name: SurveyREALL\n")

    review = read_review(folder)
    assert review.collection_dir == (folder / "output" / "TEST3").resolve()
    assert review.has_results
    assert load_state(folder)["output_folder"] == "output/TEST3"
    adopted = [e for e in journal.load(folder) if e["activity"] == "adopt-output"]
    assert adopted and adopted[-1]["generated"]["output_folder"] == "output/TEST3"
    # Recorded: the next read does not search again.
    assert read_review(folder).collection_dir == review.collection_dir


def test_new_review_records_its_own_folder(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "fresh", name="fresh")
    state = load_state(review.folder)
    assert state["output_folder"] == "output/fresh"
    assert (review.folder / STATE_FILENAME).is_file()
    created = journal.last(review.folder, "created")
    assert created["params"] == {"origin": "empty", "name": "fresh", "template": None}


# --- hooks ----------------------------------------------------------------------


def test_configure_and_link_are_journaled(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "hooks", name="hooks")
    config_editor.write_text(review, skeleton_text("hooks"))
    configure = journal.last(review.folder, "configure")
    assert len(configure["generated"]["scilex.yml sha256"]) == 64

    source = zotero_library.ZoteroSource(
        library_id="6756633",
        library_type="group",
        collection_key=None,
        collection_name="",
        library_name="scilexre_surveyv",
    )
    zotero_library.save_source(review.folder, source)
    zotero_library.save_source(review.folder, source)  # unchanged: one event only
    links = [e for e in journal.load(review.folder) if e["activity"] == "link"]
    assert len(links) == 1 and links[0]["used"]["zotero"]["library_id"] == "6756633"


def test_jobs_are_journaled_completed_and_failed(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "jobs", name="jobs")
    ctx.runner.start_task(review, "demo", lambda job: "fine")
    _wait(ctx, review, "demo")

    def boom(job):
        raise RuntimeError("broken with token=abc123")

    ctx.runner.start_task(review, "demo", boom)
    _wait(ctx, review, "demo")
    jobs = [e for e in journal.load(review.folder) if e["activity"] == "job:demo"]
    assert [e["status"] for e in jobs] == ["completed", "failed"]
    assert "abc123" not in jobs[1]["message"]


def _wait(ctx, review, kind):
    for _ in range(200):
        job = ctx.runner.latest_for(review.id, kind)
        if job is not None and not job.is_active:
            return
        time.sleep(0.01)
    raise AssertionError("job did not finish")


# --- consistency ------------------------------------------------------------------


def test_consistency_finds_results_elsewhere_and_adopt_fixes_it(tmp_path):
    folder = tmp_path / "TEST3"
    folder.mkdir()
    (folder / "scilex.yml").write_text(skeleton_text("SurveyREALL"), encoding="utf-8")
    (folder / STATE_FILENAME).write_text(
        "output_folder: output/SurveyREALL\nname: SurveyREALL\n"
    )
    write_results(folder / "output" / "TEST3")

    review = read_review(folder)
    issues = consistency.check(review)
    assert [i.kind for i in issues] == [consistency.RESULTS_ELSEWHERE]
    adopt_folder(folder, folder / "output" / "TEST3", "test")
    assert read_review(folder).has_results
    assert consistency.check(read_review(folder)) == []


def test_consistency_flags_a_zotero_library_changed_without_link(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "z", name="z")
    journal.append(
        review.folder,
        "import-zotero",
        used={"zotero": {"library_type": "group", "library_id": "6070963"}},
    )
    (review.folder / "zotero_source.yml").write_text(
        "library_id: '6756633'\nlibrary_type: group\ncollection_key: null\ncollection_name: ''\n"
    )
    assert [i.kind for i in consistency.check(review)] == [consistency.ZOTERO_CHANGED]
    zotero_library.save_source(review.folder, zotero_library.load_source(review.folder))
    journal.append(review.folder, "link", used={"zotero": {"library_id": "6756633"}})
    assert consistency.check(review) == []


def test_consistency_counts_papers_outside_required_subcorpora(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "s", name="s")
    write_results(
        review.collection_dir,
        "itemType;title;zotero_collections\njournalArticle;A;models\njournalArticle;B;NA\n",
    )
    issues = consistency.check(review, {"required_subcorpora": ["datasets", "models"]})
    assert [(i.kind, i.step) for i in issues] == [
        (consistency.UNCLASSIFIED, "consolidate")
    ]
    assert issues[0].message.startswith("1 papers")


# --- Overview ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_overview_shows_issues_and_history(ctx, tmp_path):
    folder = tmp_path / "TEST3"
    folder.mkdir()
    (folder / "scilex.yml").write_text(skeleton_text("SurveyREALL"), encoding="utf-8")
    (folder / STATE_FILENAME).write_text(
        "output_folder: output/SurveyREALL\nname: SurveyREALL\n"
    )
    write_results(folder / "output" / "TEST3")
    review = ctx.workspace.open_review(folder)
    journal.append(folder, "configure", message="saved")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="overview-issues", retries=20)
        await user.should_see(marker="overview-journal")
        await user.should_see("History")
        user.find(marker=f"issue-{consistency.RESULTS_ELSEWHERE}").click()
    assert read_review(folder).has_results
    assert pd.read_csv(read_review(folder).results_path, sep=";").shape[0] == 1
