"""Simulated UI tests of the Screen step."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import screening

pytestmark = pytest.mark.anyio


def make_results(review):
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle", "conferencePaper", "journalArticle"],
            "title": ["Graph RAG", "Metabolomics KG", "Unrelated topic"],
            "authors": ["A. One;B. Two", "C. Three", "NA"],
            "abstract": ["About retrieval", "About metabolites", "Nothing"],
            "DOI": ["10.1/abc", "NA", "10.1/zzz"],
            "date": ["2024-01-01", "2023", "2022"],
            "journalAbbreviation": ["JAI", "NA", "NA"],
            "publisher": ["P", "ConfPub", "Pub"],
            "relevance_score": [9.0, 5.0, 1.0],
            "nb_citation": [10, 3, 0],
        }
    ).to_csv(review.results_path, sep=";")


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    make_results(review)
    return review


async def test_include_with_note_saves_and_updates_counters(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see("Graph RAG")  # best score is selected first
        user.find(marker="decision-note").type("core paper")
        user.find(marker="decide-include").click()

        decisions = screening.load_decisions(review)
        assert len(decisions) == 1
        decision = next(iter(decisions.values()))
        assert decision.decision == "include"
        assert decision.note == "core paper"
        counters = user.find(marker="screen-counters").elements.pop()
        assert "Included 1" in counters.text
        assert "Undecided 2" in counters.text
        # moved on to the next undecided paper
        await user.should_see("About metabolites")


async def test_decision_filter_and_search(ctx, review):
    first = screening.load_results(review)["paper_key"].iloc[0]
    screening.set_decision(review, first, screening.EXCLUDE)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="screen-grid", retries=20)  # loaded off-loop
        grid = user.find(marker="screen-grid").elements.pop()
        assert len(grid.options["rowData"]) == 3

        decision_filter = user.find(marker="decision-filter").elements.pop()
        decision_filter.set_value("exclude")
        assert [r["title"] for r in grid.options["rowData"]] == ["Graph RAG"]
        decision_filter.set_value("undecided")
        assert len(grid.options["rowData"]) == 2
        user.find(marker="text-search").elements.pop().set_value("metabol")
        assert [r["title"] for r in grid.options["rowData"]] == ["Metabolomics KG"]


async def test_orphans_can_be_forgotten(ctx, review):
    screening.set_decision(review, "doi:10.9/gone", screening.MAYBE)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="orphans")
        user.find(content="Forget").click()
    assert "doi:10.9/gone" not in screening.load_decisions(review)


async def test_facet_filters_and_clear(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="screen-grid", retries=20)
        grid = user.find(marker="screen-grid").elements.pop()
        type_filter = user.find(marker="facet-item_type").elements.pop()
        type_filter.set_value(["Journal article"])
        assert [r["title"] for r in grid.options["rowData"]] == [
            "Graph RAG",
            "Unrelated topic",
        ]
        user.find(marker="clear-filters").click()
        assert len(grid.options["rowData"]) == 3


async def test_collection_selector_in_the_toolbar(ctx, review):
    data = pd.read_csv(review.results_path, sep=";", index_col=0)
    data["zotero_collections"] = ["Corpus/Core", "Corpus/Side", "Other"]
    data.to_csv(review.results_path, sep=";")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="screen-grid", retries=20)
        grid = user.find(marker="screen-grid").elements.pop()
        selector = user.find(marker="collection-filter").elements.pop()
        selector.set_value(["Corpus"])
        assert sorted(r["title"] for r in grid.options["rowData"]) == [
            "Graph RAG",
            "Metabolomics KG",
        ]
        selector.set_value([])
        assert len(grid.options["rowData"]) == 3
