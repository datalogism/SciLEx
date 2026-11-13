"""The review workflow as a map: steps, progress, loops and what they share.

Ten steps in two rows read as a snake (① Configure → … → ④ Annotate, then
⑤ Extend → … → ⑧ Export from right to left). Each card shows how far the
step is (a bar coloured by progress: 75 % or more, 40–74 %, under 40 %) and
the loops back show where the review returns to an earlier step. A band
lists what applies at every step. The drawing is a self-contained SVG; a
click on a step emits ``scilex_workflow_stage`` (its key) so the page shows
the step's detail. Progress is read from what the review records: results,
criteria, screening decisions, annotation tags and the journal.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

GOOD, MID, LOW = 75, 40, 0


@dataclass
class StepState:
    """One step of the map."""

    key: str  # page of the step (``/review/<id>/<key>``)
    code: str  # short id on the card (①, E, …)
    name: str
    progress: int | None = None  # 0-100; None: optional or not measurable
    value: str = ""  # one line under the name
    purpose: str = ""
    facts: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)


# (key, code, name, purpose)
STEPS = (
    ("configure", "①", "Configure", "Keywords, years, APIs and quality filters."),
    ("collect", "②", "Collect", "Query the APIs and aggregate the results."),
    (
        "criteria",
        "C",
        "Eligibility",
        "Inclusion and exclusion criteria as rules, applied as tags.",
    ),
    ("screen", "③", "Screen", "Include, exclude or keep each paper as maybe."),
    ("annotate", "④", "Annotate", "Code the papers against the grid, validate."),
    ("extend", "⑤", "Extend", "New collect, snowballing, BibTeX or Zotero imports."),
    ("consolidate", "K", "Consolidate", "Filter and rank the extended corpus again."),
    ("enrich", "⑥", "Enrich", "Citations, metrics, Crossref, LPWC, ORKG, types."),
    ("analyses", "⑦", "Analyses", "Charts, graphs, communities, summaries."),
    ("export", "⑧", "Export", "BibTeX, files, Zotero, knowledge graph."),
)
TOP = ("configure", "collect", "criteria", "screen", "annotate")
BOTTOM = ("extend", "consolidate", "enrich", "analyses", "export")  # right to left
# Loops back: (from, to, label)
LOOPS = (
    ("extend", "screen", "new papers to screen"),
    ("enrich", "criteria", "metrics for the criteria"),
    ("analyses", "configure", "suggested keywords"),
)
SHARED = (
    "Zotero group sync",
    "Journal of every action",
    "ORCID attribution",
    "Tags as shared state",
    "Explore from anywhere",
)
ANALYSES = (
    "analysis-report",
    "analysis-keywords",
    "analysis-graph",
    "analysis-summaries",
    "analysis-tags",
    "analysis-coverage",
)
EXPORTS = ("export-kg", "export-file", "push-zotero", "zotero-push")


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def compute(review, flow, events: list[dict], main: dict | None) -> list[StepState]:
    """The state of each step of ``review`` (``flow``: its PRISMA flow)."""
    from scilex.gui.services import criteria, journal

    # Jobs are journaled as "job:<history key>"; backfilled events have no status.
    done: set[str] = set()
    last_at: dict[str, str] = {}
    for event in events:
        activity = str(event.get("activity") or "").removeprefix("job:")
        if event.get("status", "completed") != "completed":
            continue
        done.add(activity)
        last_at[activity] = max(last_at.get(activity, ""), event.get("at") or "")
    states = {
        key: StepState(key, code, name, purpose=p) for key, code, name, p in STEPS
    }

    # ① Configure
    s = states["configure"]
    if review.error or not main:
        s.progress = 0
        s.todo.append("Fix scilex.yml")
    else:
        groups = [g for g in main.get("keywords") or [] if g]
        apis = main.get("apis") or []
        s.progress = 100 if groups and apis else 50
        s.value = f"{sum(len(g) for g in groups)} keywords · {len(apis)} APIs"
        years = sorted(str(y) for y in main.get("years") or [])
        if years:
            s.facts.append(f"Years {years[0]}–{years[-1]}")
        if not groups:
            s.todo.append("Add keywords")

    # ② Collect
    s = states["collect"]
    identified = flow.identification.count
    if review.has_results:
        s.progress = 100
        s.value = f"{identified:,} identified" if identified else "results ready"
        if flow.removed_before.count:
            s.facts.append(
                f"{flow.removed_before.count:,} removed (duplicates, filters)"
            )
    else:
        started = any(e.get("activity") == "collect-started" for e in events)
        s.progress = 30 if started else 0
        s.value = "running or stopped" if s.progress else "not run"
        s.todo.append("Run the collection")

    kept = flow.kept if flow.kept is not None else (flow.screened.count or 0)
    # C Eligibility criteria
    s = states["criteria"]
    saved = criteria.path_of(review.folder).is_file()
    items = criteria.load(review.folder, main) if review.folder else []
    enabled = [c for c in items if c.enabled]
    s.value = f"{len(enabled)} criteria"
    if "criteria" in last_at:
        s.progress = 100
        excluded = (flow.screened.count or 0) - kept
        s.facts.append(f"Applied: {excluded:,} papers excluded or discarded")
    elif saved:
        s.progress = 50
        s.todo.append("Apply the criteria")
    else:
        s.progress = 0
        s.todo.append("Review and save the criteria")

    # ③ Screen
    s = states["screen"]
    pending = flow.pending.count or 0
    decided = max(kept - pending, 0)
    s.progress = _pct(decided, kept) if kept else 0
    s.value = f"{decided:,} / {kept:,} decided"
    if flow.included.count is not None:
        s.facts.append(f"{flow.included.count:,} included")
    if pending:
        s.todo.append(f"{pending:,} papers still to screen")
    _two_stages(s, review, flow, kept)

    # ④ Annotate
    s = states["annotate"]
    state = _annotation(review)
    if state:
        papers = state.get("papers") or 0
        annotated = state.get("annotated") or 0
        s.progress = _pct(annotated, papers)
        s.value = f"{annotated:,} / {papers:,} annotated"
        if state.get("validated"):
            s.facts.append(f"{state['validated']:,} validated")
    else:
        s.progress = 0
        s.value = "not started"

    # ⑤ Extend (optional)
    s = states["extend"]
    added = flow.other_sources.count or 0
    s.value = f"{added:,} papers added" if added else "optional"
    s.facts += flow.other_sources.lines[:4]
    extended_at = max(
        (last_at.get(k, "") for k in (*journal.EXTENSIONS, "papers-added")),
        default="",
    )

    # K Consolidate: needed after an extension
    s = states["consolidate"]
    consolidated_at = last_at.get("consolidate", "")
    if extended_at and consolidated_at < extended_at:
        s.progress = 0
        s.value = "needed"
        s.todo.append("Consolidate after the last extension")
    elif consolidated_at:
        s.progress = 100
        s.value = "up to date"
    else:
        s.value = "not needed yet"

    # ⑥ Enrich
    s = states["enrich"]
    enrichers = journal.ENRICHERS
    ran = [name for kind, (name, _) in enrichers.items() if kind in done]
    s.progress = _pct(len(ran), len(enrichers))
    s.value = f"{len(ran)} / {len(enrichers)} sources"
    s.facts += [f"Done: {', '.join(ran)}"] if ran else []
    missing = [name for kind, (name, _) in enrichers.items() if kind not in done]
    if missing:
        s.todo.append("Not run: " + ", ".join(missing))

    # ⑦ Analyses (optional, counted)
    s = states["analyses"]
    run = [k.removeprefix("analysis-") for k in ANALYSES if k in done]
    s.value = f"{len(run)} analyses run" if run else "none yet"
    if run:
        s.facts.append("Run: " + ", ".join(run))

    # ⑧ Export
    s = states["export"]
    exported = [k for k in EXPORTS if k in done]
    s.progress = 100 if exported else 0
    s.value = "exported" if exported else "not yet"
    s.facts += [journal.LABELS.get(k, k) for k in exported]
    return [states[key] for key, *_ in STEPS]


def _two_stages(s: StepState, review, flow, kept: int) -> None:
    """Screening in two stages: the automatic one (rules), then people's
    screened-results collections in Zotero (``collection_roles``)."""
    from scilex.gui.services import collection_roles, zotero_library

    if not review.folder or zotero_library.load_source(review.folder) is None:
        return
    roles = collection_roles.load(review.folder)
    s.facts.insert(
        0, f"Stage 1, automatic: {kept:,} of {flow.screened.count or 0:,} kept"
    )
    if not collection_roles.configured(roles):
        s.todo.append("Mark the screened-results collections (Zotero group page)")
        return
    included = flow.included.count or 0
    s.value = f"{included:,} in screened collections"
    s.facts.insert(1, f"Stage 2, by hand: {included:,} in screened collections")
    s.facts[2:2] = [f"  {line}" for line in flow.included.lines]


def _annotation(review) -> dict | None:
    from scilex.gui.services import journal

    try:
        return journal.annotation_of_results(Path(review.results_path))
    except Exception:  # unreadable results: no annotation state
        return None


# -- drawing -------------------------------------------------------------------

BW, BH = 168, 64
XS = (20, 206, 392, 578, 764)
RA, RB = 18, 206
STYLE = """
.wf-stg{cursor:pointer}
.wf-stg rect.box{fill:#fff;stroke:#d3dad6;stroke-width:1.4}
.wf-stg:hover rect.box{stroke:#2c5bb8}
.wf-stg.on rect.box{stroke:#1d2528;stroke-width:2.2}
.wf text{fill:#1d2528;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
.wf .q{fill:#566367}
.wf .flow{stroke:#566367;stroke-width:1.4;fill:none}
.wf .loop{stroke:#2c5bb8;stroke-width:2;fill:none}
.wf .band{fill:rgba(29,37,40,.04);stroke:#d3dad6}
.wf .dim{fill:#fff;stroke:#d3dad6}
.wf .track{fill:#d3dad6}
.body--dark .wf-stg rect.box,.body--dark .wf .dim{fill:#1d2427;stroke:#33403f}
.body--dark .wf-stg.on rect.box{stroke:#e6ecea}
.body--dark .wf text{fill:#e6ecea}
.body--dark .wf .q{fill:#a0acaf}
.body--dark .wf .loop{stroke:#8fa9ff}
.body--dark .wf .band{fill:rgba(230,236,234,.05);stroke:#33403f}
.body--dark .wf .track{fill:#33403f}
"""


def tone(progress: int | None) -> str:
    if progress is None:
        return "#9498a0"
    if progress >= GOOD:
        return "#2e7d5b"
    if progress >= MID:
        return "#b8862a"
    return "#b04639"


def positions() -> dict[str, tuple[int, int]]:
    pos = {key: (XS[i], RA) for i, key in enumerate(TOP)}
    pos.update({key: (XS[4 - i], RB) for i, key in enumerate(BOTTOM)})
    return pos


def svg(steps: list[StepState], selected: str | None = None) -> str:
    """The map as an SVG (clicks emit ``scilex_workflow_stage``)."""
    esc = html.escape
    pos = positions()
    centre = {k: (x + BW / 2, y) for k, (x, y) in pos.items()}
    parts = [
        '<svg class="wf" viewBox="0 0 952 392" role="img" '
        'aria-label="Review workflow with loops back and shared services" '
        'style="width:100%;height:auto;display:block">',
        f"<style>{STYLE}</style>",
        '<defs><marker id="wf-ah" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0 0L10 5L0 10z" fill="#566367"/></marker>'
        '<marker id="wf-ahb" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0 0L10 5L0 10z" fill="#2c5bb8"/></marker></defs>',
    ]
    # Forward flow: top row left to right, down, bottom row right to left.
    mid_a, mid_b = RA + BH / 2, RB + BH / 2
    flows = [f"M{XS[i] + BW} {mid_a}H{XS[i + 1]}" for i in range(4)]
    flows.append(f"M{XS[4] + BW - 20} {RA + BH}V{RB}")
    flows += [f"M{XS[i]} {mid_b}H{XS[i - 1] + BW}" for i in range(4, 0, -1)]
    parts += [f'<path class="flow" d="{d}" marker-end="url(#wf-ah)"/>' for d in flows]
    # Loops back, at different heights so they never cross.
    heights = {"extend": 156, "enrich": 0, "analyses": 132}
    for source, target, label in LOOPS:
        (sx, _), (tx, _) = centre[source], centre[target]
        sx -= 30
        tx += 0 if source != "enrich" else 0
        y = heights[source]
        if y:
            d = f"M{sx:.0f} {RB}V{y}H{tx:.0f}V{RA + BH}"
            lx, ly = (sx + tx) / 2, y - 6
        else:
            d = f"M{sx:.0f} {RB}V{RA + BH}"
            lx, ly = sx + 8, (RB + RA + BH) / 2
        parts.append(f'<path class="loop" d="{d}" marker-end="url(#wf-ahb)"/>')
        anchor = "start" if not y else "middle"
        parts.append(
            f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="11.5" class="q" '
            f'text-anchor="{anchor}">{esc(label)}</text>'
        )
    # The step cards.
    for step in steps:
        x, y = pos[step.key]
        on = " on" if step.key == selected else ""
        width = (BW - 24) * (step.progress or 0) / 100
        pct = "" if step.progress is None else f"{step.progress}%"
        parts.append(
            f'<g class="wf-stg{on}" data-step="{step.key}" role="button" tabindex="0" '
            f"onclick=\"emitEvent('scilex_workflow_stage', '{step.key}')\" "
            f'aria-label="{esc(step.name)} {pct}">'
            f'<rect class="box" x="{x}" y="{y}" width="{BW}" height="{BH}" rx="8"/>'
            f'<text x="{x + 12}" y="{y + 21}" font-size="13" font-weight="600">'
            f"{esc(step.code)} {esc(step.name)}</text>"
            f'<text x="{x + BW - 12}" y="{y + 21}" font-size="11.5" class="q" '
            f'text-anchor="end">{pct}</text>'
            f'<text x="{x + 12}" y="{y + 39}" font-size="11" class="q">'
            f"{esc(step.value[:30])}</text>"
        )
        if step.progress is not None:
            parts.append(
                f'<rect class="track" x="{x + 12}" y="{y + 49}" width="{BW - 24}" '
                f'height="4" rx="2"/>'
                f'<rect x="{x + 12}" y="{y + 49}" width="{width:.1f}" height="4" '
                f'rx="2" fill="{tone(step.progress)}"/>'
            )
        parts.append("</g>")
    # What applies at every step.
    parts.append(
        '<rect class="band" x="20" y="292" width="912" height="92" rx="8"/>'
        '<text x="36" y="312" font-size="12.5" font-weight="600">'
        "At every step</text>"
    )
    for k, label in enumerate(SHARED):
        x = 36 + k * 180
        parts.append(
            f'<rect class="dim" x="{x}" y="322" width="168" height="46" rx="8"/>'
            f'<text x="{x + 84}" y="349" font-size="11.5" text-anchor="middle">'
            f"{esc(label)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)
