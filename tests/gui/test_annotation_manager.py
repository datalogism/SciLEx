"""Annotation manager: -AUTO proposals, guideline, campaigns, LLM annotator import."""

import json

import pandas as pd
import pytest

from scilex import annotation_agreement
from scilex.gui.services import annotations, campaigns, llm_annotator
from scilex.gui.services.extend import read_results, write_results
from scilex.tagging import auto_tags
from scilex.tagging.grid import annotation_dimensions, is_automation_tag
from scilex.tagging.guideline import coverage, parse_guideline

GRID = pd.DataFrame(
    [
        {
            "tag": "TASK",
            "detail": "Task?",
            "datasets": "X",
            "surveys": "X",
            "models": "",
        },
        {
            "tag": "LANG",
            "detail": "Lang?",
            "datasets": "X",
            "surveys": "",
            "models": "",
        },
    ]
)


# -- tags ---------------------------------------------------------------------


def test_auto_tags_are_never_codes():
    assert is_automation_tag("TASK-AUTO:RC") and is_automation_tag("task-auto:x")
    assert not is_automation_tag("TASK:RC")
    items = [
        {
            "data": {
                "itemType": "journalArticle",
                "title": "t",
                "tags": [{"tag": "TASK-AUTO:RC"}, {"tag": "LANG:En"}],
            }
        }
    ]
    assert set(annotation_dimensions(items)) == {"LANG"}
    assert annotation_agreement.codes_by_dimension(["TASK-AUTO:RC", "LANG:En"]) == {
        "LANG": frozenset({"En"})
    }


def test_dimension_states_and_resolve():
    tags = "TASK:?;TASK-AUTO:RC;TASK-AUTO:NER;LANG:En;LANG-AUTO:Fr;HavePDF"
    states = auto_tags.dimension_states(tags, ["TASK", "LANG", "DOMAIN"])
    assert states["TASK"].status == auto_tags.PROPOSED
    assert states["TASK"].proposed == ["RC", "NER"] and states["TASK"].placeholder
    assert states["LANG"].status == auto_tags.HUMAN and states["LANG"].stale_proposals
    assert states["DOMAIN"].status == auto_tags.TODO

    add, remove = auto_tags.resolve(tags, "TASK", ["RC"])
    assert add == ["TASK:RC"]
    assert set(remove) == {"TASK-AUTO:RC", "TASK-AUTO:NER", "TASK:?"}
    add, remove = auto_tags.resolve(tags, "TASK", [])  # rejected: still to do
    assert add == ["TASK:?"] and "TASK:?" not in remove
    with pytest.raises(ValueError):
        auto_tags.auto_tag("TASK", "")


def test_guideline_sections_and_coverage():
    text = "# Guide\nGeneral rules.\n\n## TASK\nPick the task.\n---\n## Notes\nmisc\n"
    guide = parse_guideline(text, ["TASK", "LANG"])
    assert (
        guide.for_dimension("task").startswith("## TASK")
        and "---" not in guide.sections["TASK"]
    )
    assert "General rules" in guide.general and guide.other_headings == ["Notes"]
    cov = coverage(guide, ["TASK", "LANG"])
    assert cov.covered == ["TASK"] and cov.missing == ["LANG"] and cov.has_general


def test_review_guideline_round_trip(tmp_path, ctx):
    review = ctx.workspace.create_review(tmp_path / "g", name="g")
    annotations.save_review_grid(review, GRID)
    assert annotations.load_guideline_text(review) == ""
    annotations.save_guideline_text(review, "## LANG\r\nEnglish?\r\n")
    assert annotations.review_guideline(review).sections == {
        "LANG": "## LANG\nEnglish?"
    }
    assert annotations.save_guideline_text(review, "  ") is None
    assert not annotations.guideline_path(review).exists()


# -- campaigns ----------------------------------------------------------------


