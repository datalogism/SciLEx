"""Data of the Graph tab: read the exported graph and clusters into a drawable view.

The Graph analysis writes ``<name>_graph.gexf|graphml`` (nodes are normalised
DOIs with ``cluster_id`` and ``pagerank`` attributes) and ``clusters_<name>.csv``
(the aggregated papers with the same two columns). This module joins them into
nodes, links and community summaries for the page, without any UI code.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import pandas as pd

from scilex.constants import is_valid, normalize_doi

GRAPH_NAMES = {"cocitation": "Co-citation", "coupling": "Bibliographic coupling"}
GRAPH_EXPLANATIONS = {
    "cocitation": (
        "Two corpus papers are linked when a third paper cites both of them; "
        "the link weight is the number of such papers. Shows how the field "
        "groups the corpus papers together."
    ),
    "coupling": (
        "Two corpus papers are linked when they cite the same references; "
        "the link weight is the number of shared references. Works for recent "
        "papers that are not cited yet."
    ),
}
MAX_NODES = 300
TOP_TITLES = 3
# Categorical palette; communities beyond it are drawn in grey.
PALETTE = (
    "#4269d0",
    "#efb118",
    "#ff725c",
    "#6cc5b0",
    "#3ca951",
    "#ff8ab7",
    "#a463f2",
    "#97bbf5",
    "#9c6b4e",
    "#9498a0",
)
OTHER_COLOR = "#c8c8c8"


@dataclass
class Community:
    """One community of linked papers."""

    cluster_id: int
    size: int
    years: str
    top_titles: list[str]
    color: str


@dataclass
class GraphView:
    """Everything the Graph tab draws for one graph."""

    name: str
    total_papers: int
    linked_papers: int
    links: int
    shown_papers: int
    communities: list[Community] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    papers: pd.DataFrame = field(default_factory=pd.DataFrame)
    graph_file: Path | None = None
    # Colour of each value, per "colour by" choice (see COLOR_BY).
    palettes: dict[str, dict[str, str]] = field(default_factory=dict)
    # The review's results row of each drawn paper (details on click).
    records: dict[str, dict] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """Human name of the graph."""
        return GRAPH_NAMES.get(self.name, self.name)


def available_graphs(graph_dir: Path) -> list[str]:
    """Names of the graphs that have a clusters CSV in ``graph_dir``."""
    return [
        name for name in GRAPH_NAMES if (graph_dir / f"clusters_{name}.csv").is_file()
    ]


def _graph_file(graph_dir: Path, name: str) -> Path | None:
    files = [
        path
        for path in (
            graph_dir / f"{name}_graph.gexf",
            graph_dir / f"{name}_graph.graphml",
        )
        if path.is_file()
    ]
    return max(files, key=lambda path: path.stat().st_mtime, default=None)


def _read_graph(path: Path) -> nx.Graph:
    if path.suffix == ".graphml":
        return nx.read_graphml(path)
    return nx.read_gexf(path)


def _year(value) -> str:
    text = str(value) if is_valid(value) else ""
    return text[:4] if text[:4].isdigit() else ""


def _short(text: str, length: int = 60) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def _paper_table(clusters_csv: Path) -> pd.DataFrame:
    """Read the clusters CSV, keyed by normalised DOI."""
    from scilex.gui.services.analyses import read_result_csv

    frame = read_result_csv(clusters_csv)
    for column in ("title", "authors", "date", "DOI", "cluster_id", "pagerank"):
        if column not in frame.columns:
            frame[column] = ""
    frame["doi_key"] = frame["DOI"].map(normalize_doi)
    frame["cluster_id"] = pd.to_numeric(frame["cluster_id"], errors="coerce")
    frame["pagerank"] = pd.to_numeric(frame["pagerank"], errors="coerce").fillna(0.0)
    frame["year"] = frame["date"].map(_year)
    return frame


COMMUNITY, PAPER_TYPE, COLLECTION = "community", "paper_type", "collection"
COLOR_BY = {
    COMMUNITY: "Community",
    PAPER_TYPE: "Paper type",
    COLLECTION: "Zotero collection",
}
NO_COLLECTION = "(no collection)"


def _records_by_doi(collect_dir: Path) -> dict[str, dict]:
    """The review's results rows, by normalised DOI."""
    from scilex.gui.services.extend import read_results

    try:
        data = read_results(collect_dir / "aggregated_results.csv")
    except (OSError, ValueError):
        return {}
    if data is None:
        return {}
    found = {}
    for row in data.to_dict("records"):
        doi = normalize_doi(row.get("DOI")) if is_valid(row.get("DOI")) else None
        if doi:
            found[doi] = row
    return found


