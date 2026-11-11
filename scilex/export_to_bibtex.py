"""
BibTeX Export for SciLEx - Alternative to Zotero push.

Exports aggregated paper data to BibTeX format for pipeline integration.
Supports DOI-based citation keys and direct PDF download links.
"""

import argparse
import logging
import os
import re
import sys

import pandas as pd

from scilex.config_defaults import DEFAULT_OUTPUT_DIR
from scilex.constants import (
    is_valid,
    normalize_doi,
    normalize_path_component,
    split_semicolon_field,
)
from scilex.io_utils import load_aggregated_data
from scilex.logging_config import setup_logging
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.resolve import resolve_main_config
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError

logger = logging.getLogger(__name__)


def safe_get(row, field):
    """Safely get a field from a pandas Series or dict-like object."""
    try:
        if hasattr(row, field):
            return getattr(row, field)
        return row.get(field) if hasattr(row, "get") else None
    except (AttributeError, KeyError, TypeError):
        return None


# ItemType to BibTeX entry type mapping
ITEMTYPE_TO_BIBTEX = {
    "journalArticle": "article",
    "conferencePaper": "inproceedings",
    "bookSection": "incollection",
    "book": "book",
    "preprint": "misc",
    "Manuscript": "misc",  # Use @misc instead of @unpublished for proper DOI field support in Zotero
}

# Special characters that need escaping in BibTeX
BIBTEX_SPECIAL_CHARS = {
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}

_SPECIAL_CHARS_PATTERN = re.compile(
    "[" + "".join(re.escape(char) for char in BIBTEX_SPECIAL_CHARS) + "]"
)


BIBTEX_PLAIN_FILENAME = "aggregated_results.bib"
BIBTEX_CITATIONS_FILENAME = "aggregated_results_with_citations.bib"


def load_config(collect_name: str | None = None, output_dir: str | None = None) -> dict:
    """Load scilex.config.yml configuration, with optional CLI overrides.

    Args:
        collect_name: Override collection name from CLI
        output_dir: Override output directory from CLI

    Returns:
        Configuration dictionary
    """
    config = resolve_main_config()

    # Override with CLI arguments if provided
    if collect_name:
        config["collect_name"] = collect_name
    if output_dir:
        config["output_dir"] = output_dir

    return config


def parse_tags(tags_str: str) -> list[str]:
    """Parse semicolon-separated tags from CSV.

    Args:
        tags_str: Semicolon-separated tags (e.g., "TASK:NER;PTM:BERT")

    Returns:
        List of tag strings
    """
    return split_semicolon_field(tags_str)


# Enrichment tag prefixes -> dedicated BibTeX fields (read by the RDF exporter).
TAG_PREFIX_TO_FIELD: dict[str, str] = {
    "TASK:": "task",
    "PTM:": "ptm",
    "ARCHI:": "archi",
    "DATASET:": "hfdataset",
    "FRAMEWORK:": "framework",
    "GITHUB_STARS:": "githubstars",
    "CITED_BY_DATASET:": "citingdatasets",
}


def classify_tags(tags_list: list[str]) -> dict[str, list[str]]:
    """Split tags into enrichment fields by prefix; unprefixed tags go to "keywords".

    Args:
        tags_list: List of tag strings, possibly prefixed (e.g. "TASK:NER").

    Returns:
        Dict mapping BibTeX field names to lists of stripped tag values.
    """
    result: dict[str, list[str]] = {"keywords": []}
    result.update({field_name: [] for field_name in TAG_PREFIX_TO_FIELD.values()})
    for tag in tags_list:
        for prefix, field_name in TAG_PREFIX_TO_FIELD.items():
            if tag.startswith(prefix):
                result[field_name].append(tag[len(prefix) :])
                break
        else:
            result["keywords"].append(tag)
    return result


def escape_bibtex(text: str) -> str:
    """
    Escape special BibTeX characters in text.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for BibTeX
    """
    if not is_valid(text):
        return ""

    # Single pass: sequential str.replace would re-escape the backslashes
    # introduced by earlier replacements.
    return _SPECIAL_CHARS_PATTERN.sub(
        lambda match: BIBTEX_SPECIAL_CHARS[match.group()], str(text)
    )


def _escape_url(url) -> str:
    """Escape a URL-like value for a BibTeX field.

    Only ``%``, ``#`` and unbalanced braces are escaped; ``_`` and ``~`` are
    legal in URLs and stay untouched.
    """
    if not is_valid(url):
        return ""

    chars = list(str(url))
    open_brace_positions = []
    for position, char in enumerate(chars):
        if char == "{":
            open_brace_positions.append(position)
        elif char == "}":
            if open_brace_positions:
                open_brace_positions.pop()
            else:
                chars[position] = r"\}"
    for position in open_brace_positions:
        chars[position] = r"\{"

    return "".join(chars).replace("%", r"\%").replace("#", r"\#")


