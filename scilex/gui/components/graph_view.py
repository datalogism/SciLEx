"""Graph tab results: interactive network, communities and linked papers."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from scilex.gui.services import exports
from scilex.gui.services import graph_view as service

PAPER_ROWS_SHOWN = 300


def render_graph_results(graph_dir: Path) -> None:
    """Draw the results of the Graph analysis found in ``graph_dir``."""
    names = service.available_graphs(graph_dir)
    if not names:
        return
    container = ui.column().classes("w-full gap-3")

    def show(name: str) -> None:
        container.clear()
        with container:
            _render_view(graph_dir, name)

    if len(names) > 1:
        ui.toggle(
            {name: service.GRAPH_NAMES[name] for name in names}, value=names[0]
        ).on_value_change(lambda event: show(event.value)).mark("graph-choice")
        container.move(target_index=-1)
    show(names[0])


def _render_view(graph_dir: Path, name: str) -> None:
    try:
        view = service.build_graph_view(graph_dir, name)
    except (FileNotFoundError, ValueError) as exc:
        ui.label(f"Cannot display the graph: {exc}").classes("text-red-700")
        return

    ui.label(service.GRAPH_EXPLANATIONS[name]).classes("text-sm text-gray-600")
    real_communities = [c for c in view.communities if c.size > 1]
    ui.label(
        f"{view.linked_papers} of {view.total_papers} papers are linked "
        f"({view.links} links, {len(real_communities)} communities)."
    ).classes("font-bold").mark("graph-stats")
    if view.linked_papers == 0:
        ui.label(
            "No links: fetch citations for more papers in ⑥ Enrich (Citations tab), "
            "lower Min edge weight, or try the other graph type."
        ).classes("text-orange-700")
        return
    if view.linked_papers < view.total_papers / 10:
        ui.label(
            "Few papers are linked, so most are left out of the drawing. Fetching "
            "references and citing papers for more of the corpus (⑥ Enrich, Citations tab) "
            "links more of them; the other graph type may also link more."
        ).classes("text-sm text-orange-700")
    if view.shown_papers < view.linked_papers:
        ui.label(f"Drawing the {view.shown_papers} most central papers.").classes(
            "text-sm text-gray-500"
        )

    _render_network(view)
    _render_communities(real_communities)
    _render_papers(view)
    if view.graph_file is not None:
        graph_file = view.graph_file
        with ui.row().classes("items-center gap-2"):
            ui.label(
                f"Full graph: {graph_file.name} (opens in Gephi or Cytoscape)"
            ).classes("text-xs text-gray-500").tooltip(str(graph_file))
            ui.button(
                "Reveal in folder",
                icon="folder_open",
                on_click=lambda: exports.reveal_in_folder(graph_file),
            ).props("flat dense size=sm").mark("graph-reveal")


def _render_network(view: service.GraphView) -> None:
    choices = {0: "All communities"} | {
        community.cluster_id + 1: f"Community {community.cluster_id} "
        f"({community.size} papers)"
        for community in view.communities
        if community.size > 1
    }
    # Select values are shifted by one: 0 stands for "all".
    community_select = ui.select(choices, value=0, label="Show").classes("w-64")
    community_select.mark("graph-community")
    chart = (
        ui.echart(service.chart_options(view))
        .classes("w-full border rounded")
        .style("height: 520px")
        .mark("graph-chart")
    )
    details = ui.column().classes("w-full gap-0").mark("graph-details")

    def filter_community(event) -> None:
        cluster = None if not event.value else event.value - 1
        chart.options.clear()
        chart.options.update(service.chart_options(view, cluster))
        chart.update()

    def show_details(event) -> None:
        if event.data_type != "node" or not isinstance(event.data, dict):
            return
        node = event.data
        details.clear()
        with details:
            ui.label(node.get("title", "")).classes("font-bold")
            meta = " · ".join(
                part
                for part in (
                    node.get("authors", "").replace(";", ", "),
                    node.get("year", ""),
                    f"community {node.get('cluster')}",
                )
                if part
            )
            ui.label(meta).classes("text-sm text-gray-600")
            doi = node.get("doi", "")
            if doi:
                ui.link(
                    f"https://doi.org/{doi}", f"https://doi.org/{doi}", new_tab=True
                )

    community_select.on_value_change(filter_community)
    chart.on_point_click(show_details)
    ui.label(
        "Node size: centrality (PageRank). Colour: community. Scroll to zoom, "
        "drag to move, click a paper for details."
    ).classes("text-xs text-gray-500")


def _render_communities(communities: list[service.Community]) -> None:
    if not communities:
        return
    ui.label("Communities").classes("text-lg font-bold")
    columns = [
        {"name": "id", "label": "Community", "field": "id", "align": "left"},
        {"name": "size", "label": "Papers", "field": "size", "sortable": True},
        {
            "name": "years",
            "label": "Years",
            "field": "years",
            "style": "white-space: nowrap",
        },
        {
            "name": "top",
            "label": "Most central papers",
            "field": "top",
            "align": "left",
        },
    ]
    rows = [
        {
            "id": community.cluster_id,
            "color": community.color,
            "size": community.size,
            "years": community.years,
            "top": " · ".join(community.top_titles),
        }
        for community in communities
    ]
    table = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")
    table.props("dense wrap-cells").mark("graph-communities")
    table.add_slot(
        "body-cell-id",
        r"""
        <q-td :props="props">
          <span :style="{background: props.row.color}"
                style="display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px"></span>
          {{ props.value }}
        </q-td>
        """,
    )


def _render_papers(view: service.GraphView) -> None:
    papers = view.papers.head(PAPER_ROWS_SHOWN).fillna("")
    if papers.empty:
        return
    with ui.expansion(f"Linked papers ({len(view.papers)})", icon="list").classes(
        "w-full"
    ):
        papers = papers.assign(pagerank=papers["pagerank"].map(lambda v: f"{v:.4f}"))
        columns = [
            {
                "name": "cluster_id",
                "label": "Community",
                "field": "cluster_id",
                "sortable": True,
            },
            {
                "name": "pagerank",
                "label": "PageRank",
                "field": "pagerank",
                "sortable": True,
            },
            {"name": "title", "label": "Title", "field": "title", "align": "left"},
            {"name": "year", "label": "Year", "field": "year", "sortable": True},
            {"name": "DOI", "label": "DOI", "field": "DOI", "align": "left"},
        ]
        rows = papers[[c["name"] for c in columns]].astype(str).to_dict("records")
        ui.table(columns=columns, rows=rows).classes("w-full").props(
            "dense wrap-cells"
        ).mark("graph-papers")