def _groups(record: dict | None) -> tuple[str, str]:
    """``(paper type, first Zotero collection)`` of a results row."""
    from scilex import review_tags
    from scilex.paper_types import effective_type

    if record is None:
        return "(unknown)", "(unknown)"
    collections = review_tags.split_tags(record.get("zotero_collections"))
    return effective_type(record), collections[0] if collections else NO_COLLECTION


def _palette(values) -> dict[str, str]:
    """A colour per value, the most frequent first."""
    ranked = pd.Series(list(values), dtype=object).value_counts().index
    return {
        str(value): PALETTE[rank] if rank < len(PALETTE) else OTHER_COLOR
        for rank, value in enumerate(ranked)
    }


def build_graph_view(
    graph_dir: Path, name: str, max_nodes: int = MAX_NODES
) -> GraphView:
    """Join the graph file and the clusters CSV of graph ``name``.

    Only papers with at least one link are drawn (isolated papers carry no
    information); above ``max_nodes`` the most central ones are kept.

    Raises:
        FileNotFoundError: If the clusters CSV is missing.
        ValueError: If the CSV cannot be parsed.
    """
    clusters_csv = graph_dir / f"clusters_{name}.csv"
    if not clusters_csv.is_file():
        raise FileNotFoundError(clusters_csv)
    frame = _paper_table(clusters_csv)
    graph_file = _graph_file(graph_dir, name)
    graph = _read_graph(graph_file) if graph_file else nx.Graph()

    linked = [node for node in graph.nodes if graph.degree(node) > 0]
    pagerank = {node: float(graph.nodes[node].get("pagerank", 0.0)) for node in linked}
    shown = sorted(linked, key=lambda node: pagerank[node], reverse=True)[:max_nodes]
    shown_set = set(shown)

    by_doi = frame.dropna(subset=["doi_key"]).drop_duplicates("doi_key")
    by_doi = by_doi.set_index("doi_key")
    cluster_of = {node: int(graph.nodes[node].get("cluster_id", -1)) for node in linked}

    # Communities of linked papers, largest first; colours follow that order.
    sizes = pd.Series(cluster_of, dtype="int64").value_counts()
    colors = {
        int(cluster): PALETTE[rank] if rank < len(PALETTE) else OTHER_COLOR
        for rank, cluster in enumerate(sizes.index)
    }
    communities = []
    for cluster, size in sizes.items():
        members = sorted(
            (node for node in linked if cluster_of[node] == cluster),
            key=lambda node: pagerank[node],
            reverse=True,
        )
        rows = by_doi.reindex(members)
        years = sorted(year for year in rows["year"].dropna() if year)
        titles = [
            str(title)
            for title in rows["title"].fillna("")
            if is_valid(title) and title
        ]
        communities.append(
            Community(
                cluster_id=int(cluster),
                size=int(size),
                years=f"{years[0]}–{years[-1]}" if years else "",
                top_titles=titles[:TOP_TITLES],
                color=colors[int(cluster)],
            )
        )

    max_rank = max(pagerank.values(), default=0.0) or 1.0
    records = _records_by_doi(graph_dir.parent)
    nodes = []
    for node in shown:
        row = by_doi.loc[node] if node in by_doi.index else None
        title = (
            str(row["title"]) if row is not None and is_valid(row["title"]) else node
        )
        authors = (
            str(row["authors"]) if row is not None and is_valid(row["authors"]) else ""
        )
        year = row["year"] if row is not None else ""
        cluster = cluster_of[node]
        tooltip = (
            f"<b>{html.escape(_short(title, 90))}</b><br>"
            f"{html.escape(_short(authors.replace(';', ', '), 80))}"
            f"{' · ' + year if year else ''}<br>"
            f"Community {cluster} · {graph.degree(node)} links"
        )
        nodes.append(
            {
                "id": node,
                "name": _short(title, 40),
                "title": title,
                "authors": authors,
                "year": year,
                "doi": node,
                "cluster": cluster,
                PAPER_TYPE: _groups(records.get(node))[0],
                COLLECTION: _groups(records.get(node))[1],
                "symbolSize": round(8 + 28 * (pagerank[node] / max_rank) ** 0.5, 1),
                "itemStyle": {"color": colors[cluster]},
                "tooltip": tooltip,
            }
        )
    edges = [
        {
            "source": source,
            "target": target,
            "value": int(float(data.get("weight", 1))),
        }
        for source, target, data in graph.edges(data=True)
        if source in shown_set and target in shown_set
    ]

    papers = frame[frame["doi_key"].isin(linked)].copy()
    papers["cluster_id"] = papers["cluster_id"].astype("Int64")
    papers = papers.sort_values(["cluster_id", "pagerank"], ascending=[True, False])
    palettes = {
        COMMUNITY: {str(c): color for c, color in colors.items()},
        PAPER_TYPE: _palette(node[PAPER_TYPE] for node in nodes),
        COLLECTION: _palette(node[COLLECTION] for node in nodes),
    }
    return GraphView(
        records={node: records[node] for node in shown if node in records},
        palettes=palettes,
        name=name,
        total_papers=len(frame),
        linked_papers=len(linked),
        links=graph.number_of_edges(),
        shown_papers=len(shown),
        communities=communities,
        nodes=nodes,
        edges=edges,
        papers=papers[["cluster_id", "pagerank", "title", "year", "authors", "DOI"]],
        graph_file=graph_file,
    )


