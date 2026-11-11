"""Compare by paper type / Zotero collection; paper details; one-paper enrichment."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import compare, paper_enrich
from scilex.gui.services import zotero_library as zl
from scilex.gui.services.extend import read_results, write_results

DATA = pd.DataFrame(
    [
        {
            "title": "A survey of RAG",
            "DOI": "10.1/a",
            "date": "2023",
            "archive": "OpenAlex",
            "collect_keywords": "Collect_KW1:rag",
            "tags": "TASK:QA;METHOD:?",
            "zotero_collections": "Core",
        },
        {
            "title": "RAGBench: a benchmark",
            "DOI": "10.1/b",
            "date": "2024",
            "archive": "Arxiv",
            "collect_keywords": "Collect_KW1:rag",
            "tags": "TASK:QA;PAPER_TYPE:Benchmark",
            "zotero_collections": "Core;Extension 1",
        },
        {
            "title": "GraphRAG",
            "DOI": "10.1/c",
            "date": "2024",
            "archive": "OpenAlex",
            "collect_keywords": "Collect_KW1:graph",
            "tags": "TASK:Summarization",
            "zotero_collections": "",
        },
    ]
)


def test_groups_of_each_choice():
    rows = DATA.to_dict("records")
    assert compare.groups_of(rows[0], compare.PAPER_TYPE) == [
        "Review or State of the art"
    ]
    assert compare.groups_of(rows[1], compare.PAPER_TYPE) == ["Benchmark"]
    assert compare.groups_of(rows[1], compare.COLLECTION) == ["Core", "Extension 1"]
    assert compare.groups_of(rows[2], compare.COLLECTION) == [compare.NO_GROUP]
    assert compare.groups_of(rows[0], compare.NONE) == []
    assert len(compare.exploded(DATA, compare.COLLECTION)) == 4


def test_report_charts(tmp_path):
    files = compare.report_charts(DATA, tmp_path, compare.PAPER_TYPE)
    names = {f.name for f in files}
    assert {
        "compare_paper_type_years.png",
        "compare_paper_type_sources.png",
        "compare_paper_type_keywords.png",
        "compare_types_per_collection.png",
    } <= names
    assert compare.report_charts(DATA, tmp_path, compare.NONE) == []


def test_annotation_comparison(tmp_path):
    files = compare.annotation_comparison(DATA, tmp_path, compare.COLLECTION)
    report = next(f for f in files if f.suffix == ".md").read_text("utf-8")
    assert "## TASK" in report
    assert "| Core | QA (2) |" in report
    assert "PAPER_TYPE" not in report.split("Papers per group")[1]  # not a dimension
    assert any(f.suffix == ".png" for f in files)


def test_community_composition(tmp_path):
    clusters = pd.DataFrame(
        {"DOI": ["10.1/a", "10.1/b", "10.1/c"], "cluster_id": [0, 0, 1]}
    )
    section, files = compare.community_composition(
        clusters, DATA, tmp_path, compare.PAPER_TYPE
    )
    assert "| Community 0 |" in section and files  # community 1 has one paper only
    assert "Community 1" not in section


def test_item_links():
    group = zl.ZoteroSource("42", "group", None, "")
    assert zl.item_links(group, "ABCD") == [
        ("Open in Zotero", "zotero://select/groups/42/items/ABCD"),
        ("zotero.org", "https://www.zotero.org/groups/42/items/ABCD"),
    ]
    assert zl.item_links(group, "NA") == []
    assert zl.item_links(None, "ABCD") == []


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(
        DATA.assign(itemType="journalArticle", zotero_key=["K1", "K2", "K3"]),
        review.results_path,
    )
    return review


def test_enrich_one_paper_only(review):
    message = paper_enrich.enrich_paper(
        review, "doi:10.1/c", "paper_types", lambda *_: None
    )
    assert message.startswith("1 papers tagged")
    rows = read_results(review.results_path).set_index("title")
    assert rows.loc["GraphRAG", "tags"].endswith("PAPER_TYPE:Model or Method")
    assert (
        "PAPER_TYPE" not in rows.loc["A survey of RAG", "tags"]
    )  # other papers untouched


@pytest.mark.anyio
async def test_explore_notice_shows_details_and_enriches(ctx, review):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", None, ""))
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/explore")
        await user.should_see(marker="explore-notice", retries=40)
        await user.should_see(marker="paper-badges")
        await user.should_see(marker="explore-zotero-link")
        await user.should_see(marker="paper-annotations")
        user.find(marker="explore-enrich").click()
        user.find(marker="explore-enrich-paper_types").click()
        await user.should_see("papers tagged", retries=50)
