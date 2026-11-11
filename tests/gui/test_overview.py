"""Overview: the first page of a review (counts, sub-corpora, annotation history)."""

import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import overview, screening

pytestmark = pytest.mark.anyio


def _review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text(
        "itemType;title;DOI;date;archive;zotero_collections;crossref_type\n"
        "journalArticle;A;10.1/a;2021;Zotero;Survey / Datasets;journal-article\n"
        'journalArticle;B;10.1/b;2023;Zotero;"Survey / Datasets;Survey / Models";NA\n'
        "journalArticle;C;10.1/c;2023;OpenAlex;NA;NA\n"
    )
    return review


def test_snapshot_counts_annotations_and_placeholders():
    snapshot = overview.snapshot_of(
        [["SAT_TASK:NER", "SAT_LANG:?", "HavePDF"], ["SAT_TASK:?"], ["free keyword"]],
        "annotate",
    )
    assert (snapshot.papers, snapshot.annotated, snapshot.pending, snapshot.values) == (3, 1, 2, 1)
    assert snapshot.by_dimension == {"SAT_TASK": 1}


def test_history_is_appended_and_read_in_order(tmp_path):
    overview.record_snapshot(tmp_path, [["SAT_TASK:?"]], "import")
    overview.record_snapshot(tmp_path, [["SAT_TASK:NER"]], "annotate")
    history = overview.load_history(tmp_path)
    assert [s.origin for s in history] == ["import", "annotate"]
    assert [s.annotated for s in history] == [0, 1]


def test_compute_overview(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    key = screening.paper_key({"DOI": "10.1/a"})
    screening.set_decision(review, key, screening.INCLUDE)
    data = overview.compute(review)
    assert data.papers == 3
    assert data.by_year == {2021: 1, 2023: 2}
    assert data.by_source == {"Zotero": 2, "OpenAlex": 1}
    assert data.by_collection == {"Survey / Datasets": 2, "Survey / Models": 1}
    assert data.screening["Included"] == 1 and data.screening["Not screened"] == 2
    assert data.enrichment == {"Crossref": 1}


async def test_opening_a_review_shows_its_overview(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    overview.record_snapshot(review.folder, [["SAT_TASK:NER"], ["SAT_TASK:?"]], "import")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see("Overview")
        await user.should_see(marker="tile-papers", retries=50)
        await user.should_see(marker="tile-collections")
        await user.should_see(marker="tile-annotated")
        await user.should_see(marker="overview-history")


async def test_overview_of_an_empty_review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "e", name="e")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="overview-empty", retries=50)


def test_snapshot_reads_workflow_tags():
    from scilex.gui.services.overview import snapshot_of

    snap = snapshot_of(
        [
            ["TASK:RE", "ANNOT:ann", "ANNOT_VALID_BY:ann"],
            ["TASK:?", "ANNOT:bob"],
            ["TASK:NER", "DELETED_BY:filter:year 2015"],
        ],
        "test",
    )
    assert (snap.papers, snap.annotated, snap.pending) == (2, 1, 1)
    assert (snap.validated, snap.assigned, snap.discarded) == (1, 2, 1)
    assert snap.by_dimension == {"TASK": 1}  # workflow tags are not dimensions
