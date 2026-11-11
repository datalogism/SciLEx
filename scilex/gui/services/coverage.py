"""Accessibility and coverage of the papers of a review.

For each paper: its access (open with a PDF, open, restricted, unknown),
whether it has a DOI, a code repository (GitHub…), citation data, and whether
it is cited in the citation network (by any paper, and by a paper of the
corpus). The rates are given for the whole corpus and per group: Zotero
collection (sub-corpus) or paper type (``PAPER_TYPE:<type>`` tags).

No network: reads the aggregated results and the citation caches.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from scilex import review_tags
from scilex.constants import is_valid, normalize_doi

OUTPUT_DIRNAME = "coverage_analysis"
REPORT_FILENAME = "coverage_report.md"
PAPERS_FILENAME = "coverage_per_paper.csv"
RATES_FILENAME = "coverage_rates.csv"
CHART_FILENAME = "coverage_rates.png"
ACCESS_CHART_FILENAME = "coverage_access.png"

PAPER_TYPE_TAG = "PAPER_TYPE:"
GROUP_BY = {
    "none": "Whole corpus only",
    "collection": "Zotero collection (sub-corpus)",
    "paper_type": "Paper type (Benchmark, Review, Dataset, Model)",
}
NO_GROUP = "(none)"

OPEN_PDF, OPEN, RESTRICTED, UNKNOWN = (
    "open (PDF)",
    "open",
    "restricted",
    "unknown",
)
ACCESS_LEVELS = (OPEN_PDF, OPEN, RESTRICTED, UNKNOWN)
# The rates of the report, in order: column -> label.
INDICATORS = {
    "accessible": "Accessible (open access)",
    "has_doi": "Has a DOI",
    "has_code": "Has a code repository",
    "has_citation_data": "Has citation data",
    "cited": "Cited (by any paper)",
    "cited_in_corpus": "Cited by a paper of the corpus",
}

_OPEN_RIGHTS = re.compile(
    r"open|creativecommons|\bcc[- ]?(by|0)\b|public domain", re.IGNORECASE
)
_RESTRICTED_RIGHTS = re.compile(r"restricted|closed|subscription", re.IGNORECASE)
_ARXIV = re.compile(r"arxiv\.org|10\.48550/arxiv", re.IGNORECASE)
_CODE_HOST = re.compile(r"github\.com|gitlab\.|bitbucket\.org|codeberg\.org", re.I)
CODE_COLUMNS = ("github_repo", "lpwc_repositories", "pwc_repository")
LICENCE_COLUMNS = ("rights", "license", "licence", "crossref_license")


def _text(row: pd.Series, column: str) -> str:
    value = row.get(column)
    return str(value) if is_valid(value) else ""


def access_of(row: pd.Series) -> str:
    """Access level of one paper (see ``ACCESS_LEVELS``)."""
    tags = review_tags.split_tags(row.get("tags"))
    if _text(row, "pdf_url") or "HavePDF" in tags:
        return OPEN_PDF
    rights = " ".join(_text(row, c) for c in LICENCE_COLUMNS)
    if _RESTRICTED_RIGHTS.search(rights):
        return RESTRICTED
    where = " ".join(_text(row, c) for c in ("url", "DOI"))
    if _OPEN_RIGHTS.search(rights) or _ARXIV.search(where):
        return OPEN
    return UNKNOWN


def has_code(row: pd.Series) -> bool:
    """True when the paper links to a code repository."""
    if any(_text(row, c) for c in CODE_COLUMNS):
        return True
    tags = review_tags.split_tags(row.get("tags"))
    if "HaveGithub" in tags or any(t.startswith("GITHUB_STARS:") for t in tags):
        return True
    return bool(_CODE_HOST.search(_text(row, "url")))


def groups_of(row: pd.Series, group_by: str) -> list[str]:
    """The groups a paper belongs to (see :mod:`scilex.gui.services.compare`)."""
    from scilex.gui.services.compare import groups_of as compare_groups

    return compare_groups(row, group_by) if group_by != "none" else []


def per_paper(
    data: pd.DataFrame,
    references: dict[str, list[str]],
    citers: dict[str, list[str]],
    group_by: str = "none",
) -> pd.DataFrame:
    """One row per paper with its access level and the indicators (booleans)."""
    dois = [normalize_doi(d) if is_valid(d) else None for d in data.get("DOI", [])]
    corpus = {d for d in dois if d}
    # Papers of the corpus cited by another paper of the corpus.
    cited_inside: set[str] = set()
    for doi in corpus:
        cited_inside.update(
            r for r in references.get(doi, []) if r in corpus and r != doi
        )
        if any(c in corpus and c != doi for c in citers.get(doi, [])):
            cited_inside.add(doi)
    rows = []
    for (_, row), doi in zip(data.iterrows(), dois or [None] * len(data), strict=False):
        access = access_of(row)
        in_corpus_count = row.get("metric_cited_in_corpus")
        cited_in_corpus = bool(doi and doi in cited_inside)
        if not cited_in_corpus and is_valid(in_corpus_count):
            with contextlib.suppress(TypeError, ValueError):
                cited_in_corpus = float(in_corpus_count) > 0
        cited = bool(doi and citers.get(doi)) or cited_in_corpus
        if not cited and is_valid(row.get("metric_citations")):
            with contextlib.suppress(TypeError, ValueError):
                cited = float(row.get("metric_citations")) > 0
        rows.append(
            {
                "title": _text(row, "title"),
                "DOI": doi or "",
                "access": access,
                "accessible": access in (OPEN_PDF, OPEN),
                "has_doi": bool(doi),
                "has_code": has_code(row),
                "has_citation_data": bool(doi and (doi in references or doi in citers)),
                "cited": cited,
                "cited_in_corpus": cited_in_corpus,
                "groups": ";".join(groups_of(row, group_by)),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["title", "DOI", "access", *INDICATORS, "groups"],
    )


def rates(papers: pd.DataFrame, group_by: str = "none") -> pd.DataFrame:
    """Rates (%) of each indicator for the corpus, then for each group."""

    def line(name: str, part: pd.DataFrame) -> dict:
        out = {"group": name, "papers": len(part)}
        for column in INDICATORS:
            out[column] = round(100 * part[column].mean(), 1) if len(part) else 0.0
        for level in ACCESS_LEVELS:
            out[f"access: {level}"] = int((part["access"] == level).sum())
        return out

    lines = [line("All papers", papers)]
    if group_by != "none" and len(papers):
        exploded = papers.assign(group=papers["groups"].str.split(";")).explode("group")
        for name in sorted(exploded["group"].dropna().unique(), key=str.casefold):
            lines.append(line(name, exploded[exploded["group"] == name]))
    return pd.DataFrame(lines)


def report_markdown(table: pd.DataFrame, group_by: str, citation_data: bool) -> str:
    """The Markdown report: rates per group, then access levels."""
    header = ["Group", "Papers", *INDICATORS.values()]
    out = [
        "# Accessibility and coverage",
        "",
        f"Grouped by: {GROUP_BY.get(group_by, group_by)}.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for _, row in table.iterrows():
        cells = [str(row["group"]), str(row["papers"])]
        cells += [f"{row[c]:.1f} %" for c in INDICATORS]
        out.append("| " + " | ".join(cells) + " |")
    out += ["", "## Access", "", "| Group | " + " | ".join(ACCESS_LEVELS) + " |"]
    out.append("|" + "---|" * (len(ACCESS_LEVELS) + 1))
    for _, row in table.iterrows():
        counts = [str(row[f"access: {level}"]) for level in ACCESS_LEVELS]
        out.append(f"| {row['group']} | " + " | ".join(counts) + " |")
    out += [
        "",
        "Access: *open (PDF)* has a PDF link (or the HavePDF tag); *open* has an "
        "open licence or is on arXiv; *restricted* is marked so by its source; "
        "*unknown* says nothing. Enrich with Crossref to fill licences.",
    ]
    if not citation_data:
        out += [
            "",
            "No citation data yet: the citation rates use only the metric_* "
            "columns. Fetch the citations in ⑥ Enrich (Citations) for them.",
        ]
    return "\n".join(out) + "\n"


def _charts(table: pd.DataFrame, folder: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    shown = table.head(12)  # beyond, the bars are unreadable
    labels = list(INDICATORS.values())
    fig, ax = plt.subplots(figsize=(10, 0.5 + 0.45 * len(labels) * len(shown)))
    height = 0.8 / max(len(shown), 1)
    for index, (_, row) in enumerate(shown.iterrows()):
        values = [row[c] for c in INDICATORS]
        positions = [i + index * height for i in range(len(labels))]
        ax.barh(
            positions, values, height=height, label=f"{row['group']} ({row['papers']})"
        )
    ax.set_yticks([i + 0.4 - height / 2 for i in range(len(labels))])
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of the papers")
    ax.legend(fontsize="small", loc="lower right")
    fig.tight_layout()
    path = folder / CHART_FILENAME
    fig.savefig(path, dpi=110)
    plt.close(fig)
    files.append(path)

    fig, ax = plt.subplots(figsize=(10, 0.8 + 0.4 * len(shown)))
    left = [0] * len(shown)
    for level in ACCESS_LEVELS:
        counts = [
            100 * row[f"access: {level}"] / row["papers"] if row["papers"] else 0
            for _, row in shown.iterrows()
        ]
        ax.barh(list(shown["group"]), counts, left=left, label=level)
        left = [a + b for a, b in zip(left, counts, strict=True)]
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of the papers")
    ax.legend(fontsize="small", ncol=len(ACCESS_LEVELS), loc="upper center")
    fig.tight_layout()
    path = folder / ACCESS_CHART_FILENAME
    fig.savefig(path, dpi=110)
    plt.close(fig)
    files.append(path)
    return files


def run(
    data: pd.DataFrame,
    collect_dir: Path,
    progress: Callable[[int, str], None],
    group_by: str = "none",
) -> tuple[str, list[Path]]:
    """Write the report, tables and charts in ``collect_dir/coverage_analysis``."""
    from scilex.graph_analysis.loader import load_citation_caches

    progress(10, "Reading the citation network…")
    try:
        references, citers = load_citation_caches(str(collect_dir))
        citation_data = True
    except FileNotFoundError:
        references, citers, citation_data = {}, {}, False
    progress(40, "Checking each paper…")
    papers = per_paper(data, references, citers, group_by)
    table = rates(papers, group_by)
    folder = Path(collect_dir) / OUTPUT_DIRNAME
    folder.mkdir(exist_ok=True)
    progress(70, "Drawing the charts…")
    report = folder / REPORT_FILENAME
    report.write_text(report_markdown(table, group_by, citation_data), encoding="utf-8")
    table.to_csv(folder / RATES_FILENAME, index=False)
    papers.to_csv(folder / PAPERS_FILENAME, index=False)
    files = [report, *_charts(table, folder), folder / PAPERS_FILENAME]
    whole = table.iloc[0]
    message = (
        f"{len(papers)} papers: {whole['accessible']:.0f} % accessible, "
        f"{whole['has_doi']:.0f} % with a DOI, {whole['has_code']:.0f} % with code, "
        f"{whole['cited_in_corpus']:.0f} % cited inside the corpus."
    )
    return message, files
