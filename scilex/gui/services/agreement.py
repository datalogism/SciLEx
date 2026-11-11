"""Cross-annotation study in Zotero: one copy of a paper per annotator.

Zotero does not record who added a tag, so each annotator of a cross-annotated
paper codes their own copy of it:

1. :func:`create_copies` — for every paper of the review assigned to two or
   more annotators (``ANNOT:<id>`` tags), copy its Zotero item into the
   collection ``agreement/<id>`` of each of them. The copy keeps the
   bibliographic data and the ``DIMENSION:?`` placeholders but not the codes
   (blind annotation); it carries ``ANNOT:<id>`` and ``AGREEMENT_COPY:<key of
   the reference item>``. Copies are never taken for papers of the review.
2. Annotators code their copies in Zotero, with normal ``DIMENSION:value`` tags.
3. :func:`read_copies` / :func:`compute` — Krippendorff's alpha (MASI) per
   dimension (:mod:`scilex.annotation_agreement`).
4. :func:`merge` — write on each reference item the codes every annotator gave
   and, optionally, those a majority gave; the others are listed to adjudicate.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

import pandas as pd

from scilex import annotation_agreement, review_tags
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

ROOT = "agreement"
BATCH = 50
DROP_FIELDS = ("key", "version", "dateAdded", "dateModified")


def copy_tag(item_key: str) -> str:
    return f"{review_tags.AGREEMENT_COPY}:{item_key}"


def _api(review: Review):
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None:
        raise ValueError("The review has no Zotero library: link it first (⑧ Export).")
    return zotero_library.client(effective_keys(review.folder), library=source)


# -- 1. copies ------------------------------------------------------------------


def plan_copies(data: pd.DataFrame) -> dict[str, list[str]]:
    """``{reference item key: [annotators]}`` for papers with two annotators or more."""
    plan: dict[str, list[str]] = {}
    keys = data.get("zotero_key", pd.Series("", index=data.index))
    tags = data.get("tags", pd.Series("", index=data.index))
    for index in data.index:
        state = review_tags.workflow(tags[index])
        key = str(keys[index]).strip() if pd.notna(keys[index]) else ""
        if (
            key
            and key.upper() != "NA"
            and not state.deleted
            and len(state.assigned) >= 2
        ):
            plan[key] = list(state.assigned)
    return plan


def _collections(api) -> tuple[str | None, dict[str, str]]:
    """Key of the ``agreement`` collection and ``{annotator: sub-collection key}``."""
    raw = api.get_collections() or []
    root = next(
        (
            c["key"]
            for c in raw
            if c["data"]["name"] == ROOT and not c["data"].get("parentCollection")
        ),
        None,
    )
    children = {
        c["data"]["name"]: c["key"]
        for c in raw
        if root and c["data"].get("parentCollection") == root
    }
    return root, children


def _create_collection(api, name: str, parent: str | None = None) -> str:
    entry = {"name": name}
    if parent:
        entry["parentCollection"] = parent
    response = api._post("/collections", [entry])
    if response is None:
        raise ConnectionError(f"Cannot create the Zotero collection '{name}'.")
    created = response.json().get("successful", {}).get("0")
    if not created:
        raise ConnectionError(f"Zotero refused to create the collection '{name}'.")
    return created["key"]


def _copy_of(item: dict, annotator: str, collection: str) -> dict:
    """The new item: bibliographic data, placeholders, ANNOT and AGREEMENT_COPY."""
    data = copy.deepcopy(item["data"])
    for name in DROP_FIELDS:
        data.pop(name, None)
    data["collections"] = [collection]
    data["relations"] = {}
    kept = []
    for tag in data.get("tags", []):
        text = str(tag.get("tag", ""))
        dimension, sep, value = text.partition(":")
        if review_tags.is_workflow_tag(text):
            continue  # assignment, validation… belong to the reference paper
        if sep and value.strip() and value.strip() != annotation_agreement.PLACEHOLDER:
            continue  # a code: the copy starts blind
        kept.append({"tag": text})
    kept.append({"tag": review_tags.tag(review_tags.ASSIGNED, annotator)})
    kept.append({"tag": copy_tag(item["key"])})
    data["tags"] = kept
    return data


@dataclass
class CopyReport:
    created: int = 0
    existing: int = 0
    failed: int = 0
    papers: int = 0

    def message(self) -> str:
        text = f"{self.created} copies created for {self.papers} cross-annotated papers"
        if self.existing:
            text += f" ({self.existing} already there)"
        if self.failed:
            text += f", {self.failed} failed"
        return text + "."


def create_copies(review: Review, plan: dict[str, list[str]]) -> CopyReport:
    """Create the missing copies of ``plan`` in ``agreement/<annotator>``."""
    api = _api(review)
    report = CopyReport(papers=len(plan))
    root, children = _collections(api)
    if root is None:
        root = _create_collection(api, ROOT)
    existing = read_copies(review, api=api)
    batch: list[dict] = []

    def flush() -> None:
        if not batch:
            return
        response = api._post("/items", list(batch))
        if response is None:
            report.failed += len(batch)
        else:
            outcome = api._count_outcome(response, batch)
            report.created += outcome["success"]
            report.failed += outcome["failed"]
        batch.clear()

    for item_key, annotators in plan.items():
        response = api._get(f"/items/{item_key}")
        if response is None:
            report.failed += len(annotators)
            continue
        item = response.json()
        for annotator in annotators:
            if annotator in existing.get(item_key, {}):
                report.existing += 1
                continue
            if annotator not in children:
                children[annotator] = _create_collection(api, annotator, root)
            batch.append(_copy_of(item, annotator, children[annotator]))
            if len(batch) >= BATCH:
                flush()
    flush()
    return report


# -- 2-3. reading and agreement -------------------------------------------------


def read_copies(review: Review, *, api=None) -> dict[str, dict[str, list[str]]]:
    """``{reference item key: {annotator: tags of their copy}}``."""
    api = api or _api(review)
    _, children = _collections(api)
    copies: dict[str, dict[str, list[str]]] = {}
    for annotator, collection in children.items():
        for item in api.get_top_items(collection) or []:
            tags = [str(t.get("tag", "")) for t in item.get("data", {}).get("tags", [])]
            reference = next(
                (
                    t.split(":", 1)[1]
                    for t in tags
                    if t.startswith(f"{review_tags.AGREEMENT_COPY}:")
                ),
                None,
            )
            if reference:
                copies.setdefault(reference, {})[annotator] = tags
    return copies


@dataclass
class AgreementReport:
    dimensions: list[annotation_agreement.DimensionAgreement]
    papers: int  # reference papers with at least two copies
    annotators: list[str] = field(default_factory=list)


def compute(review: Review) -> tuple[AgreementReport, dict]:
    """Agreement per dimension of the review's study, and the copies read."""
    copies = read_copies(review)
    studied = {key: by_coder for key, by_coder in copies.items() if len(by_coder) >= 2}
    annotators = sorted({who for by_coder in studied.values() for who in by_coder})
    return (
        AgreementReport(
            dimensions=annotation_agreement.by_dimension(studied),
            papers=len(studied),
            annotators=annotators,
        ),
        studied,
    )


