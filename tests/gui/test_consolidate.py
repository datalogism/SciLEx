"""Consolidation: duplicates across sources and the filters of scilex.yml."""

import pandas as pd
import pytest

from scilex.gui.services import consolidate, screening
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review

CONFIG = {
    "years": [2019, 2020, 2021, 2022],
    "quality_filters": {
        "validate_year_range": True,
        "enable_itemtype_bypass": True,
        "bypass_item_types": ["journalArticle"],
        "require_abstract": True,
    },
}


@pytest.fixture
def review(tmp_path):
    review = Review(folder=tmp_path, name="re", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "title": [
                "REBEL: Relation Extraction By End-to-end Language generation",
                "REBEL: Relation Extraction by End-to-End Language Generation.",
                "DocRED: A Large-Scale Document-Level Relation Extraction Dataset",
                "DocRED: A Large-Scale Document-Level Relation Extraction Dataset",
                "An old collected paper about relation extraction",
                "A conference paper without abstract on triples",
            ],
            "itemType": ["conferencePaper"] * 4 + ["journalArticle", "conferencePaper"],
            "DOI": ["10.1/rebel", "NA", "10.1/docred", "10.1/docred", "NA", "NA"],
            "date": ["2021", "2021", "2019", "2019", "2015", "2020"],
            "abstract": ["Seq2seq.", "NA", "Doc.", "Doc.", "Old.", "NA"],
            "archive": [
                "OpenAlex",
                "BibTeX",
                "Zotero",
                "Zotero",
                "OpenAlex",
                "SemanticScholar",
            ],
            "tags": ["TASK:RE", "TASK:RE;LANG:English", "TASK:RE", "TASK:NER", "", ""],
            "zotero_collections": ["", "", "models", "datasets", "", ""],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_plan_groups_fuzzy_titles_but_not_across_subcorpora(review):
    plan = consolidate.plan(review, CONFIG)
    assert len(plan.groups) == 1  # DocRED is in two sub-corpora: kept apart
    group = plan.groups[0]
    assert group.reason.startswith("similar titles") or group.reason == "same title"
    assert group.safe  # TASK:RE on both: no differing code

    apart = consolidate.plan(review, CONFIG, separate_subcorpora=False)
    docred = [g for g in apart.groups if "DocRED" in g.titles[0]][0]
    assert not docred.safe and docred.differing_codes == ["TASK:NER", "TASK:RE"]

    # Old paper filtered (year); the journal article is spared the quality
    # rules but not the year range; the one without abstract is filtered.
    reasons = {p.title[:8]: p.reasons for p in plan.filtered}
    assert reasons["An old c"] == ["year 2015 outside 2019-2022"]
    assert reasons["A confer"] == ["no abstract"]


def test_apply_merges_moves_decision_and_excludes_filtered(review):
    data = read_results(review.results_path)
    bibtex_copy = screening.paper_key(data.iloc[1].to_dict())
    screening.set_decision(review, bibtex_copy, screening.INCLUDE, "key paper")

    plan = consolidate.plan(review, CONFIG)
    message = consolidate.apply(review, plan, action=consolidate.EXCLUDE_IN_SCREEN)
    assert "1 duplicates merged into 1 papers" in message

    data = read_results(review.results_path)
    assert len(data) == 5
    rebel = data[data["title"].str.startswith("REBEL")].iloc[0]
    assert rebel["DOI"] == "10.1/rebel"  # the most complete copy was kept
    assert rebel["tags"] == "TASK:RE;LANG:English"  # new dimension added
    assert set(rebel["archive"].replace("*", "").split(";")) == {"OpenAlex", "BibTeX"}

    decisions = screening.load_decisions(review)
    kept_key = screening.paper_key(rebel.to_dict())
    assert decisions[kept_key].decision == screening.INCLUDE
    assert bibtex_copy not in decisions or bibtex_copy == kept_key
    excluded = [d for d in decisions.values() if d.decision == screening.EXCLUDE]
    assert len(excluded) == 2
    assert all(d.note.startswith("Consolidate:") for d in excluded)


def test_apply_refuses_a_stale_plan(review):
    plan = consolidate.plan(review, CONFIG)
    data = read_results(review.results_path)
    data.iloc[:3].to_csv(review.results_path, sep=";")
    with pytest.raises(ValueError, match="preview again"):
        consolidate.apply(review, plan)


@pytest.mark.anyio
async def test_page_previews_and_applies(ctx, tmp_path):
    from nicegui.testing import user_simulation

    from scilex.gui.app import build_root

    review = ctx.workspace.create_review(tmp_path / "c", name="c_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "title": ["Graph RAG for relation extraction"] * 2,
            "itemType": ["conferencePaper"] * 2,
            "DOI": ["10.1/g", "10.1/g"],
            "date": ["2024", "2024"],
            "abstract": ["A.", "A."],
            "archive": ["OpenAlex", "BibTeX"],
        }
    ).to_csv(review.results_path, sep=";")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/consolidate")
        user.find(marker="consolidate-preview").click()
        await user.should_see(marker="consolidate-summary", retries=20)
        await user.should_see(marker="consolidate-merge-0")
        user.find(marker="consolidate-apply").click()
        import asyncio

        for _ in range(
            100
        ):  # wait for the job (reading the file meanwhile locks it on Windows)
            job = ctx.runner.latest_for(review.id, "consolidate")
            if job is not None and not job.is_active:
                break
            await asyncio.sleep(0.05)
        assert job.status == "completed", job.error
        assert len(read_results(review.results_path)) == 1


def test_default_action_discards_with_a_filter_tag(review):
    plan = consolidate.plan(review, CONFIG)
    message = consolidate.apply(review, plan, merge=[])
    assert "2 filtered papers discarded" in message
    data = read_results(review.results_path)
    tags = {str(t)[:8]: str(row) for t, row in zip(data["title"], data["tags"])}
    assert tags["An old c"] == "DELETED_BY:filter:year 2015 outside 2019-2022"
    assert tags["A confer"] == "DELETED_BY:filter:no abstract"
    assert screening.load_decisions(review) == {}  # screening left alone
    # A second preview no longer lists them.
    assert consolidate.plan(review, CONFIG).filtered == []
