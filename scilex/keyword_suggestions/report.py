"""Generate keyword suggestion reports in Markdown and YAML formats."""

import logging
import os

import yaml

logger = logging.getLogger(__name__)

SNIPPET_HEADER = (
    "# Suggested terms for scilex.yml. As bonus_keywords they raise the\n"
    "# relevance score; add a term to a keyword group to search for it.\n"
)


def generate_keyword_report(
    suggestions: list[dict],
    output_dir: str,
    collect_name: str = "",
) -> tuple[str, str]:
    """Generate Markdown report and YAML snippet for keyword suggestions.

    Args:
        suggestions: List of suggestion dicts from extract_suggestions.
        output_dir: Directory to write output files.
        collect_name: Collection name for the report title.

    Returns:
        Tuple of (markdown_path, yaml_path).
    """
    os.makedirs(output_dir, exist_ok=True)

    md_path = os.path.join(output_dir, "keyword_suggestions.md")
    yml_path = os.path.join(output_dir, "keyword_suggestions.yml")

    # Markdown report
    md_lines = []
    title = (
        f"Keyword Suggestions: {collect_name}"
        if collect_name
        else "Keyword Suggestions"
    )
    md_lines.append(f"# {title}")
    md_lines.append("")
    md_lines.append(f"**{len(suggestions)} new terms** suggested for future searches.")
    md_lines.append("")

    if suggestions:
        md_lines.append("| Term | Frequency | Clusters |")
        md_lines.append("|------|-----------|----------|")
        for s in suggestions:
            clusters = ", ".join(str(c) for c in s["cluster_ids"])
            md_lines.append(f"| {s['term']} | {s['frequency']} | {clusters} |")
        md_lines.append("")

    md_content = "\n".join(md_lines)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # YAML snippet in the scilex.yml shape: bonus keywords only boost the
    # ranking; a term must join a keyword group to be searched.
    yml_content = SNIPPET_HEADER + yaml.safe_dump(
        {"search": {"bonus_keywords": [s["term"] for s in suggestions]}},
        allow_unicode=True,
        sort_keys=False,
    )
    with open(yml_path, "w", encoding="utf-8") as f:
        f.write(yml_content)

    logger.info(f"Keyword report: {md_path}")
    logger.info(f"YAML snippet: {yml_path}")
    return md_path, yml_path
