"""PRISMA flow of a review: every action that brought, removed or enriched papers.

Built from what the review already records, no network:

- **Identification**: the collect of ``scilex.yml`` (APIs, keywords, years)
  and its raw count (``filtering_summary.json`` / ``aggregation_stats.csv``),
  plus the records from other sources: extensions (new collect, snowballing,
  BibTeX, Zotero), from the journal and the ``extension_origin`` column;
- **Screening**: the duplicates and each automatic filter of the aggregation
  (``filtering_summary.json`` stages), the papers discarded by a rule or a
  person (``DELETED_BY:`` tags), and the screening decisions;
- **Included**: the papers included in ③ Screen (and those still undecided);
- **Enrichment**: the enrichments run on the corpus (journal), beside the flow.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from scilex import review_tags
from scilex.constants import is_valid

logger = logging.getLogger(__name__)


@dataclass
class Box:
    """One box of the diagram: a count and its explanation lines."""

    title: str
    count: int | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class Prisma:
    """The boxes of the flow, by PRISMA phase."""

    identification: Box = field(default_factory=lambda: Box("Records identified"))
    other_sources: Box = field(default_factory=lambda: Box("Records from extensions"))
    removed_before: Box = field(
        default_factory=lambda: Box("Records removed before screening")
    )
    screened: Box = field(default_factory=lambda: Box("Records screened"))
    excluded: Box = field(default_factory=lambda: Box("Records excluded"))
    included: Box = field(default_factory=lambda: Box("Studies included"))
    pending: Box = field(default_factory=lambda: Box("Still to screen"))
    enrichment: Box = field(default_factory=lambda: Box("Enrichments"))

    @property
    def empty(self) -> bool:
        return not (self.identification.count or self.screened.count)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _origin_kind(origin: str) -> str:
    text = origin.strip().lower()
    for prefix, label in (
        ("query", "new collect"),
        ("bibtex", "BibTeX"),
        ("zotero", "Zotero"),
        ("snowball", "snowballing"),
    ):
        if text.startswith(prefix):
            return label
    return text.split(" ")[0] if text else "other"


def _identification(box: Box, main: dict | None, filtering: dict) -> None:
    box.count = filtering.get("initial_count") or None
    if not main:
        return
    apis = main.get("apis") or []
    if apis:
        box.lines.append("Databases: " + ", ".join(map(str, apis)))
    keywords = main.get("keywords") or []
    groups = [
        " OR ".join(map(str, group)) if isinstance(group, list) else str(group)
        for group in keywords
    ]
    if groups:
        box.lines.append("Keywords: " + " AND ".join(f"({g})" for g in groups if g))
    years = main.get("years") or []
    if years:
        years = sorted(int(y) for y in years if str(y).isdigit())
        if years:
            box.lines.append(f"Years: {years[0]}–{years[-1]}")


def compute(review, main: dict | None = None) -> Prisma:
    """The PRISMA flow of ``review`` (``main``: its scilex.yml, if readable)."""
    from scilex.gui.services import provenance, screening

    flow = Prisma()
    folder = review.collection_dir
    filtering = _read_json(folder / "filtering_summary.json")
    _identification(flow.identification, main, filtering)

    # Automatic steps of the aggregation: duplicates, filters (not the ranking).
    stages = filtering.get("stages") or []
    removed_total = 0
    for stage in stages[1:]:
        removed = int(stage.get("removed") or 0)
        if removed > 0:
            removed_total += removed
            flow.removed_before.lines.append(f"{stage.get('stage')}: {removed}")
    flow.removed_before.count = removed_total if stages else None

    card = provenance.review_card(review.folder)
    if flow.identification.count is None and card.origin_label:
        flow.identification.lines.insert(0, f"Origin: {card.origin_label}")

    if not review.has_results:
        return flow
    data = screening.load_results(review)
    rows = data.to_dict("records")

    # Records from other sources: what each kind of extension brought.
    origins = Counter(
        _origin_kind(str(row.get("extension_origin")))
        for row in rows
        if is_valid(row.get("extension_origin"))
        and str(row.get("extension_origin")).strip()
    )
    flow.other_sources.count = sum(origins.values())
    for kind, count in origins.most_common():
        flow.other_sources.lines.append(f"{kind}: {count} papers in the review")
    runs = Counter(step.what for step in card.extensions if step.status == "completed")
    for what, count in runs.most_common():
        flow.other_sources.lines.append(f"{what}: {count} run(s)")
    if flow.identification.count is None:
        flow.identification.count = len(rows) - flow.other_sources.count

    # Discarded papers (rules and people) and screening decisions.
    discarded: Counter = Counter()
    kept_keys = []
    for row in rows:
        tags = review_tags.split_tags(row.get("tags"))
        reason = next(
            (
                t[len(review_tags.DELETED) + 1 :]
                for t in tags
                if t.startswith(review_tags.DELETED + ":")
            ),
            None,
        )
        if reason is None:
            kept_keys.append(row["paper_key"])
        else:
            discarded[
                "by a filter" if reason.startswith("filter:") else "by a person"
            ] += 1
    decisions = screening.load_decisions(review)
    counts = Counter(
        decisions[key].decision if key in decisions else "undecided"
        for key in kept_keys
    )
    flow.screened.count = len(rows)
    flow.screened.lines.append(f"{len(kept_keys)} kept in the corpus")
    excluded = counts.get(screening.EXCLUDE, 0)
    flow.excluded.count = excluded + sum(discarded.values())
    if excluded:
        flow.excluded.lines.append(f"excluded in ③ Screen: {excluded}")
    if discarded.get("by a person"):
        flow.excluded.lines.append(
            f"discarded by a person (DELETED_BY): {discarded['by a person']}"
        )
    if discarded.get("by a filter"):
        from scilex.gui.services import criteria

        per = criteria.excluded_by_criterion(row.get("tags") for row in rows)
        named = {c.id: c.name for c in criteria.load(review.folder, main)}
        for cid, count in sorted(per.items()):
            label = f"{cid} – {named[cid]}" if cid in named else cid
            flow.excluded.lines.append(f"excluded by {label}: {count}")
    flow.included.count = counts.get(screening.INCLUDE, 0)
    maybe = counts.get(screening.MAYBE, 0)
    if maybe:
        flow.included.lines.append(f"plus {maybe} marked maybe")
    flow.pending.count = counts.get("undecided", 0)

    done = [s for s in card.enrichments if s.status == "completed"]
    flow.enrichment.count = len(done)
    by_source: dict[str, int | None] = {}
    for step in done:  # the latest run of each source
        by_source[step.what] = step.papers
    for what, papers in by_source.items():
        flow.enrichment.lines.append(
            what + (f": {papers} papers updated" if papers is not None else "")
        )
    return flow


EXPORT_BASENAME = "prisma_flow"


def export_figure(flow: Prisma, out_dir: Path) -> list[Path]:
    """Draw the flow as a PRISMA-style figure: ``prisma_flow.svg`` and ``.png``."""
    import textwrap

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    def text_of(box: Box, width: int = 42) -> str:
        count = "n = —" if box.count is None else f"n = {box.count:,}"
        lines = [f"{box.title} ({count})"]
        for line in box.lines[:7]:
            lines += textwrap.wrap(line, width) or [""]
        return "\n".join(lines)

    # (phase, left box, right box); y grows downwards.
    rows = [
        ("Identification", flow.identification, flow.other_sources),
        ("", None, flow.removed_before),
        ("Screening", flow.screened, flow.excluded),
        ("Included", flow.included, flow.pending),
        ("Enrichment", flow.enrichment, None),
    ]
    fig, ax = plt.subplots(figsize=(11, 12))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 12.5)
    ax.invert_yaxis()
    ax.axis("off")
    left_x, right_x, width, height = 1.6, 6.4, 4.2, 2.0
    for index, (phase, left, right) in enumerate(rows):
        top = 0.3 + index * 2.45
        if phase:
            ax.text(
                0.6,
                top + height / 2,
                phase,
                rotation=90,
                ha="center",
                va="center",
                fontsize=11,
                fontweight="bold",
                color="#2a78d6",
            )
        for x, box, colour in ((left_x, left, "#eaf2fb"), (right_x, right, "#f4f4f2")):
            if box is None:
                continue
            ax.add_patch(
                FancyBboxPatch(
                    (x, top),
                    width,
                    height,
                    boxstyle="round,pad=0.05",
                    facecolor=colour,
                    edgecolor="#52514e",
                    linewidth=1,
                )
            )
            ax.text(x + 0.12, top + 0.12, text_of(box), ha="left", va="top", fontsize=8)
        arrow = {"arrowstyle": "->", "color": "#52514e"}
        centre = left_x + width / 2
        if left is not None and index < len(rows) - 1:
            # Down to the next box of the main flow (skipping the empty row).
            below = next(
                i for i in range(index + 1, len(rows)) if rows[i][1] is not None
            )
            ax.annotate(
                "",
                xy=(centre, 0.3 + below * 2.45),
                xytext=(centre, top + height),
                arrowprops=arrow,
            )
        if left is None and right is not None:
            # Records removed before screening: a branch off the main flow.
            ax.annotate(
                "",
                xy=(right_x, top + height / 2),
                xytext=(centre, top + height / 2),
                arrowprops=arrow,
            )
        if left is not None and right is not None and phase != "Identification":
            ax.annotate(
                "",
                xy=(right_x, top + height / 2),
                xytext=(left_x + width, top + height / 2),
                arrowprops=arrow,
            )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for suffix in (".svg", ".png"):
        path = out_dir / f"{EXPORT_BASENAME}{suffix}"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        files.append(path)
    plt.close(fig)
    return files
