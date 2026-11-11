"""Cluster summarization module for SciLEx graph analysis results.

Produces statistical summaries and optional LLM narratives for each
detected community, with Markdown + Mermaid output for Obsidian.
"""

from scilex.summarize.report import generate_report
from scilex.summarize.stats import compute_cluster_stats

__all__ = [
    "compute_cluster_stats",
    "generate_report",
]
