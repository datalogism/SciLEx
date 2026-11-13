"""Sidebar listing the pipeline steps of a review."""

from dataclasses import dataclass

from nicegui import ui

from scilex.gui.components.branding import render_logo
from scilex.gui.services.workspace import Review


@dataclass(frozen=True)
class Step:
    """One entry of the sidebar."""

    key: str
    label: str
    icon: str
    needs_results: bool = False
    # Label once the review has papers (collected, imported or snowballed).
    label_with_results: str | None = None
    # Hidden once the review has papers (Collect: then in ⑤ Extend > New collect).
    hidden_with_results: bool = False

    def label_for(self, review: Review) -> str:
        """Return the label shown for ``review``."""
        if self.label_with_results and review.has_results:
            return self.label_with_results
        return self.label


# The review workflow: collect (or load from Zotero), screen, annotate, extend
# the corpus, enrich it, analyse it, export it.
PIPELINE_STEPS = (
    Step("overview", "Overview", "dashboard"),
    Step("explore", "Explore", "manage_search", needs_results=True),
    Step("dashboard", "Dashboard", "space_dashboard", needs_results=True),
    Step("configure", "① Configure", "tune"),
    Step("collect", "② Collect", "travel_explore", hidden_with_results=True),
    Step("criteria", "Eligibility criteria", "rule", needs_results=True),
    Step("screen", "③ Screen", "fact_check", needs_results=True),
    Step("annotate", "④ Annotate", "sell"),
    Step("extend", "⑤ Extend", "hub", needs_results=True),
    Step("consolidate", "Consolidate", "merge_type", needs_results=True),
    Step("enrich", "⑥ Enrich", "auto_awesome", needs_results=True),
    Step("analyses", "⑦ Analyses", "insights", needs_results=True),
    Step("export", "⑧ Export", "ios_share", needs_results=True),
)
EXTRA_STEPS = (Step("group", "Zotero group", "groups"), Step("keys", "API keys", "key"))
STEPS = {step.key: step for step in (*PIPELINE_STEPS, *EXTRA_STEPS)}
DEFAULT_STEP = "overview"  # opening a review shows its summary first
RESULTS_POLL_SECONDS = 1.0
INVALID_CONFIG_HINT = "Fix scilex.yml in ① Configure first"
# Steps usable while scilex.yml cannot be loaded (to repair it).
USABLE_WHEN_INVALID = ("configure", "keys")
NEEDS_RESULTS_HINT = (
    "Available once a collection has been aggregated (step ②: Run, or "
    "Aggregate existing results after a stopped collection)."
)


def is_enabled(step: Step, review: Review) -> bool:
    """Return True if ``step`` can be opened for ``review``."""
    return review.has_results or not step.needs_results


# Collapsed sidebar: icons only, the step names as tooltips (title attribute).
# SIDEBAR_CLASS goes on the whole left column (review name, folder, steps);
# HIDDEN_WHEN_FOLDED on what is left out when it is folded.
SIDEBAR_CLASS, HIDDEN_WHEN_FOLDED = "scilex-sidebar", "scilex-sidebar-hide"
SIDEBAR_CSS = """
.scilex-sidebar { width: 13rem; transition: width .15s; }
.scilex-sidebar.collapsed { width: 2.75rem; }
.scilex-sidebar.collapsed .q-btn__content > .block,
.scilex-sidebar.collapsed .scilex-sidebar-hide { display: none; }
.scilex-sidebar.collapsed .scilex-sidebar-wrap { flex-wrap: wrap; }
.scilex-sidebar.collapsed .q-btn { padding-left: 0; padding-right: 0; }
.scilex-sidebar.collapsed .q-btn__content { justify-content: center; }
"""
SIDEBAR_KEY = "scilex.sidebarCollapsed"  # browser localStorage: kept per browser
# Run in the browser: no round trip, and the choice survives page changes.
TOGGLE_SIDEBAR_JS = (
    "() => { const s = document.querySelector('.scilex-sidebar');"
    " const c = s.classList.toggle('collapsed');"
    f" try {{ localStorage.setItem('{SIDEBAR_KEY}', c ? '1' : '0'); }} catch (e) {{}} }}"
)
RESTORE_SIDEBAR_JS = (
    f"try {{ if (localStorage.getItem('{SIDEBAR_KEY}') === '1')"
    " document.querySelector('.scilex-sidebar')?.classList.add('collapsed'); }"
    " catch (e) {}"
)


def render_sidebar(review: Review, active: str) -> None:
    """Draw the steps of ``review``, highlighting ``active``.

    Draw it inside a column of class :data:`SIDEBAR_CLASS`. The menu folds to its icons (toggle at its top) to leave the page more
    room; the browser remembers the choice.
    Steps that need results unlock by themselves as soon as the aggregation
    writes its results file (checked every second), without a page reload.
    """
    ui.add_head_html(f"<style>{SIDEBAR_CSS}</style>")
    locked: list[ui.button] = []
    with ui.column().classes("w-full gap-1").mark("sidebar"):
        with ui.row().classes("w-full items-center no-wrap gap-0"):
            ui.button(icon="menu_open").props(
                'flat round dense title="Fold or unfold the menu"'
            ).on("click", js_handler=TOGGLE_SIDEBAR_JS).mark("sidebar-toggle")
            render_logo(f"w-32 mb-2 cursor-pointer {HIDDEN_WHEN_FOLDED}").on(
                "click", lambda: ui.navigate.to("/")
            )
        for step in PIPELINE_STEPS:
            if step.hidden_with_results and review.has_results and step.key != active:
                continue
            _step_button(review, step, active, locked)
        ui.separator()
        for step in EXTRA_STEPS:
            _step_button(review, step, active, locked)
        ui.button(
            "My reviews", icon="folder_open", on_click=lambda: ui.navigate.to("/")
        ).props('flat align=left no-caps title="My reviews"').classes("w-full")
    ui.timer(0, lambda: ui.run_javascript(RESTORE_SIDEBAR_JS), once=True)

    if not locked:
        return

    def unlock_when_results_exist() -> None:
        if not review.has_results:
            return
        for button in locked:
            button.enable()
            for tooltip in [
                c for c in button.default_slot.children if isinstance(c, ui.tooltip)
            ]:
                tooltip.delete()
        locked.clear()
        timer.cancel()

    timer = ui.timer(RESULTS_POLL_SECONDS, unlock_when_results_exist)


def _step_button(
    review: Review, step: Step, active: str, locked: list[ui.button]
) -> None:
    button = ui.button(
        step.label_for(review),
        icon=step.icon,
        on_click=lambda: ui.navigate.to(f"/review/{review.id}/{step.key}"),
    ).props("align=left no-caps" + ("" if step.key == active else " flat"))
    button.props(f'title="{step.label_for(review)}"')
    button.classes("w-full").mark(f"step-{step.key}")
    if review.error and step.key not in USABLE_WHEN_INVALID:
        # Never unlocked by the results timer: the config must be fixed first.
        button.disable()
        button.tooltip(INVALID_CONFIG_HINT)
    elif not is_enabled(step, review):
        button.disable()
        button.tooltip(NEEDS_RESULTS_HINT)
        locked.append(button)
