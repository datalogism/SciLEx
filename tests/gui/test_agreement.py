"""Cross-annotation study in Zotero (in-memory Zotero)."""

import copy

import pandas as pd
import pytest

from scilex.gui.services import agreement
from scilex.gui.services import zotero_library as zl


class _Response:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeZotero:
    """Collections, items, item creation and tag updates."""

    _count_outcome = staticmethod(
        lambda response, batch: {"success": len(batch), "failed": 0}
    )

    def __init__(self):
        self.collections = {"MODELS": {"name": "models", "parentCollection": False}}
        self.items = {}
        self.counter = 0

    def add(self, key, title, tags, collections=("MODELS",)):
        self.items[key] = {
            "key": key,
            "version": 1,
            "data": {
                "key": key,
                "itemType": "journalArticle",
                "title": title,
                "collections": list(collections),
                "tags": [{"tag": t} for t in tags],
            },
        }

    def get_collections(self):
        return [{"key": k, "data": dict(v)} for k, v in self.collections.items()]

    def get_top_items(self, collection=None):
        return [
            copy.deepcopy(i)
            for i in self.items.values()
            if collection is None or collection in i["data"]["collections"]
        ]

    def _get(self, path, params=None):
        return _Response(copy.deepcopy(self.items[path.split("/")[-1]]))

    def _post(self, path, batch):
        successful = {}
        for index, entry in enumerate(batch):
            self.counter += 1
            key = f"NEW{self.counter}"
            if path == "/collections":
                self.collections[key] = {
                    "name": entry["name"],
                    "parentCollection": entry.get("parentCollection", False),
                }
            else:
                self.items[key] = {
                    "key": key,
                    "version": 1,
                    "data": {**entry, "key": key},
                }
            successful[str(index)] = {"key": key}
        return _Response({"successful": successful})

    def update_item_tags(self, updates):
        for key, (_version, tags) in updates.items():
            self.items[key]["data"]["tags"] = [{"tag": t} for t in tags]
        return {"success": len(updates), "failed": 0}


@pytest.fixture
def zotero(monkeypatch):
    fake = FakeZotero()
    fake.add("REF1", "REBEL", ["TASK:?", "GRANULARITY:?", "ANNOT:ann", "ANNOT:bob"])
    fake.add(
        "REF2", "DocRED", ["TASK:RE", "ANNOT:ann", "ANNOT:bob", "ANNOT_VALID_BY:ann"]
    )
    monkeypatch.setattr(agreement, "_api", lambda review: fake)
    return fake


def test_plan_copies_needs_two_annotators():
    data = pd.DataFrame(
        {
            "zotero_key": ["A", "B", "C", "NA"],
            "tags": [
                "ANNOT:x;ANNOT:y",
                "ANNOT:x",
                "ANNOT:x;ANNOT:y;DELETED_BY:me",
                "ANNOT:x;ANNOT:y",
            ],
        }
    )
    assert agreement.plan_copies(data) == {"A": ["x", "y"]}


