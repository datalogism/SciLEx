"""Tests of the screening decisions file."""

from pathlib import Path

import pandas as pd

from scilex.gui.services import screening
from scilex.gui.services.workspace import Review


def make_review(tmp_path: Path) -> Review:
    review = Review(folder=tmp_path, name="rag", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle", "conferencePaper"],
            "title": ["Graph RAG", "Metabolomics KG"],
            "DOI": ["https://doi.org/10.1/ABC", "NA"],
            "date": ["2024-01-01", "2023"],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_paper_key_prefers_doi_then_title_and_year():
    assert screening.paper_key({"DOI": "10.1/ABC", "title": "x"}) == "doi:10.1/abc"
    key = screening.paper_key(
        {"DOI": "NA", "title": "Metabolomics: KG!", "date": "2023"}
    )
    assert key == "title:metabolomics kg|2023"


def test_decisions_round_trip_and_survive_reaggregation(tmp_path):
    review = make_review(tmp_path)
    results = screening.load_results(review)
    first, second = results["paper_key"]
    screening.set_decision(review, first, screening.INCLUDE, "core paper")
    screening.set_decision(review, second, screening.EXCLUDE)

    decisions = screening.load_decisions(review)
    assert decisions[first].note == "core paper"
    assert list(screening.included_results(review)["title"]) == ["Graph RAG"]

    # Re-aggregation drops the second paper: its decision becomes an orphan.
    pd.DataFrame(
        {
            "itemType": ["journalArticle"],
            "title": ["Graph RAG"],
            "DOI": ["10.1/abc"],
            "date": ["2024"],
        }
    ).to_csv(review.results_path, sep=";")
    assert screening.orphan_keys(review, screening.load_results(review)) == [second]

    screening.set_decision(review, second, None)
    assert second not in screening.load_decisions(review)


def test_session_rows_counts_filters_and_navigation(tmp_path):
    review = make_review(tmp_path)
    session = screening.ScreeningSession(review)
    assert len(session.rows) == 2
    keys = [r["paper_key"] for r in session.rows]
    row = session.decide(keys[0], screening.INCLUDE, "n")
    assert row["decision"] == "Include"
    assert session.counts()["undecided"] == 1
    assert [r["paper_key"] for r in session.visible_rows("undecided")] == [keys[1]]
    assert session.visible_rows("exclude") == []
    assert session.next_undecided(keys, keys[0]) == keys[1]
    assert session.next_undecided(keys, keys[1]) is None
    assert session.update_note(keys[0], "changed")
    assert screening.load_decisions(review)[keys[0]].note == "changed"
    session.decide(keys[0], None)
    assert session.counts()["undecided"] == 2


def test_unknown_rows_are_kept_when_rewriting(tmp_path):
    review = make_review(tmp_path)
    first, _ = screening.load_results(review)["paper_key"]
    screening.screening_path(review).write_text(
        "paper_key,decision,note,updated_at\n"
        "doi:x,later,keep me,2024\n"
        ",include,no key,2024\n"
    )
    screening.set_decision(review, first, screening.INCLUDE)
    text = screening.screening_path(review).read_text()
    assert "doi:x,later,keep me,2024" in text
    assert ",include,no key,2024" in text
    assert list(screening.load_decisions(review)) == [first]


def test_two_sessions_do_not_overwrite_each_other(tmp_path):
    review = make_review(tmp_path)
    first, second = screening.load_results(review)["paper_key"]
    window_a = screening.ScreeningSession(review)
    window_b = screening.ScreeningSession(review)
    window_a.decide(first, screening.INCLUDE)
    window_b.decide(second, screening.EXCLUDE)
    saved = screening.load_decisions(review)
    assert set(saved) == {first, second}
    assert window_b.decision_of(first).decision == screening.INCLUDE
    assert window_b.row(first)["decision"] == "Include"


def make_faceted_review(tmp_path: Path) -> Review:
    review = Review(folder=tmp_path, name="rag", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle", "conferencePaper", "conferencePaper"],
            "title": ["Graph RAG", "Metabolomics KG", "Snowballed"],
            "DOI": ["10.1/a", "10.1/b", "10.1/c"],
            "date": ["2024", "2023", "2022"],
            "archive": ["OpenAlex*;SemanticScholar", "Zotero", "SemanticScholar"],
            "collect_keywords": ["Collect_KW1:RAG;Collect_KW2:KG", "NA", "NA"],
            "tags": ["TASK:RE;LANG:English", "TASK:NER", "NA"],
            "lpwc_tasks": ["Relation Extraction", "NA", "NA"],
            "snowball_depth": [0, 0, 1],
            "extension_origin": ["", "", ""],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_facets_filter_by_type_origin_keywords_and_tags(tmp_path):
    review = make_faceted_review(tmp_path)
    session = screening.ScreeningSession(review)
    options = session.facet_options()

    assert dict(options["item_type"]) == {"Conference paper": 2, "Journal article": 1}
    assert dict(options["origin"]) == {"Collect": 1, "Zotero import": 1, "Snowball": 1}
    assert dict(options["source"]) == {"SemanticScholar": 2, "OpenAlex": 1, "Zotero": 1}
    assert dict(options["collect_keywords"]) == {"RAG": 1, "KG": 1, "(none)": 2}
    assert "orkg_fields" not in options  # no paper has a value

    def titles(**facets):
        return [r["title"] for r in session.visible_rows(facets=facets)]

    assert titles(item_type={"Conference paper"}) == ["Metabolomics KG", "Snowballed"]
    # Values of one facet are OR-ed, facets are AND-ed.
    assert titles(tags={"TASK:RE", "TASK:NER"}) == ["Graph RAG", "Metabolomics KG"]
    assert titles(tags={"TASK:RE", "TASK:NER"}, origin={"Zotero import"}) == [
        "Metabolomics KG"
    ]
    assert titles(lpwc_tasks={"(none)"}) == ["Metabolomics KG", "Snowballed"]
    assert len(titles(item_type=set())) == 3  # an empty selection filters nothing


def test_paper_log_dates_only_papers_added_after_it_exists(tmp_path):
    import datetime as dt

    from scilex.gui.services import paper_log

    review = make_faceted_review(tmp_path)
    data = screening.load_results(review)
    # First sight of an existing review: the papers predate the log.
    log = paper_log.update(review.folder, data, when=dt.date(2026, 11, 10))
    assert {entry["imported_at"] for entry in log.values()} == {None}

    extra = pd.DataFrame(
        {
            "title": ["New one"],
            "DOI": ["10.1/new"],
            "date": ["2025"],
            "extension_origin": ["query 2026-11-09"],
        }
    )
    log = paper_log.update(
        review.folder, pd.concat([data, extra]), when=dt.date(2026, 11, 10)
    )
    assert log["doi:10.1/new"] == {
        "imported_at": "2026-11-09",
        "origin": "Extend collect",
    }

    other = tmp_path / "fresh"
    log = paper_log.update(other, data, when=dt.date(2026, 11, 10), fresh=True)
    assert {entry["imported_at"] for entry in log.values()} == {"2026-11-10"}
    assert paper_log.load(other) == log


def test_citation_network_feeds_cited_and_in_corpus_counts(tmp_path):
    review = Review(folder=tmp_path, name="rag", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 3,
            "title": ["A", "B", "C"],
            "DOI": ["10.1/a", "10.1/b", "NA"],
            "date": ["2024", "2023", "2022"],
            "nb_citation": [1, 50, 3],
        }
    ).to_csv(review.results_path, sep=";")
    import json

    # A is cited by 3 papers, one of them B (also found through B's references);
    # B's citers were not fetched but A cites it.
    (review.collection_dir / "citers_cache.json").write_text(
        json.dumps({"https://doi.org/10.1/A": ["10.1/B", "10.9/x", "10.9/y"]})
    )
    (review.collection_dir / "citations_cache.json").write_text(
        json.dumps({"10.1/a": ["10.1/b"], "10.1/b": ["10.1/a", "10.9/z"]})
    )
    session = screening.ScreeningSession(review)
    rows = {r["title"]: r for r in session.rows}
    assert session.has_network
    assert rows["A"]["citations"] == 3  # network count beats the stale Collect 1
    assert rows["A"]["cited_in_corpus"] == 1
    assert rows["B"]["citations"] == 50  # Collect count kept when higher
    assert rows["B"]["cited_in_corpus"] == 1
    assert rows["C"]["cited_in_corpus"] is None  # no DOI
    assert session.network_counts("doi:10.1/a") == {
        "cited_in_corpus": 1,
        "network_citers": 3,
        "network_references": 1,
    }
    assert session.network_counts("doi:10.1/b") == {
        "cited_in_corpus": 1,
        "network_references": 2,
    }


def test_no_citation_network_leaves_counts_alone(tmp_path):
    review = make_review(tmp_path)
    session = screening.ScreeningSession(review)
    assert not session.has_network
    assert all(r["cited_in_corpus"] is None for r in session.rows)


def test_collection_filter_takes_subcollections(tmp_path):
    review = Review(folder=tmp_path, name="rag", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 4,
            "title": ["A", "B", "C", "D"],
            "date": ["2024"] * 4,
            "zotero_collections": [
                "Corpus/Included",
                "Corpus / Excluded;Other",
                "Other",
                "NA",
            ],
        }
    ).to_csv(review.results_path, sep=";")
    session = screening.ScreeningSession(review)
    assert session.collection_options() == [
        ("Corpus", 2),
        ("Corpus/Excluded", 1),
        ("Corpus/Included", 1),
        ("Other", 2),
        (screening.NONE_VALUE, 1),
    ]

    def titles(*chosen):
        rows = session.visible_rows(facets={"collection": set(chosen)})
        return sorted(r["title"] for r in rows)

    assert titles("Corpus") == ["A", "B"]
    assert titles("Corpus/Included") == ["A"]
    assert titles("Corpus/Included", "Other") == ["A", "B", "C"]
    assert titles(screening.NONE_VALUE) == ["D"]


def test_no_collection_selector_when_it_would_change_nothing(tmp_path):
    review = make_review(tmp_path)
    assert screening.ScreeningSession(review).collection_options() == []


def test_decision_records_who_decided_and_old_files_still_load(tmp_path):
    """SX-5: decided_by is the ORCID iD of the app user; old rows keep it empty."""
    from scilex.gui.services import journal

    review = make_review(tmp_path)
    old = screening.screening_path(review)
    old.write_text(
        "paper_key,decision,note,updated_at\ndoi:10.1/old,exclude,,2026-01-01\n",
        encoding="utf-8",
    )
    assert screening.load_decisions(review)["doi:10.1/old"].decided_by == ""
    journal.set_agent("https://orcid.org/0000-0002-1825-0097", "Ada")
    try:
        screening.set_decision(review, "doi:10.1/abc", screening.INCLUDE)
    finally:
        journal.set_agent("")
    decisions = screening.load_decisions(review)
    assert (
        decisions["doi:10.1/abc"].decided_by == "https://orcid.org/0000-0002-1825-0097"
    )
    assert decisions["doi:10.1/old"].decided_by == ""  # kept as it was
    assert "decided_by" in old.read_text(encoding="utf-8").splitlines()[0]