def format_authors(authors_str: str) -> str:
    """
    Format semicolon-separated author list for BibTeX.

    Converts "John Smith;Jane Doe" to "John Smith and Jane Doe"

    Args:
        authors_str: Semicolon-separated author names

    Returns:
        BibTeX-formatted author list
    """
    if not is_valid(authors_str):
        return ""

    return " and ".join(split_semicolon_field(authors_str))


def format_pages(pages_str: str) -> str:
    """
    Format page range for BibTeX (use en-dash).

    Converts "123-456" to "123--456"

    Args:
        pages_str: Page range string

    Returns:
        BibTeX-formatted page range
    """
    if not is_valid(pages_str):
        return ""

    pages_str = str(pages_str).strip()
    # Any run of hyphens / en / em dashes becomes the BibTeX range "--"
    return re.sub(r"\s*[-\u2013\u2014]+\s*", "--", pages_str)


def extract_year(date_str: str) -> str:
    """
    Extract year from date string.

    Handles ISO dates (YYYY-MM-DD), years (YYYY), and partial dates.

    Args:
        date_str: Date string in various formats

    Returns:
        Year as string (YYYY)
    """
    if not is_valid(date_str):
        return ""

    date_str = str(date_str).strip()

    # Extract first 4 consecutive digits (year)
    match = re.search(r"\d{4}", date_str)
    if match:
        return match.group(0)

    return ""


_INVALID_KEY_CHARS = re.compile(r"[^A-Za-z0-9_:-]")


