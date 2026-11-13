"""Eligibility criteria: defaults, rules, exceptions, apply and re-apply."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import criteria as cr
from scilex.gui.services import screening
from scilex.gui.services.extend import read_results, write_results

MAIN = {
    "years": [2019, 2020, 2021, 2022, 2023, 2024],
    "keywords": [["survey", "review"], ["question answering"]],
}

ROWS = [
    {  # passes everything
        "title": "A survey of question answering",
        "abstract": "We review the question answering methods of the field.",
        "date": "2022",
        "DOI": "10.1/a",
        "itemType": "journalArticle",
    },
    {  # too old, but a dataset paper: exception of C1
        "title": "SQuAD: a dataset for question answering",
        "abstract": "A reading comprehension dataset we review in depth.",
        "date": "2016",
        "DOI": "10.1/b",
        "itemType": "conferencePaper",
    },
    {  # too old, no exception
        "title": "Old review of question answering",
        "abstract": "",
        "date": "2010",
        "DOI": "10.1/c",
        "itemType": "journalArticle",
    },
    {  # no keyword of group 2, no DOI, arXiv preprint
        "title": "A survey of graph learning",
        "abstract": "",
        "date": "2023",
        "DOI": "",
        "itemType": "preprint",
    },
    {  # older version of the first paper
        "title": "A survey of question answering",
        "abstract": "",
        "date": "2020",
        "DOI": "",
        "itemType": "preprint",
    },
]


def frame():
    return pd.DataFrame(ROWS)


def by_id(items):
    return {c.id: c for c in items}


def test_defaults_follow_the_review():
    c = by_id(cr.defaults(MAIN))
    assert c["C1"].params == {"start": 2019, "end": 2024}
    assert c["C2"].params["groups"] == [["survey", "review"], ["question answering"]]
    assert [x.id for x in cr.defaults(MAIN)] == [
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
        "C8",
        "C9",
    ]
    assert not by_id(cr.defaults(MAIN))["C9"].enabled  # needs citation counts


def test_each_rule():
    c = by_id(cr.defaults(MAIN))
    data = frame()
    period = cr.test(c["C1"], data)
    assert [p.title for p in period.excluded] == ["Old review of question answering"]
    assert [p.title for p in period.spared] == [
        "SQuAD: a dataset for question answering"
    ]
    coherence = cr.test(c["C2"], data)
    assert [p.title for p in coherence.excluded] == ["A survey of graph learning"]
    assert len(cr.test(c["C6"], data).excluded) == 2  # no DOI
    assert len(cr.test(c["C5"], data).excluded) == 2  # preprints
    duplicates = cr.test(c["C7"], data)
    assert [(p.index, p.cause) for p in duplicates.excluded] == [
        (4, "older version (2020) of a paper of 2022")
    ]


def test_people_exceptions_and_included_papers_are_kept():
    c = by_id(cr.defaults(MAIN))["C1"]
    data = frame()
    data.loc[2, "tags"] = "KEEP:C1"
    assert cr.test(c, data).excluded == []
    data.loc[2, "tags"] = ""
    assert cr.test(c, data, included={"doi:10.1/c"}).excluded == []
    data.loc[2, "tags"] = "DELETED_BY:0000-0002-1825-0097"  # a person's discard
    result = cr.test(c, data)
    assert result.excluded == [] and result.checked == 4


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(frame(), review.results_path)
    return review


def test_apply_tags_then_reapply_untags(review):
    items = cr.defaults(MAIN)
    counts = cr.apply(review, items)
    assert counts["C1"] == 1 and counts["C6"] == 2
    tags = read_results(review.results_path)["tags"].fillna("").tolist()
    assert tags[2] == "DELETED_BY:filter:C1 published in 2010, outside 2019-2024"
    assert cr.excluded_by_criterion(tags) == {"C1": 1, "C2": 1, "C6": 2, "C7": 1}
    # The paper is now included in Screen: applying again removes its tag.
    screening.set_decision(review, "doi:10.1/c", screening.INCLUDE)
    cr.apply(review, items)
    tags = read_results(review.results_path)["tags"].fillna("").tolist()
    assert "C1" not in str(tags[2])
    table = cr.markdown_table(items)
    assert "| C1 – Publication period | Not published between 2019 and 2024 |" in table
    assert "C4" not in table  # disabled


def test_save_refuses_bad_ids(tmp_path):
    items = cr.defaults(MAIN)
    items[1].id = "C1"
    with pytest.raises(ValueError, match="Two criteria"):
        cr.save(tmp_path, items)
    items[1].id = "C 2"
    with pytest.raises(ValueError, match="Invalid"):
        cr.save(tmp_path, items)


@pytest.mark.anyio
async def test_page_tests_and_applies(ctx, review):
    cr.save(review.folder, cr.defaults(MAIN))  # not the template's years
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/criteria")
        await user.should_see(marker="criterion-C1")
        user.find(marker="criterion-test-C1").click()
        await user.should_see(
            "C1: 1 of 5 papers excluded, 1 kept by an exception.", retries=40
        )
        user.find(marker="criteria-apply").click()
        await user.should_see(marker="criteria-apply-confirm", retries=20)
        user.find(marker="criteria-apply-confirm").click()
        await user.should_see("Excluded:", retries=40)
    assert cr.path_of(review.folder).is_file()


def test_quality_criterion_uses_scilex_yml_rules():
    main = {**MAIN, "quality_filters": {"require_abstract": True}}
    c8 = by_id(cr.defaults(main))["C8"]
    assert c8.enabled
    excluded = cr.test(c8, frame()).excluded
    assert {p.title for p in excluded} == {
        "Old review of question answering",
        "A survey of graph learning",
        "A survey of question answering",  # the abstract-less older version
    }
    assert all(p.cause == "no abstract" for p in excluded)
    assert not by_id(cr.defaults(MAIN))["C8"].enabled  # no quality filters set


def test_panel_verdicts():
    from scilex.gui.components.criteria_panel import verdicts

    items = cr.defaults(MAIN)
    old = {**ROWS[2], "tags": ""}
    states = {c.id: state for c, state, _ in verdicts(old, items)}
    assert states["C1"] == "excluded" and states["C6"] == "pass"
    states = {
        c.id: state for c, state, _ in verdicts({**old, "tags": "KEEP:C1"}, items)
    }
    assert states["C1"] == "kept"
    tagged = {
        **ROWS[0],
        "tags": "DELETED_BY:filter:C7 older version (2020) of a paper of 2022",
    }
    states = {c.id: state for c, state, _ in verdicts(tagged, items)}
    assert states["C7"] == "tagged"


@pytest.mark.anyio
async def test_screen_offers_keep_as_exception(ctx, review):
    cr.save(review.folder, cr.defaults(MAIN))
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/screen")
        await user.should_see(marker="detail-panel", retries=40)
        await user.should_see(marker="paper-criteria")
    # The old paper: keep it as an exception to C1, from its panel.
    from scilex.gui.components import criteria_panel
    from scilex.gui.services.screening import ScreeningSession

    session = ScreeningSession(review)
    assert await criteria_panel.write_tags(
        review, session, "doi:10.1/c", ["KEEP:C1"], []
    )
    assert "KEEP:C1" in str(read_results(review.results_path).loc[2, "tags"])
    assert cr.apply(review, cr.defaults(MAIN))["C1"] == 0


METRIC_ROWS = [
    {
        "title": "a",
        "date": "2018",
        "DOI": "10.1/a",
        "nb_citation": 50,
        "metric_pagerank": 0.01,
        "venue_rank": "A",
    },
    {
        "title": "b",
        "date": "2018",
        "DOI": "10.1/b",
        "nb_citation": 1,
        "metric_pagerank": 0.5,
        "venue_rank": "Q4",
    },
    {
        "title": "c",
        "date": "2018",
        "DOI": "10.1/c",
        "nb_citation": 2,
        "metric_pagerank": 0.001,
    },
    {"title": "d", "date": "2026-10", "DOI": "10.1/d", "nb_citation": 0},
]


def metric(conditions, **params):
    return cr.Criterion(
        "C9", "Impact", "metric", params={"conditions": conditions, **params}
    )


def test_metric_thresholds_and_unknown_values():
    data = pd.DataFrame(METRIC_ROWS)
    at_least = metric([{"metric": "citations", "op": ">=", "value": 5}])
    assert [p.title for p in cr.test(at_least, data).excluded] == ["b", "c", "d"]
    venue = metric([{"metric": "venue_rank", "op": ">=", "value": 6}])
    assert [p.title for p in cr.test(venue, data).excluded] == ["b"]
    venue.params["missing"] = "exclude"
    causes = {p.title: p.cause for p in cr.test(venue, data).excluded}
    assert causes["c"] == "Venue rank unknown"


def test_metric_age_aware_and_top_percent_combined():
    data = pd.DataFrame(METRIC_ROWS)
    age = metric([{"metric": "citations", "op": "age_aware"}])
    # The recent paper is in its grace period.
    assert [p.title for p in cr.test(age, data).excluded] == ["b", "c"]
    top = metric([{"metric": "pagerank", "op": "top_percent", "value": 34}])
    assert [p.title for p in cr.test(top, data).excluded] == ["c"]
    # any: excluded only when every condition fails (b is central).
    both = metric(
        [
            {"metric": "citations", "op": "age_aware"},
            {"metric": "pagerank", "op": "top_n", "value": 1},
        ],
        match="any",
    )
    result = cr.test(both, data)
    assert [p.title for p in result.excluded] == ["c"]
    assert "PageRank: known for 3 of 4 papers" in " ".join(result.notes)
    # One paper alone: ranking conditions are not judged.
    assert cr.cause_of(top, METRIC_ROWS[2]) is None


def test_eligibility_per_paper(tmp_path):
    data = pd.DataFrame(ROWS)
    verdicts = cr.eligibility(cr.defaults(MAIN), data)
    assert verdicts["doi:10.1/c"]["C1"][0] == cr.EXCLUDED
    assert verdicts["doi:10.1/b"]["C1"][0] == cr.KEPT  # dataset paper
    assert "doi:10.1/a" not in verdicts  # meets all criteria


def test_save_refuses_bad_metric_conditions(tmp_path):
    with pytest.raises(ValueError, match="enough for its age"):
        cr.save(tmp_path, [metric([{"metric": "pagerank", "op": "age_aware"}])])
    with pytest.raises(ValueError, match="value is needed"):
        cr.save(tmp_path, [metric([{"metric": "citations", "op": ">="}])])
    cr.save(tmp_path, [metric([{"metric": "citations", "op": "age_aware"}])])
    assert cr.load(tmp_path)[0].params["conditions"][0]["op"] == "age_aware"


def test_aggregation_applies_the_saved_criteria(review):
    import threading
    from types import SimpleNamespace

    from scilex.gui.services.jobs import JobRunner

    job = SimpleNamespace(cancel_event=threading.Event(), message="")
    # Never saved: the aggregation leaves the papers as they are.
    assert JobRunner._apply_criteria(job, review) == ""
    assert "DELETED_BY" not in read_results(review.results_path).to_csv()
    cr.save(review.folder, cr.defaults(MAIN))
    message = JobRunner._extend(job, review, None, None)
    assert message.startswith("Eligibility criteria applied: C1 1")
    tags = read_results(review.results_path)["tags"].fillna("").tolist()
    # The paper type is tagged first, then the exclusion.
    assert tags[2].endswith(
        ";DELETED_BY:filter:C1 published in 2010, outside 2019-2024"
    )
