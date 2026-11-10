"""Provenance of a review: origin, agents, extensions, enrichments, annotation, Zotero actors."""

import time

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import journal, provenance
from scilex.init_templates import skeleton_text


def _wait(ctx, review, kind):
    for _ in range(300):
        job = ctx.runner.latest_for(review.id, kind)
        if job is not None and not job.is_active:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


# --- origin (backfill) -----------------------------------------------------------


def test_backfill_infers_a_zotero_import(tmp_path):
    (tmp_path / "scilex.yml").write_text(
        "# scilex.yml: created from the Zotero collection 'datasets' on 2026-11-10.\n"
        + skeleton_text("SurveyRE"),
        encoding="utf-8",
    )
    (tmp_path / "zotero_source.yml").write_text(
        "library_id: '6070963'\nlibrary_type: group\ncollection_key: JDPEMF65\n"
        "collection_name: datasets\nlibrary_name: scilex_re_systlitreview\n",
        encoding="utf-8",
    )
    journal.backfill(tmp_path)
    created = journal.last(tmp_path, "created")
    assert created["params"]["origin"] == journal.ZOTERO_IMPORT
    assert created["used"]["zotero"]["library_id"] == "6070963"
    assert created["used"]["zotero"]["collection_name"] == "datasets"
    assert created["agent"] == journal.UNKNOWN_AGENT
    card = provenance.review_card(tmp_path)
    assert card.origin_label == "Zotero import"
    assert card.origin_detail == "scilex_re_systlitreview — datasets"
    assert card.created_by == "unknown (before tracking)"


def test_backfill_infers_a_scilex_collection(tmp_path):
    (tmp_path / "scilex.yml").write_text(skeleton_text("re"), encoding="utf-8")
    collect = tmp_path / "output" / "re"
    collect.mkdir(parents=True)
    (collect / "config_used.yml").write_text(
        "collect_name: re\nkeywords: [[Relation extraction, Triple Extraction]]\n"
        "years: [2019, 2024]\napis: [HAL, Arxiv]\n",
        encoding="utf-8",
    )
    journal.backfill(tmp_path)
    created = journal.last(tmp_path, "created")
    assert created["params"]["origin"] == journal.SCILEX_COLLECT
    assert created["params"]["apis"] == ["HAL", "Arxiv"]
    assert len(created["params"]["config_sha256"]) == 64
    card = provenance.review_card(tmp_path)
    assert card.origin_detail == (
        "(Relation extraction | Triple Extraction), 2019–2024 on HAL, Arxiv"
    )


def test_backfill_falls_back_on_the_archive_column(tmp_path):
    (tmp_path / "scilex.yml").write_text(skeleton_text("b"), encoding="utf-8")
    out = tmp_path / "output" / "b"
    out.mkdir(parents=True)
    (out / "aggregated_results.csv").write_text(
        "itemType;title;archive\njournalArticle;A;BibTeX\njournalArticle;B;BibTeX\n",
        encoding="utf-8",
    )
    journal.backfill(tmp_path)
    assert (
        journal.last(tmp_path, "created")["params"]["origin"] == journal.BIBTEX_IMPORT
    )


# --- who, extensions and enrichments --------------------------------------------------


def test_enrichment_and_extension_events_say_who_when_and_how_many(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    review.collection_dir.mkdir(parents=True)
    rows = pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 3,
            "title": ["A", "B", "C"],
            "crossref_type": ["", "", ""],
        }
    )
    rows.to_csv(review.results_path, sep=";", index=False)

    def extend(job):  # +2 papers
        more = pd.concat(
            [rows, rows.head(2).assign(title=["D", "E"])], ignore_index=True
        )
        more.to_csv(review.results_path, sep=";", index=False)
        return "2 new papers"

    def crossref(fill):
        def body(job):
            data = pd.read_csv(
                review.results_path, sep=";", dtype=str, keep_default_na=False
            )
            data.loc[: fill - 1, "crossref_type"] = "journal-article"
            time.sleep(0.02)  # a visible change of the file's modification time
            data.to_csv(review.results_path, sep=";", index=False)
            return f"{fill} papers"

        return body

    ctx.runner.start_task(review, "x", extend, history_key="extend-add")
    _wait(ctx, review, "x")
    ctx.runner.start_task(review, "e", crossref(1), history_key="analysis-crossref")
    _wait(ctx, review, "e")
    ctx.runner.start_task(review, "e", crossref(3), history_key="analysis-crossref")
    _wait(ctx, review, "e")

    events = journal.load(review.folder)
    extension = next(e for e in events if e["activity"] == "job:extend-add")
    assert extension["agent"]["name"] == "Test User"
    assert extension["params"]["category"] == "extension"
    assert extension["params"]["started_at"] <= extension["at"]
    assert extension["generated"]["results_rows"] == 5
    enrichments = [e for e in events if e["activity"] == "job:analysis-crossref"]
    assert [e["params"]["source"] for e in enrichments] == ["Crossref", "Crossref"]
    assert enrichments[0]["generated"]["filled"]["crossref_type"] == 1
    assert enrichments[1]["generated"]["papers_updated"] == 2
    assert enrichments[1]["generated"]["columns_written"] == ["crossref_type"]

    card = provenance.review_card(review.folder)
    assert card.origin == journal.EMPTY or card.origin == journal.SCILEX_COLLECT
    assert [(s.what, s.who) for s in card.enrichments] == [
        ("Crossref", "Test User")
    ] * 2
    assert card.enrichments[-1].papers == 2
    assert card.extensions[0].what == "new queries (add new papers)"
    assert card.scilex_users["Test User"] >= 4