@pytest.fixture
def review(tmp_path, ctx):
    review = ctx.workspace.create_review(tmp_path / "r", name="rev")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(
        pd.DataFrame(
            [
                {
                    "title": "Alpha",
                    "DOI": "10.1/a",
                    "itemType": "journalArticle",
                    "date": "2021",
                    "zotero_key": "AAAA1111",
                    "zotero_collections": "datasets",
                    "tags": "TASK:?;LANG:?",
                },
                {
                    "title": "Beta",
                    "DOI": "10.1/b",
                    "itemType": "journalArticle",
                    "date": "2022",
                    "zotero_key": "BBBB2222",
                    "zotero_collections": "datasets / sub;models",
                    "tags": "TASK:NER;LANG:?",
                },
                {
                    "title": "Gamma",
                    "DOI": "10.1/c",
                    "itemType": "journalArticle",
                    "date": "2023",
                    "zotero_key": "CCCC3333",
                    "zotero_collections": "models",
                    "tags": "TASK:?",
                },
                {
                    "title": "Gone",
                    "DOI": "10.1/d",
                    "itemType": "journalArticle",
                    "date": "2023",
                    "zotero_key": "DDDD4444",
                    "zotero_collections": "datasets",
                    "tags": "DELETED_BY:ann",
                },
            ]
        ),
        review.results_path,
    )
    annotations.save_review_grid(review, GRID)
    return review


def tags_of(review):
    data = read_results(review.results_path)
    return dict(zip(data["title"], data["tags"].fillna(""), strict=True))


def test_campaign_store_and_papers(review):
    data = read_results(review.results_path)
    assert campaigns.collection_paths(data) == ["datasets", "datasets / sub", "models"]
    assert campaigns.suggest_type("datasets") == "datasets"
    assert campaigns.suggest_type("Surveys") == "surveys"
    campaign = campaigns.create(
        review.folder,
        "datasets",
        paper_type="datasets",
        annotators=["ann", "bob"],
        llm_models=["m1"],
    )
    again = campaigns.create(review.folder, "datasets")
    assert again.id == "datasets-2"
    loaded = campaigns.load(review.folder)
    assert [c.id for c in loaded.campaigns] == ["datasets", "datasets-2"]
    assert loaded.get("datasets").llm_models == ["m1"]
    # sub-collections belong to the campaign; discarded papers do not
    rows = campaigns.paper_rows(data, campaign)
    assert data.loc[rows, "title"].tolist() == ["Alpha", "Beta"]
    assert campaigns.dimensions(GRID, campaign) == ["TASK", "LANG"]
    plan = campaigns.plan_assignment(data, campaign)
    assert plan.load == {"ann": 1, "bob": 1}
    progress = campaigns.progress(data, campaign, ["TASK", "LANG"])
    assert progress.papers == 2 and progress.cells[auto_tags.HUMAN] == 1
    assert progress.cells[auto_tags.TODO] == 3
    campaigns.remove(review.folder, "datasets-2")
    assert len(campaigns.load(review.folder).campaigns) == 1


# -- LLM annotator ----------------------------------------------------------


def answer(tag, values, status="llm", final=None, model="m1", **extra):
    return {
        "tag": tag,
        "addressed": bool(values),
        "values": values,
        "final_values": final if final is not None else values,
        "confidence": "high",
        "rationale": "because",
        "model": model,
        "evidence": [{"quote": "q", "section": "s", "found": True}],
        "status": status,
        "reviewer": extra.get("reviewer", ""),
        "error": "",
    }


def test_tag_value_keeps_the_grid_vocabulary():
    assert llm_annotator.tag_value("SciBERT") == "SciBERT"
    assert llm_annotator.tag_value("RC") == "RC"
    assert llm_annotator.tag_value("deep learning") == "DeepLearning"