# -- 4. merge -------------------------------------------------------------------


@dataclass
class MergeReport:
    papers: int = 0
    codes: int = 0
    failed: int = 0
    disputed: dict[str, list[str]] = field(default_factory=dict)  # item key -> codes

    def message(self) -> str:
        text = f"{self.codes} codes written on {self.papers} reference papers"
        if self.failed:
            text += f" ({self.failed} papers edited meanwhile in Zotero: compute again)"
        disputed = sum(len(v) for v in self.disputed.values())
        if disputed:
            text += f"; {disputed} disputed codes on {len(self.disputed)} papers to adjudicate"
        return text + "."


def merge(review: Review, copies: dict, *, with_majority: bool = True) -> MergeReport:
    """Write the agreed (and majority) codes on the reference items in Zotero.

    Placeholders ``DIMENSION:?`` of the dimensions now coded are removed;
    existing codes of the reference item are kept.
    """
    api = _api(review)
    report = MergeReport()
    updates: dict[str, tuple[int, list[str]]] = {}
    for item_key, by_coder in copies.items():
        proposal = annotation_agreement.merge_proposal(by_coder)
        new_codes = proposal.agreed + (proposal.majority if with_majority else [])
        if proposal.disputed or (not with_majority and proposal.majority):
            report.disputed[item_key] = proposal.disputed + (
                [] if with_majority else proposal.majority
            )
        if not new_codes:
            continue
        response = api._get(f"/items/{item_key}")
        if response is None:
            report.failed += 1
            continue
        item = response.json()
        tags = [str(t.get("tag", "")) for t in item["data"].get("tags", [])]
        coded = {code.split(":", 1)[0].upper() for code in new_codes}
        kept = [
            t
            for t in tags
            if not (
                t.endswith(":" + annotation_agreement.PLACEHOLDER)
                and t.split(":", 1)[0].upper() in coded
            )
        ]
        merged = kept + [code for code in new_codes if code not in kept]
        if merged != tags:
            updates[item_key] = (item["version"], merged)
            report.codes += len([c for c in new_codes if c not in tags])
    if updates:
        outcome = api.update_item_tags(updates)
        report.papers = outcome["success"]
        report.failed += outcome["failed"]
    return report