def _layout(node_count: int) -> dict:
    """Force layout spacing: small graphs spread out, large ones stay in the frame."""
    if node_count <= 30:
        return {
            "zoom": 1.0,
            "force": {"repulsion": 300, "edgeLength": [80, 160], "gravity": 0.1},
        }
    if node_count <= 120:
        return {
            "zoom": 0.7,
            "force": {"repulsion": 90, "edgeLength": [40, 90], "gravity": 0.18},
        }
    return {
        "zoom": 0.6,
        "force": {"repulsion": 70, "edgeLength": [30, 80], "gravity": 0.2},
    }


def group_of(node: dict, color_by: str) -> str:
    """The value of ``node`` for the ``color_by`` choice."""
    return str(node["cluster"] if color_by == COMMUNITY else node.get(color_by, ""))


def compare_groups(view: GraphView, color_by: str) -> pd.DataFrame:
    """Per paper type or collection: papers drawn, links inside and across groups."""
    if color_by == COMMUNITY or not view.nodes:
        return pd.DataFrame()
    of = {node["id"]: group_of(node, color_by) for node in view.nodes}
    rows: dict[str, dict] = {}
    for node in view.nodes:
        group = of[node["id"]]
        row = rows.setdefault(
            group,
            {
                "group": group,
                "papers": 0,
                "communities": set(),
                "inside": 0,
                "across": 0,
            },
        )
        row["papers"] += 1
        row["communities"].add(node["cluster"])
    for edge in view.edges:
        a, b = of.get(edge["source"]), of.get(edge["target"])
        if a is None or b is None:
            continue
        if a == b:
            rows[a]["inside"] += 1
        else:
            rows[a]["across"] += 1
            rows[b]["across"] += 1
    table = pd.DataFrame(
        [{**row, "communities": len(row["communities"])} for row in rows.values()]
    )
    return table.sort_values("papers", ascending=False).rename(
        columns={
            "group": COLOR_BY[color_by],
            "papers": "Papers drawn",
            "communities": "Communities",
            "inside": "Links inside",
            "across": "Links to other groups",
        }
    )


def chart_options(
    view: GraphView, cluster: int | None = None, color_by: str = COMMUNITY
) -> dict:
    """ECharts options of a force-directed graph, optionally one community only.

    ``color_by``: colour the papers by community, paper type or Zotero
    collection (see ``COLOR_BY``), to compare them in the network.
    """
    nodes = [
        node for node in view.nodes if cluster is None or node["cluster"] == cluster
    ]
    kept = {node["id"] for node in nodes}
    # Label the most central papers only, so the drawing stays readable.
    labelled = {node["id"] for node in nodes[:10]}
    palette = view.palettes.get(color_by) or {}
    data = [
        {
            **node,
            "label": {"show": node["id"] in labelled},
            "itemStyle": {
                "color": palette.get(
                    group_of(node, color_by), node["itemStyle"]["color"]
                )
            },
        }
        for node in nodes
    ]
    links = [
        {
            **edge,
            "lineStyle": {"width": min(1 + edge["value"], 6)},
        }
        for edge in view.edges
        if edge["source"] in kept and edge["target"] in kept
    ]
    return {
        "tooltip": {
            ":formatter": (
                "p => p.dataType === 'node' ? p.data.tooltip"
                " : 'Weight: ' + p.data.value"
            )
        },
        "series": [
            {
                "type": "graph",
                "layout": "force",
                "roam": True,
                "draggable": True,
                "data": data,
                "links": links,
                **_layout(len(data)),
                "label": {"position": "right", "fontSize": 10},
                "lineStyle": {"color": "#9aa0a6", "opacity": 0.5, "curveness": 0.1},
                "emphasis": {"focus": "adjacency", "lineStyle": {"opacity": 0.9}},
            }
        ],
    }
