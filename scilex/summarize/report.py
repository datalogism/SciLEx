"""Generate Markdown summary report with Mermaid mindmap for clusters."""

import logging
import os

from scilex.summarize.stats import ClusterStats

logger = logging.getLogger(__name__)


def generate_report(
    stats: list[ClusterStats],
    output_path: str,
    collect_name: str = "",
) -> str:
    """Generate a Markdown summary report with Mermaid mindmap.

    Args:
        stats: List of ClusterStats from compute_cluster_stats; clusters of a
            single paper are counted but not listed.
        output_path: Where to write the Markdown file.
        collect_name: Collection name for the report title.

    Returns:
        The report as a string.
    """
    lines = []
    # A paper with no link to the others forms a community of its own: listing
    # hundreds of them would bury the real communities.
    singletons = sum(1 for cs in stats if cs.size <= 1)
    stats = [cs for cs in stats if cs.size > 1]

    # Header
    title = f"Cluster Summary: {collect_name}" if collect_name else "Cluster Summary"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**{len(stats)} communities** detected in the collection.")
    if singletons:
        lines.append(
            f"{singletons} papers without links to the others are left out "
            "(one-paper communities)."
        )
    lines.append("")

    # Mermaid mindmap
    lines.append("## Mindmap")
    lines.append("")
    lines.append("```mermaid")
    lines.append("mindmap")
    lines.append(f"  root(({collect_name or 'Collection'}))")
    for cs in stats:
        label = _cluster_label(cs)
        lines.append(f"    {label}")
        for kw, _count in cs.top_keywords[:5]:
            # Escape special chars for Mermaid
            safe_kw = kw.replace("(", "").replace(")", "").replace('"', "")
            lines.append(f"      {safe_kw}")
    lines.append("```")
    lines.append("")

    # Detailed stats per cluster
    lines.append("## Cluster Details")
    lines.append("")

    for cs in stats:
        lines.append(f"### Cluster {cs.cluster_id} ({cs.size} papers)")
        lines.append("")

        # Year range
        yr_min, yr_max = cs.year_range
        if yr_min and yr_max:
            lines.append(f"**Years:** {yr_min}–{yr_max}")
            lines.append("")

        # Hub paper
        if cs.hub_paper:
            lines.append(
                f"**Hub paper:** {cs.hub_paper} (PageRank: {cs.hub_pagerank:.4f})"
            )
            lines.append("")

        # Keywords
        if cs.top_keywords:
            lines.append("**Top keywords:**")
            for kw, count in cs.top_keywords:
                lines.append(f"- {kw} ({count})")
            lines.append("")

        # Authors
        if cs.top_authors:
            lines.append("**Top authors:**")
            for author, count in cs.top_authors:
                lines.append(f"- {author} ({count})")
            lines.append("")

        lines.append("---")
        lines.append("")

    report = "\n".join(lines)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Summary report: {output_path}")
    return report


def _cluster_label(cs: ClusterStats) -> str:
    """Generate a short label for a cluster in the mindmap."""
    label = cs.top_keywords[0][0] if cs.top_keywords else f"Cluster {cs.cluster_id}"
    return f"Cluster {cs.cluster_id}: {label}"
