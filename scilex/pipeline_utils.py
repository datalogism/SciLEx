"""Shared utilities for SciLEx pipeline entry points.

Centralizes common boilerplate: config loading, collect-dir resolution,
DOI extraction, cluster CSV detection, and keyword parsing.
"""

import os

import pandas as pd

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import is_valid, normalize_path_component
from scilex.settings.resolve import resolve_legacy_configs, resolve_main_config


def load_main_config() -> dict:
    """Resolve the main configuration (``scilex.yml`` or legacy) as a legacy dict."""
    return resolve_main_config()


def load_main_and_api_configs() -> tuple[dict, dict]:
    """Resolve ``(main_config, api_config)`` from ``scilex.yml`` / ``keys.yml``."""
    return resolve_legacy_configs()


def resolve_collect_dir(config: dict) -> str:
    """Derive the collection output directory from config.

    Args:
        config: Parsed ``scilex.config.yml`` dict.

    Returns:
        Absolute path to ``{output_dir}/{collect_name}/``.

    Raises:
        ValueError: If ``collect_name`` is missing from config.
    """
    if "collect_name" not in config:
        raise ValueError("collect_name not specified in scilex.config.yml")
    output_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
    collect_name = normalize_path_component(config["collect_name"])
    return os.path.join(output_dir, collect_name)


def extract_corpus_dois(df: pd.DataFrame, doi_column: str = "DOI") -> set[str]:
    """Extract the set of valid, stripped DOI strings from a DataFrame."""
    return {str(d).strip() for d in df[doi_column] if is_valid(d) and str(d).strip()}


CLUSTER_GRAPHS = ("cocitation", "coupling")


def find_clusters_csv(analysis_dir: str, graph: str | None = None) -> str:
    """Find a clusters CSV in *analysis_dir*.

    Args:
        analysis_dir: Directory of the graph analysis outputs.
        graph: ``"cocitation"`` or ``"coupling"`` for that graph's clusters;
            None prefers ``clusters_cocitation.csv`` and falls back to
            ``clusters_coupling.csv``.

    Raises:
        FileNotFoundError: If no matching clusters CSV exists.
    """
    graphs = [graph] if graph else list(CLUSTER_GRAPHS)
    candidates = [os.path.join(analysis_dir, f"clusters_{name}.csv") for name in graphs]
    csv_path = next((p for p in candidates if os.path.exists(p)), None)
    if csv_path is None:
        which = f"{graph} clusters CSV" if graph else "clusters CSV"
        raise FileNotFoundError(
            f"No {which} found in {analysis_dir}. Run scilex-analyze first."
        )
    return csv_path


def parse_keyword_values(val: str) -> list[str]:
    """Parse a raw keyword/tag cell value into cleaned keyword strings.

    Handles semicolon and comma separators, strips tag prefixes like
    ``"TASK:"``, and filters out empty or very short tokens.
    """
    keywords = []
    for kw in str(val).replace(",", ";").split(";"):
        kw = kw.strip()
        if ":" in kw:
            kw = kw.split(":", 1)[1].strip()
        if kw and len(kw) > 1:
            keywords.append(kw)
    return keywords
