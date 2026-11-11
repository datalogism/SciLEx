"""PRISMA flow of the Overview."""

import json

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import journal, prisma, screening
from scilex.gui.services.extend import write_results


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    folder = review.collection_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "filtering_summary.json").write_text(
        json.dumps(
            {
                "initial_count": 120,
                "final_count": 3,
                "stages": [
                    {"stage": "Initial", "papers": 120, "removed": 0},
                    {"stage": "Deduplication", "papers": 80, "removed": 40},
                    {"stage": "Abstract filter", "papers": 3, "removed": 77},
                    {"stage": "Relevance Ranking", "papers": 3, "removed": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {"title": "Kept A", "DOI": "10.1/a", "tags": ""},
        {"title": "Kept B", "DOI": "10.1/b", "tags": ""},
        {"title": "Old C", "DOI": "10.1/c", "tags": "DELETED_BY:filter:year"},
        {
            "title": "Snowballed D",
            "DOI": "10.1/d",
            "tags": "",
            "extension_origin": "bibtex refs.bib 2026-11-11",
        },
    ]
    write_results(
        pd.DataFrame([{**r, "itemType": "journalArticle"} for r in rows]),
        review.results_path,
    )
    screening.set_decision(review, "doi:10.1/a", screening.INCLUDE)
    screening.set_decision(review, "doi:10.1/b", screening.EXCLUDE)
    journal.append(
        review.folder,
        "analysis-crossref",
        params={"category": "enrichment", "source": "Crossref"},
        generated={"papers_updated": 3},
    )
    return review


def test_flow_counts(review):
    main = {
        "apis": ["OpenAlex", "Arxiv"],
        "keywords": [["rag"], ["graph"]],
        "years": [2022, 2024],
    }
    flow = prisma.compute(review, main)
    assert flow.identification.count == 120
    assert "Databases: OpenAlex, Arxiv" in flow.identification.lines
    assert "Keywords: (rag) AND (graph)" in flow.identification.lines
    assert flow.removed_before.count == 117
    assert "Deduplication: 40" in flow.removed_before.lines
    assert flow.other_sources.count == 1
    assert flow.other_sources.lines[0] == "BibTeX: 1 papers in the review"
    assert flow.screened.count == 4
    assert flow.excluded.count == 2  # one excluded, one discarded by a filter
    assert flow.included.count == 1
    assert flow.pending.count == 1
    assert flow.enrichment.lines == ["Crossref: 3 papers updated"]


@pytest.mark.anyio
async def test_overview_shows_the_flow(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="overview-prisma", retries=40)
        await user.should_see(marker="prisma-included")
        await user.should_see("Records excluded")


def test_overview_counts_paper_types(review):
    from scilex.gui.services import overview

    data = overview.compute(review)
    assert sum(data.by_type.values()) == 4
    assert data.by_type == {"Model or Method": 4}  # no cue in these titles
    assert sum(sum(v.values()) for v in data.type_by_year.values()) == 0  # no dates


def test_export_figure_and_types_tagged_after_import(review, tmp_path):
    flow = prisma.compute(review, {"apis": ["OpenAlex"]})
    files = prisma.export_figure(flow, tmp_path / "out")
    assert [f.name for f in files] == ["prisma_flow.svg", "prisma_flow.png"]
    assert "Records identified" in files[0].read_text(encoding="utf-8")

    from scilex.gui.services.paper_enrich import tag_types

    assert tag_types(review.results_path) == 4  # every paper gets a type
    assert tag_types(review.results_path) == 0  # once only


@pytest.mark.anyio
async def test_overview_exports_the_flow(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="prisma-export", retries=40)
        user.find(marker="prisma-export").click()
        await user.should_see("PRISMA flow saved", retries=40)
    assert (review.collection_dir / "prisma_flow.svg").is_file()