def test_import_is_human_first(review):
    campaign = campaigns.create(review.folder, "datasets", paper_type="datasets")
    data = read_results(review.results_path)
    plan = llm_annotator.plan_run(data, campaign, ["TASK", "LANG"])
    # Beta's TASK is coded by a person: it is not asked
    assert {k: len(v) for k, v in plan.groups.items()} == {
        ("TASK", "LANG"): 1,
        ("LANG",): 1,
    }
    _, keys = llm_annotator.bibtex_for(data, list(data.index[:2]))
    assert set(keys) == {"AAAA1111", "BBBB2222"}

    payload = {
        "job": {"model": "m1"},
        "papers": [
            {
                "key": "AAAA1111",
                "annotations": [
                    answer("TASK", ["RC", "relation classification"]),
                    answer("LANG", ["English"], status="accepted", reviewer="rev1"),
                ],
            },
            {
                "key": "BBBB2222",
                "annotations": [
                    answer("TASK", ["RC"]),  # a person coded TASK: kept locally only
                    answer("LANG", ["Chinese"], status="rejected", final=[]),
                ],
            },
        ],
    }
    report = llm_annotator.import_results(review, campaign, payload, keys, job_id="j1")
    assert report.proposals == 2 and report.validated == 1 and report.rejected == 1
    assert report.kept_local == 1
    tags = tags_of(review)
    assert (
        "TASK-AUTO:RC" in tags["Alpha"]
        and "TASK-AUTO:RelationClassification" in tags["Alpha"]
    )
    assert "LANG:English" in tags["Alpha"] and "LANG:?" not in tags["Alpha"]
    assert "TASK-AUTO" not in tags["Beta"] and "TASK:NER" in tags["Beta"]
    assert "LANG:?" in tags["Beta"] and "LANG-AUTO" not in tags["Beta"]
    stored = llm_annotator.answers(review, campaign.id)
    assert len(stored) == 4 and stored[0]["evidence"][0]["found"]
    outcomes = {
        (d["dimension"], d["outcome"], d["reviewer"])
        for d in llm_annotator.decisions(review)
    }
    assert outcomes == {("LANG", "accepted", "rev1"), ("LANG", "rejected", "")}
    # a re-run does not ask the rejected pair again
    data = read_results(review.results_path)
    plan = llm_annotator.plan_run(
        data, campaign, ["TASK", "LANG"], rejected=llm_annotator.rejected_pairs(review)
    )
    assert plan.groups == {}


def test_validate_and_reconcile(review):
    campaign = campaigns.create(review.folder, "datasets", paper_type="datasets")
    data = read_results(review.results_path)
    _, keys = llm_annotator.bibtex_for(data, list(data.index))
    payload = {
        "job": {"model": "m1"},
        "papers": [
            {
                "key": "AAAA1111",
                "annotations": [answer("TASK", ["RC"]), answer("LANG", ["En"])],
            },
            {"key": "BBBB2222", "annotations": [answer("LANG", ["Zh"])]},
        ],
    }
    llm_annotator.import_results(review, campaign, payload, keys)
    data = read_results(review.results_path)
    queue = llm_annotator.pending(review, data, [campaign], GRID)
    assert {(p.title, p.dimension) for p in queue} == {
        ("Alpha", "TASK"),
        ("Alpha", "LANG"),
        ("Beta", "LANG"),
    }
    by = {(p.title, p.dimension): p for p in queue}
    assert (
        by[("Alpha", "TASK")].confidence == "high"
        and by[("Alpha", "TASK")].evidence_found
    )
    llm_annotator.decide_many(
        review,
        [
            (by[("Alpha", "TASK")], "accepted", None),
            (by[("Alpha", "LANG")], "corrected", ["English", "French"]),
        ],
        reviewer="me",
    )
    tags = tags_of(review)["Alpha"].split(";")
    assert {"TASK:RC", "LANG:English", "LANG:French"} <= set(tags)
    assert not [t for t in tags if "-AUTO" in t or t.endswith(":?")]
    with pytest.raises(ValueError):
        llm_annotator.decide(review, by[("Beta", "LANG")], "corrected", [])

    # Beta's LANG is coded in Zotero (synced back), its proposal still there
    data = read_results(review.results_path)
    index = data.index[data["title"] == "Beta"][0]
    data.at[index, "tags"] = str(data.at[index, "tags"]).replace("LANG:?", "LANG:Zh")
    write_results(data, review.results_path)
    counts = llm_annotator.reconcile(review)
    assert counts == {"accepted": 1, "tidied": 1}
    assert "LANG-AUTO" not in tags_of(review)["Beta"]
    assert llm_annotator.reconcile(review) == {}  # already logged

    models = llm_annotator.llm_agreement(review, read_results(review.results_path))
    assert [m.model for m in models] == ["m1"]
    assert models[0].outcomes["accepted"] == 2 and models[0].outcomes["corrected"] == 1
    assert {d.dimension for d in models[0].dimensions} == {"TASK", "LANG"}
    coders = llm_annotator.coder_tags(review, {"AAAA1111"})
    assert coders == {"AAAA1111": {"llm:m1": ["TASK:RC", "LANG:En"]}}


