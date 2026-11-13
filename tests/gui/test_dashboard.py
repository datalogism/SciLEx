"""Dashboard step: its data (papers, facets, eligibility, links) and page."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.pages import dashboard as page
from scilex.gui.services import criteria as cr
from scilex.gui.services import dashboard as service
from scilex.gui.services.screening import CitationNetwork, ScreeningSession


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "re", name="re_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle", "conferencePaper", "conferencePaper"],
            "title": ["REBEL", "DocRED: a dataset", "HyperRED"],
            "abstract": ["Seq2seq RE.", "Document-level RE.", "Hyper-relational."],
            "DOI": ["10.1/rebel", "10.1/docred", "NA"],
            "date": ["2021", "2019", "2022"],
            "nb_citation": [120, 300, "NA"],
            "archive": ["Zotero", "Zotero", "Zotero"],
            "tags": ["TASK:RE", "TASK:RE", "TASK:NER"],
            "zotero_collections": ["models", "datasets", "datasets"],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_payload_papers_facets_eligibility_and_links(review):
    cr.save(review.folder, [c for c in cr.defaults({}) if c.id == "C6"])
    session = ScreeningSession(review)
    items = cr.load(review.folder)
    from scilex.gui.pages.explore import compute_eligibility

    verdicts = compute_eligibility(session, items)
    network = CitationNetwork({"10.1/rebel": {"10.1/docred", "10.9/out"}}, {})
    data = service.payload(session, verdicts, network, items)
    by_title = {p["title"]: p for p in data["papers"]}
    assert by_title["HyperRED"]["fails"] == {"C6": "no DOI"}
    assert by_title["HyperRED"]["f"]["eligibility"] == [service.NOT_ELIGIBLE]
    assert by_title["REBEL"]["f"]["eligibility"] == [service.ELIGIBLE]
    assert by_title["DocRED: a dataset"]["citations"] == 300
    assert by_title["DocRED: a dataset"]["f"]["paper_type"] == ["Dataset"]
    assert "collection" in data["facets"] and "eligibility" in data["facets"]
    rebel = data["papers"].index(by_title["REBEL"])
    docred = data["papers"].index(by_title["DocRED: a dataset"])
    assert data["links"] == [[rebel, docred]]  # the outside DOI is left out
    assert data["criteria"] == {"C6": "Referenceability"}


def test_mount_script_loads_the_shipped_libraries():
    script = page.mount_script("root", {"papers": []})
    assert "/scilex-dashboard/vendor/d3.min.js" in script
    for name in ("d3.min.js", "crossfilter.min.js"):
        assert (page.ASSET_DIR / "vendor" / name).is_file()
    assert (page.ASSET_DIR / "dashboard.js").is_file()


@pytest.mark.anyio
async def test_page_opens_with_the_notice(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/dashboard")
        await user.should_see(marker="dashboard-root", retries=20)
        await user.should_see("Select a paper to read its notice.", retries=40)


def test_decision_and_validator_facets_feed_the_quick_filters(review):
    from scilex.gui.services import screening

    data = pd.read_csv(review.results_path, sep=";", index_col=0)
    data.loc[0, "tags"] = "TASK:RE;ANNOT_VALID_BY:0000-0002-1825-0097"
    data.to_csv(review.results_path, sep=";")
    session = ScreeningSession(review)
    rebel = next(r for r in session.rows if r["title"] == "REBEL")
    screening.set_decision(review, rebel["paper_key"], screening.MAYBE)
    payload = service.payload(ScreeningSession(review))
    by_title = {p["title"]: p for p in payload["papers"]}
    assert by_title["REBEL"]["f"]["decision"] == ["Maybe"]
    assert by_title["HyperRED"]["f"]["decision"] == ["Undecided"]
    assert by_title["REBEL"]["f"]["validated_by"] == ["0000-0002-1825-0097"]
    # One validator only: still charted, the quick filter needs it.
    assert "validated_by" in payload["facets"]
    script = (page.ASSET_DIR / "dashboard.js").read_text(encoding="utf-8")
    assert 'count("decision", "Include")' in script  # the label of INCLUDE
    assert screening.DECISION_LABELS[screening.INCLUDE] == "Include"
