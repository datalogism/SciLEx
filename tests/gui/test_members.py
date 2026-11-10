"""Workflow tags, review members and the assignment of papers to annotators."""

import pandas as pd
import pytest

from scilex import review_tags as rt
from scilex.gui.services import members as svc
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review

ORCID_A = "0000-0002-7302-9037"


def test_workflow_tags():
    state = rt.workflow(f"TASK:RE;ANNOT:{ORCID_A};ANNOT:bob;ANNOT_VALID_BY:bob")
    assert state.assigned == [ORCID_A, "bob"] and state.validated_by == ["bob"]
    assert state.status == "validated"
    assert rt.workflow("DELETED_BY:filter:year 2015").status == "deleted"
    assert rt.workflow("NA").status == "unassigned"
    assert rt.filter_tag("year 2015") == "DELETED_BY:filter:year 2015"
    assert rt.is_workflow_tag("ANNOT:bob") and not rt.is_workflow_tag("TASK:RE")
    assert rt.with_tags("A;B", add=["C", "a"], remove=["B"]) == "A;C"
    with pytest.raises(ValueError):
        rt.tag(rt.ASSIGNED, "x;y")


def test_member_identifier_and_save_checks(tmp_path):
    members = [
        svc.Member(
            name="Célian", username="celian_ringwald", orcid=ORCID_A, role="owner"
        ),
        svc.Member(name="Guest", role="manual"),
    ]
    assert members[0].identifier == ORCID_A and members[1].identifier == "Guest"
    svc.save(tmp_path, members)
    assert [m.identifier for m in svc.load(tmp_path)] == [ORCID_A, "Guest"]
    with pytest.raises(ValueError, match="ORCID"):
        svc.save(tmp_path, [svc.Member(name="x", orcid="1234")])
    with pytest.raises(ValueError, match="Two members"):
        svc.save(tmp_path, [svc.Member(name="x"), svc.Member(name="X")])


def test_merge_keeps_orcid_and_best_role():
    members = [svc.Member(zotero_id="5", orcid=ORCID_A, role="contributor")]
    svc._merge(members, svc.Member(zotero_id="5", username="celian", role="owner"))
    assert members == [
        svc.Member(username="celian", zotero_id="5", orcid=ORCID_A, role="owner")
    ]


@pytest.fixture
def review(tmp_path):
    review = Review(folder=tmp_path, name="re", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "title": [f"Paper {i}" for i in range(6)],
            "itemType": ["journalArticle"] * 6,
            "date": ["2021"] * 6,
            "tags": ["ANNOT:ann", "", "", "DELETED_BY:filter:year", "", "TASK:RE"],
            "zotero_collections": [
                "models",
                "models",
                "datasets",
                "models",
                "datasets",
                "datasets",
            ],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_balanced_assignment_and_progress(review):
    data = read_results(review.results_path)
    plan = svc.plan_assignment(data, ["ann", "bob"])
    # Paper 0 already "ann", paper 3 discarded: 4 papers, loads balanced 3/3? no: 1+2 vs 2.
    assert sorted(plan.plan) == [1, 2, 4, 5]
    assert plan.load == {"ann": 2, "bob": 3} or plan.load == {"ann": 3, "bob": 2}

    only_datasets = svc.plan_assignment(data, ["ann", "bob"], sub_corpus="datasets")
    assert sorted(only_datasets.plan) == [2, 4, 5]

    cross = svc.plan_assignment(
        data, ["ann", "bob"], per_paper=2, only_unassigned=False
    )
    assert cross.plan[0] == ["bob"]  # completes paper 0 with the second annotator
    assert all(len(whos) == 2 for i, whos in cross.plan.items() if i != 0)

    assert svc.assign(review, plan) == 4
    data = read_results(review.results_path)
    assert data.at[5, "tags"].startswith("TASK:RE;ANNOT:")
    table = {row["annotator"]: row for row in svc.progress(data)}
    assert table["ann"]["assigned"] + table["bob"]["assigned"] == 5


@pytest.mark.anyio
async def test_annotators_card_assigns_papers(ctx, tmp_path):
    from nicegui.testing import user_simulation

    from scilex.gui.app import build_root

    review = ctx.workspace.create_review(tmp_path / "ann", name="ann_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "title": ["A paper", "B paper", "C paper"],
            "itemType": ["journalArticle"] * 3,
            "date": ["2021"] * 3,
        }
    ).to_csv(review.results_path, sep=";")
    svc.save(
        review.folder, [svc.Member(name="Ann", orcid=ORCID_A), svc.Member(name="Bob")]
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/annotate")
        await user.should_see(marker="annotators-card", retries=20)
        user.find(marker="annotators-preview-button").click()
        await user.should_see("3 papers to assign")
        user.find(marker="annotators-apply").click()
        await user.should_see(marker="annotators-progress", retries=20)
    tags = ";".join(str(t) for t in read_results(review.results_path)["tags"])
    assert tags.count(f"ANNOT:{ORCID_A}") + tags.count("ANNOT:Bob") == 3
