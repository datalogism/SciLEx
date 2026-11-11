"""Citation snapshot from Zotero notes and the metrics computed from it."""

from datetime import date

import pandas as pd

from scilex import citation_metrics as cm
from scilex.gui.services import zotero_citations as zc


def test_parse_note_reads_python_and_json_notes():
    note = "<p>{&apos;citing&apos;: [&apos;10.1/X&apos;], &apos;cited&apos;: []}</p>"
    assert zc.parse_note(note) == {"citing": ["10.1/X"], "cited": []}
    assert zc.parse_note('<p>{"citing": [], "cited": ["10.2/y"]}</p>') == {
        "citing": [],
        "cited": ["10.2/y"],
    }
    assert zc.parse_note("<p>Just a note</p>") is None


def test_to_caches_keys_by_doi_and_counts():
    notes = {
        "A": {"citing": ["10.9/c1", "10.9/c2"], "cited": ["10.1/b"]},
        "B": {"citing": [], "cited": []},
        "C": {"citing": ["10.9/c1"], "cited": []},
    }
    items = [
        {"key": "A", "data": {"DOI": "https://doi.org/10.1/A"}},
        {"key": "B", "data": {"DOI": "10.1/b"}},
        {"key": "C", "data": {"DOI": ""}},
    ]
    refs, cits, report = zc.to_caches(notes, items)
    assert refs["10.1/a"] == ["10.1/b"] and cits["10.1/a"] == ["10.9/c1", "10.9/c2"]
    assert (report.papers, report.empty, report.without_doi) == (2, 1, 1)


def test_metrics_and_tags():
    data = pd.DataFrame(
        {
            "DOI": ["10.1/a", "10.1/b", "NA"],
            "date": ["2020", "2018", "2021"],
            "quality_score": [87, 40, None],
            "tags": ["TASK:RE;CITATIONS:10^9", "", "LANG:English"],
        }
    )
    refs = {"10.1/a": ["10.1/b", "10.5/out"], "10.1/b": []}
    cits = {"10.1/a": [f"10.9/{i}" for i in range(150)], "10.1/b": ["10.1/a"]}
    tagged = cm.annotate(data, refs, cits, today=date(2024, 6, 1))

    assert tagged == 2  # the paper without DOI or quality gets none
    a, b, c = (data.loc[i] for i in range(3))
    assert a["metric_citations"] == 150 and a["metric_references"] == 2
    assert a["metric_citations_year"] == 30.0  # 150 citations over 2020-2024
    assert b["metric_cited_in_corpus"] == 1 and a["metric_cites_in_corpus"] == 1
    assert a["tags"].split(";") == [
        "TASK:RE",  # other tags kept, old CITATIONS tag replaced
        "CITATIONS:10^2",
        "REFERENCES:10^0",
        "CITATIONS_PER_YEAR:10^1",
        "CITED_IN_CORPUS:0",
        "PAGERANK:other",
        "QUALITY:80",
    ]
    assert b["metric_pagerank"] > a["metric_pagerank"]  # the cited paper ranks first
    assert c["tags"] == "LANG:English"  # no DOI, no quality: nothing added


def test_scilex_tags_are_never_annotation_codes():
    from scilex.review_tags import WORKFLOW_PREFIXES
    from scilex.tagging.grid import is_automation_tag

    for dimension in (*cm.METRIC_DIMENSIONS, *WORKFLOW_PREFIXES, "SCREEN"):
        assert is_automation_tag(f"{dimension}:x"), dimension
    assert not is_automation_tag("TASK:RE")
    assert not is_automation_tag("GRANULARITY:Document")
