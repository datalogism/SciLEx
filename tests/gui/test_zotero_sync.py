"""Two-way Zotero sync and its icon, against an in-memory Zotero (no network)."""

import copy

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import screening
from scilex.gui.services import zotero_sync as sync
from scilex.gui.services.extend import read_results, write_results
from scilex.Zotero.zotero_api import ZoteroAPI

pytestmark = pytest.mark.anyio
COLLECTION = "COLL"


class _Response:
    def __init__(self, body, version):
        self._body = body
        self.headers = {"Last-Modified-Version": str(version)}

    def json(self):
        return self._body


class FakeZotero:
    """Versions, ``since`` queries, partial writes with version checks, deletions."""

    _count_outcome = staticmethod(ZoteroAPI._count_outcome)

    def __init__(self):
        self.version = 10
        self.items: dict[str, dict] = {}
        self.deleted: dict[str, int] = {}

    def add(self, key, title, doi="", tags=(), collections=(COLLECTION,), **fields):
        self.version += 1
        self.items[key] = {
            "key": key,
            "version": self.version,
            "data": {
                "key": key, "itemType": "journalArticle", "title": title, "DOI": doi,
                "date": "2021", "abstractNote": "", "url": "", "collections": list(collections),
                "tags": [{"tag": t} for t in tags], **fields,
            },
        }

    def edit(self, key, tags=None, **fields):
        self.version += 1
        data = self.items[key]["data"]
        data.update(fields)
        if tags is not None:
            data["tags"] = [{"tag": t} for t in tags]
        self.items[key]["version"] = self.version

    def tags(self, key):
        return sorted(t["tag"] for t in self.items[key]["data"]["tags"])

    def _get(self, path, params=None):
        params = params or {}
        if path == "/items/top" and "since" in params:
            body = {k: i["version"] for k, i in self.items.items() if i["version"] > params["since"]}
        elif path == "/items/top":
            body = []
        elif path == "/deleted":
            body = {"items": [k for k, v in self.deleted.items() if v > params["since"]]}
        elif path == "/items":
            keys = params["itemKey"].split(",")
            body = [copy.deepcopy(self.items[k]) for k in keys if k in self.items]
        else:
            raise AssertionError(path)
        return _Response(body, self.version)

    def _post(self, path, batch):
        successful, failed = {}, {}
        for index, entry in enumerate(batch):
            item = self.items[entry["key"]]
            if entry["version"] != item["version"]:
                failed[str(index)] = {"message": "version mismatch"}
                continue
            self.version += 1
            item["data"].update({k: v for k, v in entry.items() if k not in ("key", "version")})
            item["version"] = self.version
            successful[str(index)] = item
        return _Response({"successful": successful, "failed": failed}, self.version)


@pytest.fixture
def zotero(monkeypatch):
    fake = FakeZotero()
    fake.add("K1", "Graph RAG", doi="10.1/a", tags=["Tool:Blender"])
    fake.add("K2", "Knowledge graphs", doi="10.1/b")
    monkeypatch.setattr(sync, "_api", lambda review: (fake, None))
    monkeypatch.setattr(
        sync, "_fetch_all", lambda review, api, source: (copy.deepcopy(list(fake.items.values())), [COLLECTION])
    )
    return fake


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rev", name="rev")
    review.collection_dir.mkdir(parents=True)
    write_results(
        pd.DataFrame(
            [
                {"itemType": "journalArticle", "title": "Graph RAG", "DOI": "10.1/a", "date": "2021", "abstract": "NA", "tags": "Tool:Blender"},
                {"itemType": "journalArticle", "title": "Knowledge graphs", "DOI": "10.1/b", "date": "2021", "abstract": "NA", "tags": "NA"},
                {"itemType": "journalArticle", "title": "Only in SciLEx", "DOI": "10.1/c", "date": "2022", "abstract": "NA", "tags": "NA"},
            ]
        ),
        review.results_path,
    )
    return review


def _rows(review):
    data = read_results(review.results_path)
    return {r["title"]: r for r in data.to_dict("records")}


