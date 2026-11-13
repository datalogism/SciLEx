"""Saved versions of scilex.yml and criteria.yml (SX-7, SX-8)."""

import pandas as pd
import yaml

from scilex.gui.services import config_editor, journal, versions
from scilex.gui.services import criteria as cr
from scilex.gui.services.extend import write_results

MAIN = {"years": [2019, 2020, 2021], "keywords": [["survey"], ["question answering"]]}


def frame():
    return pd.DataFrame(
        [
            {
                "title": "A survey of question answering",
                "abstract": "",
                "date": "2020",
                "DOI": "10.1/a",
                "itemType": "journalArticle",
            },
            {
                "title": "Old survey of question answering",
                "abstract": "",
                "date": "2010",
                "DOI": "10.1/c",
                "itemType": "journalArticle",
            },
        ]
    )


def test_two_config_saves_give_two_versions_and_jobs_point_to_one(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    data = config_editor.load_editable(review)
    config_editor.save(review, data)
    data["search"]["years"] = [2020, 2021]
    config_editor.save(review, data)
    saved = versions.load_versions(review.folder, versions.CONFIG)
    assert len(saved) >= 2
    latest = versions.current_hash(review.folder, versions.CONFIG)
    assert latest in {v["sha256"] for v in saved}
    body = next(v for v in saved if v["sha256"] == latest)
    rows = {r["path"]: r for r in body["values"]}
    assert rows["search.years"]["value"] == [2020, 2021]
    assert rows["search.years"]["default"] is False
    assert any(r["default"] for r in body["values"])  # defaults are flagged
    text = yaml.safe_dump(saved)
    assert "api_key" not in text and "output_dir" not in text
    # the configure events carry the hash of the saved version
    hashes = [
        e["generated"].get("scilex.yml sha256")
        for e in journal.load(review.folder)
        if e["activity"] == "configure"
    ]
    assert hashes[-1] == latest


def test_exclusions_point_to_the_criteria_version_applied(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(frame(), review.results_path)
    items = cr.defaults(MAIN)
    cr.save(review.folder, items)
    first = versions.current_hash(review.folder, versions.CRITERIA)
    cr.apply(review, items)
    items[0].enabled = False
    cr.save(review.folder, items)
    second = versions.current_hash(review.folder, versions.CRITERIA)
    cr.apply(review, items)
    assert first != second
    applied = [
        e["used"].get("criteria.yml sha256")
        for e in journal.load(review.folder)
        if e["activity"] == "criteria"
    ]
    assert applied[-2:] == [first, second]
    saved = {v["sha256"]: v for v in versions.load_versions(review.folder, "criteria")}
    assert saved[first]["criteria"][0]["enabled"] is True
    assert saved[second]["criteria"][0]["enabled"] is False
