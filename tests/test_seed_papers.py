"""Tests for the seed-papers mode (HTTP mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from scilex import seed_papers as seed
from scilex.config_defaults import get_default_quality_filters
from scilex.io_utils import load_aggregated_data

LONG_ABSTRACT = "This paper studies knowledge graphs for metabolomics data. " * 15


def _raw_paper(doi, title, year=2020, citations=50):
    return {
        "paperId": f"id-{doi}",
        "title": title,
        "abstract": LONG_ABSTRACT,
        "authors": [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}],
        "externalIds": {"DOI": doi},
        "publicationTypes": ["JournalArticle"],
        "publicationDate": f"{year}-05-01",
        "venue": "Journal of Tests",
        "citationCount": citations,
        "url": f"https://example.org/{doi}",
    }


def _response(payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_read_inputs(tmp_path):
    doi_file = tmp_path / "dois.txt"
    doi_file.write_text("# seeds\n10.1/A\nhttps://doi.org/10.1/b  # note\n\n10.1/a\n")
    assert seed.read_doi_file(str(doi_file)) == ["10.1/a", "10.1/b"]

    bib = tmp_path / "s.bib"
    bib.write_text(
        "@article{k1, title={T}, doi={10.2/X}}\n@article{k2, title={No doi}}\n"
    )
    assert seed.read_bibtex_dois(str(bib)) == ["10.2/x"]


def test_fetch_recommendations_request_shape():
    with patch.object(
        seed, "_rate_limited_post", return_value=_response({"recommendedPapers": [{}]})
    ) as post:
        result = seed.fetch_recommendations(["10.1/a"], api_key="k", limit=9999)
    headers, params, body = post.call_args.args
    assert headers["x-api-key"] == "k"
    assert params["limit"] == seed.MAX_RECOMMENDATIONS
    assert "title" in params["fields"] and "externalIds" in params["fields"]
    assert body == {"positivePaperIds": ["DOI:10.1/a"]}
    assert result == [{}]


def test_fetch_recommendations_retries_on_429():
    responses = [_response({}, 429), _response({"recommendedPapers": []})]
    with (
        patch.object(seed, "_rate_limited_post", side_effect=responses),
        patch("tenacity.nap.time.sleep"),
    ):
        assert seed.fetch_recommendations(["10.1/a"]) == []


def test_run_seed_writes_exportable_csv(tmp_path):
    raw = [
        _raw_paper("10.9/new1", "Graphs one"),
        _raw_paper("10.9/new2", "Graphs two"),
        _raw_paper("10.9/new1", "Graphs one duplicate"),
        _raw_paper("10.1/seed", "The seed itself"),
        # Not a bypass type (journal/conference): the quality filters apply.
        {
            **_raw_paper("10.9/noabs", "No abstract"),
            "abstract": None,
            "publicationTypes": None,
        },
    ]
    filters = get_default_quality_filters()
    filters["validate_year_range"] = False
    with patch.object(seed, "fetch_recommendations", return_value=raw):
        path, frame = seed.run_seed(
            ["10.1/seed"],
            10,
            None,
            filters,
            str(tmp_path / "coll"),
            "aggregated_results.csv",
        )
    assert sorted(frame["DOI"]) == ["10.9/new1", "10.9/new2"]
    loaded = load_aggregated_data({"collect_name": "coll", "output_dir": str(tmp_path)})
    assert len(loaded) == 2 and "itemType" in loaded.columns


def test_run_seed_with_snowball_appends_candidates(tmp_path):
    filters = get_default_quality_filters()
    filters["validate_year_range"] = False
    with (
        patch.object(
            seed,
            "fetch_recommendations",
            return_value=[_raw_paper("10.9/new1", "Graphs one")],
        ),
        patch(
            "scilex.citations.reference_fetcher.fetch_references_batch",
            return_value={"10.1/seed": ["10.7/cand"], "10.9/new1": ["10.7/cand"]},
        ),
        patch("scilex.citations.reference_fetcher.fetch_citers_batch", return_value={}),
        patch(
            "scilex.snowball.fetcher.fetch_metadata_batch",
            return_value=[
                seed.convert_ss_paper(_raw_paper("10.7/cand", "Candidate paper"))
            ],
        ),
    ):
        _, frame = seed.run_seed(
            ["10.1/seed"],
            10,
            None,
            filters,
            str(tmp_path),
            "aggregated_results.csv",
            with_snowball=True,
        )
    assert sorted(frame["DOI"]) == ["10.7/cand", "10.9/new1"]


def test_keyword_filter_applied_when_groups_given():
    filters = get_default_quality_filters()
    filters["validate_year_range"] = False
    frame = seed.recommendations_to_frame(
        [_raw_paper("10.9/a", "Graphs"), _raw_paper("10.9/b", "Other")]
    )
    frame.loc[1, "abstract"] = "Completely unrelated text about cooking. " * 10
    filtered = seed.apply_filters(
        frame, filters, [["knowledge graph"], ["metabolomics"]]
    )
    assert list(filtered["DOI"]) == ["10.9/a"]


def test_journal_articles_with_short_abstracts_are_kept():
    # S2 recommendations often have truncated abstracts; like the aggregation,
    # journal articles bypass the quality filters, other types do not.
    filters = get_default_quality_filters()
    filters["validate_year_range"] = False
    article = _raw_paper("10.9/a", "Graphs")
    preprint = {**_raw_paper("10.9/b", "Other"), "publicationTypes": None}
    frame = seed.recommendations_to_frame([article, preprint])
    frame["abstract"] = "A short truncated abstract of thirty words or so."
    filtered = seed.apply_filters(frame, filters)
    assert list(filtered["DOI"]) == ["10.9/a"]


def test_requested_fields_are_valid_s2_fields():
    # The S2 API answers 400 for an unknown field; the DOI is in externalIds.
    from scilex.snowball.fetcher import SS_FIELDS

    assert "DOI" not in SS_FIELDS.split(",")
    assert "externalIds" in SS_FIELDS.split(",")


def test_rate_limit_gives_a_clear_message(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["scilex-seed", "--dois", "10.1/a"])
    monkeypatch.setattr(seed, "_load_configs", lambda: ({"collect_name": "x"}, {}))
    monkeypatch.setattr(
        seed, "run_seed", MagicMock(side_effect=seed._RetryableSSError("HTTP 429"))
    )
    with pytest.raises(SystemExit):
        seed.main()
    output = capsys.readouterr()
    assert "keys.yml" in output.out + output.err
    assert "Traceback" not in output.out + output.err


def test_main_without_seed_exits(monkeypatch):
    monkeypatch.setattr("sys.argv", ["scilex-seed"])
    with pytest.raises(SystemExit):
        seed.main()