def test_link_gives_each_copy_of_a_paper_its_own_item(review, zotero):
    # Same paper annotated twice on purpose: once as a model, once as a dataset.
    zotero.add("KM", "DocRED", doi="10.1/docred")
    zotero.add("KD", "DocRED", doi="10.1/docred")
    zotero.items["KM"]["_scilex_collections"] = ["models"]
    zotero.items["KD"]["_scilex_collections"] = ["datasets"]
    data = read_results(review.results_path)
    copies = pd.DataFrame(
        [
            {"itemType": "journalArticle", "title": "DocRED", "DOI": "10.1/docred", "date": "2019", "zotero_collections": corpus}
            for corpus in ("datasets", "models")
        ]
    )
    write_results(pd.concat([data, copies], ignore_index=True), review.results_path)

    assert sync.link(review)["linked"] == 4
    keys = {r["zotero_collections"]: r["zotero_key"] for r in read_results(review.results_path).to_dict("records") if r["title"] == "DocRED"}
    assert keys == {"datasets": "KD", "models": "KM"}


def test_link_prefers_required_subcorpora_over_import_copies(review, zotero):
    # A Zotero file import duplicated the "datasets" items into a stamped collection.
    zotero.add("KCOPY", "DocRED", doi="10.1/docred")
    zotero.add("KREAL", "DocRED", doi="10.1/docred")
    zotero.items["KCOPY"]["_scilex_collections"] = ["datasets 10/11/2026 15:35:35"]
    zotero.items["KREAL"]["_scilex_collections"] = ["datasets"]
    data = read_results(review.results_path)
    row = pd.DataFrame([{"itemType": "journalArticle", "title": "DocRED", "DOI": "10.1/docred", "date": "2019", "zotero_key": "KCOPY"}])
    write_results(pd.concat([data, row], ignore_index=True), review.results_path)

    sync.link(review, required=["datasets", "models", "surveys"])
    docred = _rows(review)["DocRED"]
    assert docred["zotero_key"] == "KREAL"
    assert docred["zotero_collections"] == "datasets"


def test_link_matches_by_doi_and_starts_in_sync(review, zotero):
    assert sync.check(review).state == "unlinked"
    result = sync.link(review)
    assert result == {"linked": 2, "papers": 3, "zotero": 2}
    rows = _rows(review)
    assert rows["Graph RAG"]["zotero_key"] == "K1"
    status = sync.check(review)
    assert status.state == "synced"
    assert status.local_unlinked == 1


def test_zotero_changes_are_pulled(review, zotero):
    sync.link(review)
    zotero.edit("K1", tags=["Tool:Blender", "Onto:CIDOC-CRM"], abstractNote="New abstract")
    status = sync.check(review)
    assert status.state == "pull" and status.zotero_count == 1
    assert status.zotero_changed[0].added == {"Onto:CIDOC-CRM"}
    sync.pull(review, status)
    row = _rows(review)["Graph RAG"]
    assert row["abstract"] == "New abstract"
    assert set(row["tags"].split(";")) == {"Tool:Blender", "Onto:CIDOC-CRM"}
    assert sync.check(review).state == "synced"


def test_screening_and_enrichment_are_pushed(review, zotero):
    sync.link(review)
    row = _rows(review)["Knowledge graphs"]
    screening.set_decision(review, screening.paper_key(row), screening.INCLUDE)
    data = read_results(review.results_path)
    data.loc[data["title"] == "Knowledge graphs", "abstract"] = "Filled by Crossref"
    write_results(data, review.results_path)
    status = sync.check(review)
    assert status.state == "push" and status.local_count == 1
    assert sync.push(review, status) == {"success": 1, "failed": 0}
    assert "SCREEN:Include" in zotero.tags("K2")
    assert zotero.items["K2"]["data"]["abstractNote"] == "Filled by Crossref"
    assert sync.check(review).state == "synced"