def _collision_suffix(counter: int) -> str:
    """Return the collision suffix for a 1-based counter: a..z, aa, ab, ..."""
    letters = ""
    while counter > 0:
        counter, remainder = divmod(counter - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def generate_citation_key(doi: str, row: pd.Series, used_keys: set) -> str:
    """
    Generate unique DOI-based citation key.

    Format: DOI with special chars replaced by underscores
    Example: "10.1021/acsomega.2c06948" -> "10_1021_acsomega_2c06948"

    Args:
        doi: DOI string
        row: Paper row data
        used_keys: Set of already-used keys (for collision detection)

    Returns:
        Unique citation key
    """
    base_key = None

    # Try DOI first (preferred)
    if is_valid(doi):
        doi = str(doi).strip()
        # Replace special characters with underscores
        base_key = doi.replace(".", "_").replace("/", "_")
        # Clean up multiple underscores
        while "__" in base_key:
            base_key = base_key.replace("__", "_")

    # Fallback: author-year format
    if not base_key:
        authors_str = safe_get(row, "authors")
        if is_valid(authors_str):
            # Get first author's last name
            first_author = str(authors_str).split(";")[0].strip()
            if "," in first_author:
                # "Last, First" format
                last_name = first_author.split(",")[0].strip()
            elif first_author:
                last_name = first_author.split()[-1]
            else:
                last_name = "Unknown"
        else:
            last_name = "Unknown"

        year = extract_year(safe_get(row, "date"))
        title = safe_get(row, "title")
        first_word = str(title).split()[0] if is_valid(title) else "Paper"

        base_key = f"{last_name}{year}_{first_word}"

    base_key = _INVALID_KEY_CHARS.sub("", base_key) or "Paper"

    # Ensure uniqueness
    final_key = base_key
    counter = 0
    while final_key in used_keys:
        counter += 1
        # Add suffix: a..z, then aa, ab, ...
        suffix = _collision_suffix(counter)
        final_key = f"{base_key}_{suffix}"

    used_keys.add(final_key)
    return final_key


def _tag_field_lines(tags_str) -> list[str]:
    """Build BibTeX lines for tags: one field per enrichment prefix, then plain keywords."""
    classified = classify_tags(parse_tags(tags_str))
    lines = []
    for field_name in [*TAG_PREFIX_TO_FIELD.values(), "keywords"]:
        values = classified[field_name]
        if values:
            joined = ", ".join(escape_bibtex(value) for value in values)
            lines.append(f"  {field_name} = {{{joined}}},")
    return lines


# (bibtex_field, row_field, formatter, allowed_entry_types or None for all).
# Order is the output order. Title, author and year are handled separately
# because author has a mandatory "Unknown" fallback and year is derived.
_PUBLISHER_TYPES = ("book", "incollection", "inproceedings")
_ENTRY_FIELDS = [
    ("journal", "journalAbbreviation", lambda v: escape_bibtex(v), ("article",)),
    ("booktitle", "conferenceName", lambda v: escape_bibtex(v), ("inproceedings",)),
    ("volume", "volume", lambda v: escape_bibtex(str(v)), None),
    ("number", "issue", lambda v: escape_bibtex(str(v)), None),
    ("pages", "pages", format_pages, None),
    ("publisher", "publisher", lambda v: escape_bibtex(v), _PUBLISHER_TYPES),
    ("series", "serie", lambda v: escape_bibtex(str(v)), None),
    ("doi", "DOI", lambda v: escape_bibtex(normalize_doi(v) or str(v)), None),
    ("url", "url", _escape_url, None),
    ("file", "pdf_url", _escape_url, None),
    ("abstract", "abstract", lambda v: escape_bibtex(str(v)), None),
    ("language", "language", lambda v: escape_bibtex(str(v)), None),
    ("copyright", "rights", lambda v: escape_bibtex(str(v)), None),
    ("archiveprefix", "archive", lambda v: escape_bibtex(str(v)), None),
    ("eprint", "archiveID", lambda v: escape_bibtex(str(v)), None),
    # Falls back to the legacy "hf_url" column for old aggregated CSVs
    ("pwcurl", "pwc_url", _escape_url, None),
    ("howpublished", "github_repo", _escape_url, None),
    # SciLEx internal fields, consumed by the RDF exporter
    ("relevancescore", "relevance_score", str, None),
    ("citationcount", "nb_citation", str, None),
]


def format_bibtex_entry(
    row: pd.Series,
    citation_key: str,
    references: list[str] | None = None,
    cited_by: list[str] | None = None,
) -> str:
    """Generate complete BibTeX entry for a paper.

    Args:
        row: Paper data row
        citation_key: Citation key for the entry
        references: Optional cited DOIs (outgoing), exported as ``bibo:cites`` in RDF
        cited_by: Optional citing DOIs (incoming), exported as ``bibo:citedBy`` in RDF

    Returns:
        Formatted BibTeX entry string
    """
    entry_type = ITEMTYPE_TO_BIBTEX.get(safe_get(row, "itemType"), "misc")
    lines = [f"@{entry_type}{{{citation_key},"]

    title = safe_get(row, "title")
    if is_valid(title):
        lines.append(f"  title = {{{escape_bibtex(title)}}},")

    # BibTeX requires author or organization
    authors_str = safe_get(row, "authors")
    authors = (
        escape_bibtex(format_authors(authors_str))
        if is_valid(authors_str)
        else "Unknown"
    )
    lines.append(f"  author = {{{authors}}},")

    year = extract_year(safe_get(row, "date"))
    if year:
        lines.append(f"  year = {{{year}}},")

    for bibtex_field, row_field, formatter, allowed_types in _ENTRY_FIELDS:
        if allowed_types is not None and entry_type not in allowed_types:
            continue
        value = safe_get(row, row_field)
        if not is_valid(value) and bibtex_field == "pwcurl":
            value = safe_get(row, "hf_url")
        if not is_valid(value):
            continue
        formatted = formatter(value)
        # Skip fields whose formatter yields nothing (e.g. empty tag list)
        if formatted:
            lines.append(f"  {bibtex_field} = {{{formatted}}},")

    tags_str = safe_get(row, "tags")
    if is_valid(tags_str):
        lines.extend(_tag_field_lines(tags_str))

    if references:
        lines.append(f"  references = {{{', '.join(references)}}},")
    if cited_by:
        lines.append(f"  cited_by = {{{', '.join(cited_by)}}},")

    # Close entry (remove trailing comma from last line)
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")

    return "\n".join(lines)


def export_to_bibtex(data: pd.DataFrame, config: dict) -> str:
    """
    Export aggregated data to BibTeX file.

    Args:
        data: DataFrame with aggregated papers
        config: Configuration dictionary

    Returns:
        Path to generated BibTeX file
    """
    output_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
    dir_collect = os.path.join(
        output_dir, normalize_path_component(config["collect_name"])
    )

    # Output file path
    output_file = os.path.join(dir_collect, BIBTEX_PLAIN_FILENAME)

    logger.info(f"Exporting {len(data)} papers to BibTeX")
    logger.info(f"Output file: {output_file}")

    entries = []
    used_keys = set()
    skipped = 0

    # Process each paper
    for row in data.itertuples(index=False):
        try:
            # Get citation key
            doi = safe_get(row, "DOI")
            citation_key = generate_citation_key(doi, row, used_keys)

            # Generate BibTeX entry
            entry = format_bibtex_entry(row, citation_key)
            entries.append(entry)

        except Exception as e:
            logger.warning(f"Error processing paper {safe_get(row, 'title')}: {e}")
            skipped += 1
            continue

    # Write to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(entries))
        f.write("\n")

    logger.info(f"Successfully exported {len(entries)} entries to {output_file}")
    if skipped > 0:
        logger.warning(f"Skipped {skipped} papers due to errors")

    return output_file


@exit_on_config_error
def main():
    """Main entry point for BibTeX export."""
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Export aggregated papers to BibTeX format"
    )
    parser.add_argument(
        "--collect-name",
        type=str,
        default=None,
        help="Collection name (overrides scilex.config.yml)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (overrides scilex.config.yml)",
    )

    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    try:
        # Load configuration with CLI overrides
        config = load_config(
            collect_name=args.collect_name,
            output_dir=args.output_dir,
        )

        # Validate required config
        if "collect_name" not in config:
            raise ValueError(
                "collect_name not specified in scilex.config.yml or --collect-name"
            )

        # Load aggregated data
        data = load_aggregated_data(config)

        # Export to BibTeX
        output_file = export_to_bibtex(data, config)

        logger.info(f"BibTeX export complete: {output_file}")
        print(f"\n✓ BibTeX file created: {output_file}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Configuration or data error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during BibTeX export: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
