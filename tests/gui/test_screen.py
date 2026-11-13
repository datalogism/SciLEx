"""Simulated UI tests of the Screen step."""

import asyncio

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


async def test_eligibility_filter(ctx, review):
    from scilex.gui.services import criteria as cr

    items = [c for c in cr.defaults({}) if c.id == "C6"]  # DOI required
    cr.save(review.folder, items)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="screen-eligibility", retries=20)
        grid = user.find(marker="screen-grid").elements.pop()
        rows = {r["title"]: r for r in grid.options["rowData"]}
        assert rows["Metabolomics KG"]["criteria"] == "C6"
        eligibility = user.find(marker="screen-eligibility").elements.pop()
        assert "Excluded by C6 – Referenceability (1)" in eligibility.options.values()
        eligibility.set_value("fail:C6")
        assert [r["title"] for r in grid.options["rowData"]] == ["Metabolomics KG"]
        await user.should_see("About metabolites")  # detail follows the filter
        eligibility.set_value("eligible")
        assert {r["title"] for r in grid.options["rowData"]} == {
            "Graph RAG",
            "Unrelated topic",
        }


async def test_paper_types_can_be_set_while_screening(ctx, review):
    from scilex.gui.services.extend import read_results

    async def tags_of(title, wanted):
        for _ in range(50):
            data = read_results(review.results_path).set_index("title")
            tags = str(data["tags"][title]) if "tags" in data.columns else ""
            if wanted(tags):
                return tags
            await asyncio.sleep(0.05)
        return tags

    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="paper-type-picker", retries=20)
        grid = user.find(marker="screen-grid").elements.pop()
        first = grid.options["rowData"][0]
        assert first["title"] == "Graph RAG"
        assert first["paper_type"] == "Model or Method"  # the default

        # The first choice replaces the default type.
        user.find(marker="paper-type-3").click()  # Dataset
        tags = await tags_of("Graph RAG", lambda t: "PAPER_TYPE:Dataset" in t)
        assert tags.count("PAPER_TYPE:") == 1 and "PAPER_TYPE:Dataset" in tags

        # A paper can be both a method and a dataset.
        user.find(marker="paper-type-4").click()  # Model or Method
        tags = await tags_of("Graph RAG", lambda t: "Model or Method" in t)
        assert "PAPER_TYPE:Dataset" in tags and "PAPER_TYPE:Model or Method" in tags

        # Clicking a type again switches it off.
        user.find(marker="paper-type-3").click()
        tags = await tags_of("Graph RAG", lambda t: "Dataset" not in t)
        assert tags.count("PAPER_TYPE:") == 1 and "Model or Method" in tags


async def test_ticked_papers_are_validated_or_deleted_at_once(ctx, review, monkeypatch):
    from nicegui import ui

    from scilex.gui.services.extend import read_results

    orcid = ctx.profile.orcid
    ticked = []

    async def selected_rows(self):
        return list(ticked)

    monkeypatch.setattr(ui.aggrid, "get_selected_rows", selected_rows)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="screen-grid", retries=20)
        await user.should_not_see(marker="bulk-delete")  # nothing ticked
        grid = user.find(marker="screen-grid").elements.pop()
        rows = {r["title"]: r for r in grid.options["rowData"]}
        ticked[:] = [rows["Graph RAG"], rows["Unrelated topic"]]
        user.find(marker="screen-grid").trigger("selectionChanged")
        await user.should_see("2 paper(s) ticked", retries=20)

        user.find(marker="bulk-delete").click()
        await user.should_see("2 paper(s) deleted", retries=20)
        tags = read_results(review.results_path).set_index("title")["tags"]
        assert f"DELETED_BY:{orcid}" in str(tags["Graph RAG"])
        assert f"DELETED_BY:{orcid}" in str(tags["Unrelated topic"])
        assert f"DELETED_BY:{orcid}" not in str(tags["Metabolomics KG"])

        ticked[:] = [rows["Metabolomics KG"]]
        user.find(marker="screen-grid").trigger("selectionChanged")
        await user.should_see("1 paper(s) ticked", retries=20)
        user.find(marker="bulk-validate").click()
        await user.should_see("1 paper(s) validated", retries=20)
        tags = read_results(review.results_path).set_index("title")["tags"]
        assert f"ANNOT_VALID_BY:{orcid}" in str(tags["Metabolomics KG"])


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
