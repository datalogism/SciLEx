"""Accessibility and coverage analysis."""

import pandas as pd

from scilex.gui.services import coverage

DATA = pd.DataFrame(
    [
        {  # open with a PDF, code, cited by B
            "title": "A",
            "DOI": "10.1/A",
            "pdf_url": "https://x/a.pdf",
            "github_repo": "https://github.com/x/a",
            "tags": "PAPER_TYPE:Dataset",
            "zotero_collections": "Core",
        },
        {  # arXiv: open; cites A
            "title": "B",
            "DOI": "10.48550/arXiv.2401.1",
            "tags": "PAPER_TYPE:Model or Method;HaveGithub",
            "zotero_collections": "Core;Extension 1",
        },
        {  # restricted, no DOI
            "title": "C",
            "DOI": "NA",
            "rights": "restricted",
            "tags": "NA",
            "zotero_collections": "Extension 1",
        },
        {  # nothing known
            "title": "D",
            "DOI": "10.1/d",
            "rights": "NA",
            "tags": "",
            "zotero_collections": "",
        },
    ]
)
REFERENCES = {"10.48550/arxiv.2401.1": ["10.1/a", "10.9/outside"]}
CITERS = {"10.1/a": ["10.48550/arxiv.2401.1"], "10.1/d": ["10.9/outside"]}


def test_per_paper_indicators():
    papers = coverage.per_paper(DATA, REFERENCES, CITERS).set_index("title")
    assert list(papers["access"]) == ["open (PDF)", "open", "restricted", "unknown"]
    assert list(papers["has_doi"]) == [True, True, False, True]
    assert list(papers["has_code"]) == [True, True, False, False]
    assert list(papers["has_citation_data"]) == [True, True, False, True]
    assert list(papers["cited"]) == [True, False, False, True]
    assert list(papers["cited_in_corpus"]) == [True, False, False, False]


def test_rates_per_collection_and_type():
    papers = coverage.per_paper(DATA, REFERENCES, CITERS, "collection")
    table = coverage.rates(papers, "collection").set_index("group")
    assert table.loc["All papers", "papers"] == 4
    assert table.loc["All papers", "has_doi"] == 75.0
    assert table.loc["Core", "papers"] == 2 and table.loc["Core", "accessible"] == 100.0
    assert table.loc["Extension 1", "papers"] == 2
    assert table.loc["(none)", "papers"] == 1
    typed = coverage.rates(coverage.per_paper(DATA, {}, {}, "paper_type"), "paper_type")
    # Every paper has a type: its PAPER_TYPE tag, else its default one.
    assert "(none)" not in set(typed["group"])
    assert set(typed["group"]) >= {"Dataset", "Model or Method"}


def test_run_writes_report_and_charts(tmp_path):
    message, files = coverage.run(DATA, tmp_path, lambda *_: None, "collection")
    assert "4 papers" in message and "75 % with a DOI" in message
    names = {f.name for f in files}
    assert {"coverage_report.md", "coverage_rates.png", "coverage_access.png"} <= names
    report = (tmp_path / "coverage_analysis" / "coverage_report.md").read_text("utf-8")
    assert "| Core | 2 |" in report
    assert "No citation data yet" in report  # no cache in tmp_path


def test_abstract_gap_warns_before_keyword_enrichment(tmp_path):
    from scilex.gui.services.analyses import abstract_gap
    from scilex.gui.services.extend import write_results

    rows = [
        {
            "title": f"P{i}",
            "itemType": "journalArticle",
            "abstract": "text" if i < 2 else "",
        }
        for i in range(5)
    ]
    write_results(pd.DataFrame(rows), tmp_path / "aggregated_results.csv")
    warning = abstract_gap(tmp_path)
    assert warning.startswith("3 of 5 papers (60 %) have no abstract")
    rows = [{**r, "abstract": "text"} for r in rows]
    write_results(pd.DataFrame(rows), tmp_path / "aggregated_results.csv")
    assert abstract_gap(tmp_path) is None
