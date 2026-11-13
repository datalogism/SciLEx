"""Simulated UI tests of the Explore screen."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root

pytestmark = pytest.mark.anyio


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "re", name="re_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle", "conferencePaper", "conferencePaper"],
            "title": ["REBEL", "DocRED", "HyperRED"],
            "abstract": ["Seq2seq RE.", "Document-level RE.", "Hyper-relational."],
            "DOI": ["10.1/rebel", "10.1/docred", "NA"],
            "date": ["2021", "2019", "2022"],
            "archive": ["Zotero", "Zotero", "Zotero"],
            "tags": [
                "TASK:RE;LANG:English",
                "TASK:RE;GRANULARITY:Document",
                "TASK:NER",
            ],
            "zotero_collections": ["models", "datasets", "datasets"],
            "lpwc_tasks": ["Relation Extraction", "NA", "NA"],
            "pwc_url": ["https://paperswithcode.com/paper/rebel", "NA", "NA"],
        }
    ).to_csv(review.results_path, sep=";")
    return review


async def test_filters_chart_and_notice(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/explore")
        await user.should_see(marker="explore-grid", retries=20)
        grid = user.find(marker="explore-grid").elements.pop()
        assert len(grid.options["rowData"]) == 3
        await user.should_see("3 of 3 papers")

        # The first paper's notice is open, with its tags grouped by dimension.
        await user.should_see(marker="explore-notice")
        await user.should_see("Papers with Code")

        user.find(marker="explore-facet-collection").elements.pop().set_value(
            ["datasets"]
        )
        assert {r["title"] for r in grid.options["rowData"]} == {"DocRED", "HyperRED"}
        await user.should_see("2 of 3 papers")

        tags = user.find(marker="explore-facet-tags").elements.pop()
        tags.set_value(["TASK:RE"])
        assert [r["title"] for r in grid.options["rowData"]] == ["DocRED"]

        chart = user.find(marker="explore-chart").elements.pop()
        assert chart.options["series"][0]["data"] == [1]

        user.find(marker="explore-clear").click()
        assert len(grid.options["rowData"]) == 3


async def test_notice_discards_and_validates_with_the_users_orcid(ctx, review):
    from scilex.gui.services.extend import read_results

    orcid = ctx.profile.orcid
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/explore")
        await user.should_see(marker="explore-notice", retries=20)
        user.find(marker="explore-discard").click()
        await user.should_see("discarded by " + orcid, retries=20)
        user.find(marker="explore-validate").click()
        await user.should_see("validated by " + orcid, retries=20)
        status = user.find(marker="explore-status").elements.pop()
        assert status.text == "deleted"  # discarding wins over validation

        tags = ";".join(str(t) for t in read_results(review.results_path)["tags"])
        assert f"DELETED_BY:{orcid}" in tags and f"ANNOT_VALID_BY:{orcid}" in tags


async def test_eligibility_filter(ctx, review):
    from scilex.gui.services import criteria as cr

    items = [c for c in cr.defaults({}) if c.id == "C6"]  # DOI required
    cr.save(review.folder, items)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/explore")
        await user.should_see(marker="explore-eligibility", retries=20)
        grid = user.find(marker="explore-grid").elements.pop()
        rows = {r["title"]: r for r in grid.options["rowData"]}
        assert rows["HyperRED"]["criteria"] == "C6"
        assert rows["HyperRED"]["criteria_causes"] == "C6: no DOI"
        eligibility = user.find(marker="explore-eligibility").elements.pop()
        assert "Excluded by C6 – Referenceability (1)" in eligibility.options.values()
        eligibility.set_value("fail:C6")
        assert [r["title"] for r in grid.options["rowData"]] == ["HyperRED"]
        eligibility.set_value("eligible")
        assert {r["title"] for r in grid.options["rowData"]} == {"REBEL", "DocRED"}


async def test_explore_from_any_step(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/criteria")
        await user.should_see(marker="explore-anywhere", retries=20)
        user.find(marker="explore-anywhere").click()
        await user.should_see(marker="explore-grid", retries=20)
        await user.should_see("3 of 3 papers", retries=20)
        await user.open(f"/review/{review.id}/explore")
        await user.should_see(marker="explore-grid", retries=20)
        await user.should_not_see(marker="explore-anywhere")