class FakeHttp:
    """The SciLEx Annotator API, as seen through httpx."""

    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))

        class Response:
            status_code = 200

            def __init__(self, body):
                self.body = body

            def json(self):
                return self.body

        if path == "/reviews":
            return Response({"id": kwargs["data"]["name"]})
        if path.endswith("/jobs"):
            body = kwargs["json"]
            self.job = {
                "id": "j1",
                "model": body["model"],
                "keys": body["keys"],
                "tags": body["tags"],
            }
            return Response(self.job)
        if path.endswith("/results"):
            return Response(
                {
                    "job": self.job,
                    "papers": [
                        {
                            "key": key,
                            "annotations": [
                                answer(t, ["X"], model=self.job["model"])
                                for t in self.job["tags"]
                            ],
                        }
                        for key in self.job["keys"]
                    ],
                }
            )
        return Response({**self.job, "status": "done", "completed": 1})


def test_run_campaign_through_the_service(review):
    campaign = campaigns.create(review.folder, "models", paper_type="surveys")
    annotations.save_guideline_text(review, "## TASK\nThe task.\n")
    http = FakeHttp()
    client = llm_annotator.Client("http://x", http=http)
    report = llm_annotator.run_campaign(
        review, campaign, "m2", "http://x", client=client, poll=0
    )
    assert report.proposals == 1
    method, path, kwargs = http.calls[0]
    assert path == "/reviews" and kwargs["data"]["name"] == "rev-models"
    assert kwargs["data"]["paper_type"] == "surveys" and "guideline" in kwargs["files"]
    posted = next(c for c in http.calls if c[1].endswith("/jobs"))[2]["json"]
    assert posted["keys"] == ["CCCC3333"] and posted["tags"] == ["TASK"]
    assert "TASK:?" not in posted["bibtex"] and "Gamma" in posted["bibtex"]  # blind
    assert "TASK-AUTO:X" in tags_of(review)["Gamma"]
    record = json.loads(
        llm_annotator.store_path(review, campaign.id)
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert record["model"] == "m2" and record["job"] == "j1"


def test_run_plan_keeps_only_the_tags_the_service_annotates():
    plan = llm_annotator.RunPlan(
        groups={("TASK", "SCREEN"): [0, 1], ("SCREEN",): [2], ("LANG",): [3]}
    )
    assert plan.only({"TASK", "LANG"}).groups == {("TASK",): [0, 1], ("LANG",): [3]}
    assert plan.only(set()).groups == {}


def test_run_campaign_does_not_send_tags_the_service_excludes(review):
    class Excluding(FakeHttp):
        def request(self, method, path, **kwargs):
            response = super().request(method, path, **kwargs)
            if path == "/reviews":
                response.body["tags"] = ["LANG"]  # TASK excluded by the service
            return response

    campaign = campaigns.create(review.folder, "models", paper_type="surveys")
    http = Excluding()
    client = llm_annotator.Client("http://x", http=http)
    report = llm_annotator.run_campaign(
        review, campaign, "m2", "http://x", client=client, poll=0
    )
    assert report.proposals == 0
    assert not any(c[1].endswith("/jobs") for c in http.calls)


def test_new_answers_skips_seen_and_older_answers():
    old = {**answer("LANG", ["En"]), "created_at": "2026-01-01T00:00:00+00:00"}
    new = {**answer("TASK", ["RC"]), "created_at": "2026-02-01T00:00:00+00:00"}
    payload = {"job": {"model": "m1"}, "papers": [{"key": "K", "annotations": [old, new]}]}
    seen: set = set()
    since = "2026-01-15T00:00:00+00:00"
    fresh = llm_annotator.new_answers(payload, seen, since=since)
    assert [a["tag"] for a in fresh["papers"][0]["annotations"]] == ["TASK"]
    assert llm_annotator.new_answers(payload, seen, since=since) is None
    final = llm_annotator.new_answers(payload, seen)  # last pull: older ones too
    assert [a["tag"] for a in final["papers"][0]["annotations"]] == ["LANG"]
    assert llm_annotator.new_answers(payload, seen) is None


def test_run_campaign_imports_answers_while_the_job_runs(review):
    class Live(FakeHttp):
        """The job reports one answer while still running, then finishes."""

        statuses = iter(["running", "done"])

        def request(self, method, path, **kwargs):
            response = super().request(method, path, **kwargs)
            if path.endswith("/jobs"):
                response.body["created_at"] = "2026-01-01T00:00:00+00:00"
            elif path.endswith("/results"):
                self.results_while.append(self.state)
                for paper in response.body["papers"]:
                    for a in paper["annotations"]:
                        a["created_at"] = "2026-01-01T00:00:01+00:00"
            elif "/jobs/" in path:
                self.state = next(self.statuses)
                response.body["status"] = self.state
            return response

    campaign = campaigns.create(review.folder, "models", paper_type="surveys")
    http = Live()
    http.results_while, http.state = [], ""
    client = llm_annotator.Client("http://x", http=http)
    report = llm_annotator.run_campaign(
        review, campaign, "m2", "http://x", client=client, poll=0
    )
    assert http.results_while == ["running", "done"]  # imported before the end
    assert report.proposals == 1 and report.answers == 1  # not imported twice
    stored = llm_annotator.answers(review, campaign.id)
    assert len(stored) == 1 and tags_of(review)["Gamma"].count("TASK-AUTO:X") == 1


def test_store_signature_changes_on_import(review):
    campaign = campaigns.create(review.folder, "models", paper_type="surveys")
    before = llm_annotator.store_signature(review)
    llm_annotator.run_campaign(
        review,
        campaign,
        "m2",
        "http://x",
        client=llm_annotator.Client("http://x", http=FakeHttp()),
        poll=0,
    )
    assert llm_annotator.store_signature(review) != before


def test_client_reports_service_errors():
    class Down:
        def request(self, *a, **k):
            raise OSError("refused")

    with pytest.raises(llm_annotator.AnnotatorError, match="scilex-annotator api"):
        llm_annotator.Client("http://x", http=Down()).health()


@pytest.mark.anyio
async def test_annotate_page_guideline_campaign_and_validation(review, ctx):
    from nicegui.testing import user_simulation

    from scilex.gui.app import build_root

    campaign = campaigns.create(
        review.folder, "datasets", paper_type="datasets", llm_models=["m1"]
    )
    data = read_results(review.results_path)
    _, keys = llm_annotator.bibtex_for(data, list(data.index))
    llm_annotator.import_results(
        review,
        campaign,
        {
            "job": {"model": "m1"},
            "papers": [{"key": "AAAA1111", "annotations": [answer("TASK", ["RC"])]}],
        },
        keys,
    )

    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/annotate")
        await user.should_see(marker="guideline-card", retries=20)
        user.find(marker="guideline-editor").type("## TASK\nThe task.")
        user.find(marker="guideline-save").click()
        await user.should_see("Guideline saved", retries=20)

        user.find(marker="annotate-tab-campaigns").click()
        await user.should_see(marker="campaign-datasets", retries=20)
        await user.should_see("1 LLM proposals to validate", retries=20)

        user.find(marker="annotate-tab-validate").click()
        await user.should_see("1 proposals shown (1 pending).", retries=20)
        await user.should_see("“q”")
        user.find(marker="validate-accept").click()
        await user.should_see("No proposal to validate.", retries=20)

    assert annotations.load_guideline_text(review).startswith("## TASK")
    assert "TASK:RC" in tags_of(review)["Alpha"].split(";")
    assert llm_annotator.decisions(review)[-1]["outcome"] == "accepted"