def test_study_copies_compute_and_merge(zotero):
    review = object()
    report = agreement.create_copies(
        review, {"REF1": ["ann", "bob"], "REF2": ["ann", "bob"]}
    )
    assert report.created == 4
    # Copies: blind (no codes, placeholders kept), under agreement/<annotator>.
    copies = [i for i in zotero.items.values() if zl.is_agreement_copy(i)]
    assert len(copies) == 4
    docred_copy = next(c for c in copies if "AGREEMENT_COPY:REF2" in str(c))
    tags = {t["tag"] for t in docred_copy["data"]["tags"]}
    assert "TASK:RE" not in tags and "ANNOT_VALID_BY:ann" not in tags
    names = {c["name"] for c in zotero.collections.values()}
    assert {"agreement", "ann", "bob"} <= names
    # A second run creates nothing.
    assert agreement.create_copies(review, {"REF1": ["ann", "bob"]}).existing == 2

    # Annotators code their copies.
    for item in copies:
        who = next(
            t["tag"][6:] for t in item["data"]["tags"] if t["tag"].startswith("ANNOT:")
        )
        ref = next(
            t["tag"].split(":")[1]
            for t in item["data"]["tags"]
            if t["tag"].startswith("AGREEMENT_COPY:")
        )
        codes = {
            "ann": ["TASK:RE", "GRANULARITY:Sentence"],
            "bob": ["TASK:RE", "GRANULARITY:Document"],
        }[who]
        zotero.items[item["key"]]["data"]["tags"] += [{"tag": c} for c in codes]
        assert ref in ("REF1", "REF2")

    result, studied = agreement.compute(review)
    by_dim = {d.dimension: d for d in result.dimensions}
    assert result.papers == 2 and result.annotators == ["ann", "bob"]
    assert by_dim["TASK"].alpha == 1.0
    assert by_dim["GRANULARITY"].level == "poor"

    merged = agreement.merge(review, studied)
    assert merged.papers == 1  # DocRED already had TASK:RE: nothing to write
    ref1 = {t["tag"] for t in zotero.items["REF1"]["data"]["tags"]}
    assert (
        "TASK:RE" in ref1 and "TASK:?" not in ref1
    )  # placeholder of a coded dimension removed
    assert "GRANULARITY:?" in ref1  # disputed: left to adjudicate
    assert set(merged.disputed["REF1"]) == {
        "GRANULARITY:Document",
        "GRANULARITY:Sentence",
    }


def test_copies_are_not_papers(zotero):
    agreement.create_copies(object(), {"REF1": ["ann", "bob"]})
    papers = zl.fetch_papers(zotero, None)
    assert {p["key"] for p in papers} == {"REF1", "REF2"}


@pytest.mark.anyio
async def test_card_computes_alpha(ctx, tmp_path, zotero):
    from nicegui.testing import user_simulation

    from scilex.gui.app import build_root

    review = ctx.workspace.create_review(tmp_path / "ag", name="ag_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "title": ["REBEL"],
            "itemType": ["journalArticle"],
            "date": ["2021"],
            "zotero_key": ["REF1"],
            "tags": ["ANNOT:ann;ANNOT:bob"],
        }
    ).to_csv(review.results_path, sep=";")
    agreement.create_copies(review, {"REF1": ["ann", "bob"]})
    for item in zotero.items.values():
        if zl.is_agreement_copy(item):
            item["data"]["tags"].append({"tag": "TASK:RE"})
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/annotate")
        await user.should_see(marker="agreement-card", retries=20)
        await user.should_see("1 papers with two annotators or more (2 copies).")
        user.find(marker="agreement-compute").click()
        await user.should_see(marker="agreement-table", retries=20)
        table = user.find(marker="agreement-table").elements.pop()
        rows = {row["dimension"]: row for row in table.rows}
        assert rows["TASK"] == {
            "dimension": "TASK",
            "alpha": "1.00",
            "level": "good",
            "papers": 1,
        }
        assert rows["GRANULARITY"]["level"] == "n/a"  # only placeholders so far


def test_kg_export_drops_discarded_papers_and_copies():
    bib = (
        "@article{rebel2021,\n  title = {REBEL},\n  keywords = {TASK:RE, LANG:English},\n}\n\n"
        "@article{old2015,\n  title = {Old},\n  keywords = {DELETED_BY:filter:year 2015},\n}\n\n"
        "@inproceedings{rebel2021a,\n  title = {REBEL},\n"
        "  keywords = {ANNOT:ann, AGREEMENT_COPY:REF1},\n}\n"
    )
    text, dropped = zl.drop_excluded_entries(bib)
    assert dropped == {"old2015", "rebel2021a"}
    assert text == bib.split("@article{old2015")[0]
    assert zl.drop_excluded_entries("no entry") == ("no entry", set())
