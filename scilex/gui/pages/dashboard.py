"""Dashboard step: statistics, charts and citation network, all cross-filtered.

Built with D3 and crossfilter (``scilex/gui/assets/dashboard``, shipped with
the app, so it works offline). Every chart filters the others: brush the
years, click bars (paper type, collection, source, tags, decision,
eligibility, criteria not met…), or keep one paper and its neighbours in the
network. Clicking a paper (network node or list row) opens its full notice on
the right, the one of Explore, with its actions (validate, discard, keep as
an exception, enrich).
"""

from __future__ import annotations

import json
from pathlib import Path

from nicegui import app, events, run, ui

from scilex.gui.components import criteria_panel
from scilex.gui.components.errors import show_error
from scilex.gui.pages.explore import ExplorePage, compute_eligibility
from scilex.gui.services import dashboard as service
from scilex.gui.services.screening import (
    CitationNetwork,
    ReviewFileError,
    ScreeningSession,
)
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

ASSET_DIR = Path(__file__).parents[1] / "assets" / "dashboard"
ASSET_URL = "/scilex-dashboard"
SCRIPTS = (
    ("d3", f"{ASSET_URL}/vendor/d3.min.js"),
    ("crossfilter", f"{ASSET_URL}/vendor/crossfilter.min.js"),
    ("SciLExDashboard", f"{ASSET_URL}/dashboard.js"),
)
_served = False


def _serve_assets() -> None:
    global _served
    if not _served:
        app.add_static_files(ASSET_URL, ASSET_DIR)
        _served = True


def build_payload(
    review: Review, scope: str | None = None
) -> tuple[ScreeningSession, list, dict, dict]:
    """Session, criteria, eligibility verdicts and the dashboard data
    (``scope``: screened / automatic / all papers, see scope_switch)."""
    from scilex.gui.components import scope_switch

    session = (
        ScreeningSession(review)
        if scope is None
        else scope_switch.load_session(review, scope)
    )
    items = criteria_panel.load_criteria(review)
    verdicts = compute_eligibility(session, items)
    network = CitationNetwork.load(review)
    data = service.payload(session, verdicts, network, items)
    return session, items, verdicts, data


def mount_script(root_id: str, data: dict) -> str:
    """JavaScript loading the libraries once, then drawing the dashboard."""
    scripts = json.dumps(SCRIPTS)
    return f"""
(async () => {{
  const load = (src) => new Promise((ok, ko) => {{
    const s = document.createElement('script');
    s.src = src; s.onload = ok; s.onerror = ko; document.head.appendChild(s);
  }});
  if (!document.getElementById('sx-dashboard-css')) {{
    const l = document.createElement('link');
    l.id = 'sx-dashboard-css'; l.rel = 'stylesheet';
    l.href = '{ASSET_URL}/dashboard.css';
    document.head.appendChild(l);
  }}
  try {{
    for (const [name, src] of {scripts}) {{ if (!window[name]) await load(src); }}
  }} catch (e) {{
    const r = document.getElementById('{root_id}');
    if (r) r.textContent = 'The charts could not be loaded.';
    return;
  }}
  window.SciLExDashboard.mount('{root_id}', {json.dumps(data)});
}})();
"""


class DashboardNotice(ExplorePage):
    """The Explore notice of the paper clicked in the dashboard.

    Previous / next follow the papers left by the dashboard filters.
    """

    def __init__(self, review, session, profile, ctx, eligibility, root_id: str):
        super().__init__(review, session, profile, ctx=ctx, eligibility=eligibility)
        self.order = [row["paper_key"] for row in session.rows]
        self.current = None
        self.root_id = root_id

    def move(self, step: int) -> None:
        if not self.order:
            return
        index = self.order.index(self.current) if self.current in self.order else -1
        self.current = self.order[min(max(index + step, 0), len(self.order) - 1)]
        self.notice.refresh()
        ui.run_javascript(
            f"const r = document.getElementById({json.dumps(self.root_id)});"
            f"if (r && r.sxSelect) r.sxSelect({json.dumps(self.current)});"
        )

    def refill(self) -> None:  # no grid here: the notice only
        self.notice.refresh()


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Dashboard step of ``review``."""
    _serve_assets()
    ui.label("Dashboard").classes("text-2xl font-bold")
    ui.label(
        "Statistics, charts and citation network of the review, all linked: "
        "drag over the years, click bars or legend values to filter every "
        "view; click a paper (network or list) to read its notice."
    ).classes("text-gray-500")
    from scilex.gui.components import scope_switch

    # A new scope draws the page again (the charts are built once per load).
    scope_switch.switch(review, lambda _: ui.navigate.reload())
    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        holder = ui.column().classes("grow min-w-0")
        side = ui.column().classes("w-[26rem] shrink-0 sticky top-2")
    with holder, ui.row().classes("items-center gap-2") as loading:
        ui.spinner()
        ui.label("Loading papers…")
    root = ui.element("div").classes("w-full").mark("dashboard-root")
    root.move(holder)
    root_id = f"sx-dashboard-{root.id}"
    root.props(f"id={root_id}")
    state: dict = {}

    async def load() -> None:
        try:
            session, items, verdicts, data = await run.io_bound(
                build_payload, review, scope_switch.current(review)
            )
        except Exception as exc:
            if holder.is_deleted:
                return
            loading.delete()
            with holder:
                show_error(
                    "Cannot load the results",
                    exc,
                    expected=isinstance(exc, ReviewFileError),
                )
            return
        if holder.is_deleted:
            return
        loading.delete()
        state["data"] = data
        with side:
            notice = DashboardNotice(
                review, session, ctx.profile, ctx, (items, verdicts), root_id
            )
            state["notice"] = notice
            notice.notice()
        ui.run_javascript(mount_script(root_id, data), timeout=30)

    def on_paper(event: events.GenericEventArguments) -> None:
        notice = state.get("notice")
        key = (event.args or {}).get("key")
        if notice is None or side.is_deleted or not key:
            return
        notice.current = key
        notice.notice.refresh()

    def on_filtered(event: events.GenericEventArguments) -> None:
        notice = state.get("notice")
        if notice is not None:
            notice.order = list((event.args or {}).get("keys") or [])

    ui.on("scilex_dashboard_paper", on_paper)
    ui.on("scilex_dashboard_filtered", on_filtered)
    ui.timer(0, load, once=True)