# --- annotation growth -------------------------------------------------------------------


def test_annotation_state_and_delta(tmp_path):
    first = journal.annotation_state([["TASK:RE"], ["LANG:English"], []])
    assert (first["papers"], first["annotated"], first["codes"]) == (3, 2, 2)
    journal.append(
        tmp_path, "created", params={"origin": journal.ZOTERO_IMPORT}, annotation=first
    )
    second = journal.annotation_state(
        [
            ["TASK:RE", "GRANULARITY:Document", "ANNOT_VALID_BY:0000-0002-1825-0097"],
            ["LANG:English"],
            ["TASK:NER", "ANNOT_VALID_BY:alice"],
        ]
    )
    assert second["validated"] == 2
    assert second["validated_by"] == {"0000-0002-1825-0097": 1, "alice": 1}
    assert second["by_dimension"]["TASK"] == 2
    event = journal.append(tmp_path, "zotero-pull", annotation=second)
    assert event["annotation"]["delta"] == {
        "papers": 0,
        "annotated": 1,
        "pending": 0,
        "codes": 2,
        "validated": 2,
    }
    card = provenance.review_card(tmp_path)
    assert [(a, c) for _, a, c in card.annotation] == [(2, 2), (3, 4)]


# --- Zotero-side actors ----------------------------------------------------------------


def _item(key, added, modified, creator, modifier=None):
    meta = {
        "createdByUser": {
            "id": creator[0],
            "username": creator[1],
            "name": creator[1].title(),
        }
    }
    if modifier:
        meta["lastModifiedByUser"] = {"id": modifier[0], "username": modifier[1]}
    return {
        "key": key,
        "meta": meta,
        "data": {"dateAdded": added, "dateModified": modified},
    }


def test_zotero_actors_counts_creators_and_modifiers_since_last_read(tmp_path):
    items = [
        _item(
            "A",
            "2026-11-01T10:00:00Z",
            "2026-11-10T15:00:00Z",
            (1, "celian"),
            (2, "fabien"),
        ),
        _item("B", "2026-11-09T10:00:00Z", "2026-11-09T10:00:00Z", (1, "celian")),
        _item(
            "C",
            "2026-11-10T16:00:00Z",
            "2026-11-10T16:00:00Z",
            (3, "hanna"),
            (3, "hanna"),
        ),
    ]
    everyone = journal.zotero_actors(items)
    assert everyone["celian"]["created"] == 2 and everyone["celian"]["modified"] == 1
    assert everyone["fabien"] == {
        "id": 2,
        "name": "fabien",
        "created": 0,
        "modified": 1,
    }
    since = journal.zotero_actors(items, since="2026-11-10T00:00:00Z")
    assert set(since) == {"fabien", "hanna"}
    assert since["hanna"]["created"] == 1 and since["hanna"]["modified"] == 1

    journal.append(tmp_path, "zotero-pull", zotero_actors=since)
    card = provenance.review_card(tmp_path)
    assert card.zotero_users == {"fabien": 1, "hanna": 2}


# --- Overview card ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_overview_shows_the_review_card(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "card", name="card")
    review.collection_dir.mkdir(parents=True)
    (review.results_path).write_text(
        "itemType;title;tags\njournalArticle;A;TASK:RE\n", encoding="utf-8"
    )
    journal.append(
        review.folder,
        "extend-zotero",
        params={"category": "extension", "mode": "Zotero"},
        generated={"added": 70},
        zotero_actors={
            "hanna": {"id": 3, "name": "hanna", "created": 2, "modified": 1}
        },
        annotation=journal.annotation_state([["TASK:RE"]]),
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="review-card", retries=20)
        await user.should_see(marker="review-extensions")
        await user.should_see("Zotero — +70 added")
        await user.should_see("hanna (3)")