def test_both_sides_and_conflict_resolution(review, zotero):
    sync.link(review)
    zotero.edit("K1", title="Graph RAG (Zotero)")
    data = read_results(review.results_path)
    data.loc[data["title"] == "Graph RAG", "title"] = "Graph RAG (SciLEx)"
    write_results(data, review.results_path)
    status = sync.check(review)
    assert status.state == "conflict"
    conflict = status.conflicts[0]
    assert (conflict.what, conflict.local, conflict.zotero) == (
        "title", "Graph RAG (SciLEx)", "Graph RAG (Zotero)"
    )
    sync.resolve(review, conflict, "zotero")
    assert "Graph RAG (Zotero)" in _rows(review)
    assert sync.check(review).state == "synced"


def test_keep_scilex_pushes_the_local_value(review, zotero):
    sync.link(review)
    zotero.edit("K1", title="Zotero title")
    data = read_results(review.results_path)
    data.loc[data["title"] == "Graph RAG", "title"] = "SciLEx title"
    write_results(data, review.results_path)
    conflict = sync.check(review).conflicts[0]
    sync.resolve(review, conflict, "scilex")
    status = sync.check(review)
    assert status.state == "push"
    sync.push(review, status)
    assert zotero.items["K1"]["data"]["title"] == "SciLEx title"
    assert sync.check(review).state == "synced"


def test_tags_merge_from_both_sides(review, zotero):
    sync.link(review)
    zotero.edit("K1", tags=["Tool:Blender", "Step:3"])
    data = read_results(review.results_path)
    data.loc[data["title"] == "Graph RAG", "tags"] = "Tool:Blender;Onto:PROV-O"
    write_results(data, review.results_path)
    status = sync.check(review)
    assert status.state == "both" and not status.conflicts
    sync.pull(review, status)
    status = sync.check(review)
    assert status.state == "push"
    sync.push(review, status)
    assert zotero.tags("K1") == ["Onto:PROV-O", "Step:3", "Tool:Blender"]
    assert set(_rows(review)["Graph RAG"]["tags"].split(";")) == {"Tool:Blender", "Step:3", "Onto:PROV-O"}
    assert sync.check(review).state == "synced"


def test_new_zotero_papers_and_screen_tags_are_pulled(review, zotero):
    sync.link(review)
    zotero.add("K3", "Added in Zotero", doi="10.1/z", tags=["SCREEN:Exclude"])
    zotero.add("K9", "Other collection", collections=("OTHER",))
    status = sync.check(review)
    assert [i["key"] for i in status.zotero_new] == ["K3"]
    sync.pull(review, status)
    row = _rows(review)["Added in Zotero"]
    assert row["zotero_key"] == "K3"
    decision = screening.load_decisions(review)[screening.paper_key(row)]
    assert decision.decision == screening.EXCLUDE
    assert sync.check(review).state == "synced"


def test_removed_in_zotero_is_reported_not_deleted(review, zotero):
    sync.link(review)
    zotero.version += 1
    zotero.deleted["K2"] = zotero.version
    del zotero.items["K2"]
    status = sync.check(review)
    assert status.zotero_removed == ["K2"]
    sync.pull(review, status)
    assert "Knowledge graphs" in _rows(review)


def test_no_zotero_collection_is_an_error_state(review, monkeypatch):
    sync.forget_cache(review)
    status = sync.cached_check(review, force=True)
    assert status.state == "error"
    assert "Not linked to Zotero" in status.error


async def test_icon_shows_the_state(ctx, review, monkeypatch):
    status = sync.SyncStatus(
        linked=2,
        zotero_changed=[sync.Change("K1", "Graph RAG", added={"Onto:X"})],
        local_changed=[sync.Change("K2", "Knowledge graphs", added={"SCREEN:Include"})],
    )
    monkeypatch.setattr(sync, "cached_check", lambda review, force=False: status)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/overview")
        await user.should_see(marker="sync-state-both", retries=50)
        await user.should_see("↓1 ↑1")
        user.find(marker="sync-badge").click()
        await user.should_see(marker="sync-dialog")
        await user.should_see("Get Zotero updates")
        await user.should_see("Push to Zotero")
