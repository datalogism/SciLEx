"""Add the papers of a BibTeX file to a review.

Each entry becomes a row of ``aggregated_results.csv`` (``archive`` =
``BibTeX``), with the same columns as collected papers. Papers the review
already has (same DOI, else same title and year) are skipped, so a file can be
imported again after adding entries to it. The previous results are backed up
first, and the new papers are dated in the paper log.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from scilex.constants import normalize_doi
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

ARCHIVE = "BibTeX"
ORIGIN_COLUMN = "extension_origin"  # same column as scilex.gui.services.extend

# BibTeX / BibLaTeX entry type -> Zotero item type (as SciLEx writes it).
ITEM_TYPES = {
    "article": "journalArticle",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "proceedings": "book",
    "book": "book",
    "inbook": "bookSection",
    "incollection": "bookSection",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "dataset": "dataset",
    "software": "computerProgram",
    "online": "webpage",
}


class BibtexImportError(ValueError):
    """The file is not a usable BibTeX file."""


@dataclass
class BibtexImport:
    """Outcome of :func:`import_bibtex`."""

    entries: int = 0
    added: int = 0
    already_there: int = 0
    skipped: list[str] = field(default_factory=list)  # entry keys without a title
    warnings: list[str] = field(default_factory=list)

    def message(self) -> str:
        """One-line summary for the user."""
        text = f"{self.added} new papers added from {self.entries} BibTeX entries"
        if self.already_there:
            text += f" ({self.already_there} already in the review)"
        text += "."
        if self.skipped:
            text += f" {len(self.skipped)} entries without a title were skipped."
        return text


def _clean(value: str) -> str:
    """Remove BibTeX braces and collapse spaces."""
    value = re.sub(r"(?<!\\)[{}]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _person(name: str) -> str:
    """ "Last, First" -> "First Last"."""
    parts = [part.strip() for part in name.split(",")]
    if len(parts) == 2 and all(parts):
        return f"{parts[1]} {parts[0]}"
    if len(parts) == 3 and all(parts):  # "Last, Jr, First"
        return f"{parts[2]} {parts[0]} {parts[1]}"
    return name.strip()


def _authors(value: str) -> str:
    names = re.split(r"\s+and\s+", value, flags=re.IGNORECASE)
    return ";".join(_person(name) for name in names if name.strip())


def _keywords(value: str) -> str:
    """BibTeX keywords (Zotero tags): ";"-separated when they are, else ","."""
    separator = ";" if ";" in value else ","
    return ";".join(part.strip() for part in value.split(separator) if part.strip())


def _item_type(entry_type: str, fields: dict[str, str]) -> str:
    entry_type = entry_type.lower()
    if entry_type in ITEM_TYPES:
        return ITEM_TYPES[entry_type]
    archive = fields.get("archiveprefix", "") + fields.get("journal", "")
    if "arxiv" in archive.lower() or fields.get("eprint"):
        return "preprint"
    return "document"


def entry_to_row(entry_type: str, fields: dict[str, str]) -> dict:
    """Map one BibTeX entry (lowercased field names) to a results row."""
    fields = {name.lower(): _clean(value) for name, value in fields.items() if value}
    date = fields.get("date") or fields.get("year", "")
    if fields.get("year") and fields.get("month") and not fields.get("date"):
        date = f"{fields['year']}-{fields['month']}"
    doi = fields.get("doi", "")
    url = fields.get("url", "")
    if (
        not url
        and fields.get("eprint")
        and "arxiv" in fields.get("archiveprefix", "").lower()
    ):
        url = f"https://arxiv.org/abs/{fields['eprint']}"
    row = {
        "title": fields.get("title", ""),
        "authors": _authors(fields.get("author", "")),
        "abstract": fields.get("abstract", ""),
        "date": date,
        "DOI": normalize_doi(doi) or doi if doi else "",
        "url": url,
        "itemType": _item_type(entry_type, fields),
        "journalAbbreviation": fields.get("journal") or fields.get("journaltitle", ""),
        "conferenceName": fields.get("booktitle", "")
        if entry_type.lower() in ("inproceedings", "conference")
        else "",
        "publisher": fields.get("publisher") or fields.get("organization", ""),
        "volume": fields.get("volume", ""),
        "issue": fields.get("number") or fields.get("issue", ""),
        # "--" (or the en dash the LaTeX decoder makes of it) -> "-"
        "pages": re.sub(r"\s*(--|–|—)\s*", "-", fields.get("pages", "")),
        "language": fields.get("language") or fields.get("langid", ""),
        "rights": fields.get("copyright", ""),
        "tags": _keywords(fields.get("keywords", "")),
        "archive": ARCHIVE,
    }
    return {key: value for key, value in row.items() if value}


def parse_bibtex(text: str) -> tuple[list[tuple[str, dict]], list[str]]:
    """Return the ``(entry key, row)`` pairs of a BibTeX text and parser warnings.

    Raises:
        BibtexImportError: If the text holds no BibTeX entry.
    """
    import bibtexparser

    middlewares = []
    try:  # LaTeX accents and commands -> Unicode ({\\'e} -> é)
        from bibtexparser.middlewares import LatexDecodingMiddleware

        middlewares.append(LatexDecodingMiddleware())
    except ImportError:  # pylatexenc missing: keep the raw LaTeX
        pass
    library = bibtexparser.parse_string(text, append_middleware=middlewares)
    warnings = [
        f"Unreadable block at line {block.start_line + 1}"
        for block in library.failed_blocks
    ]
    if not library.entries:
        raise BibtexImportError(
            "No BibTeX entry found (expected @article{…}, @inproceedings{…}…)."
        )
    rows = []
    for entry in library.entries:
        fields = {f.key: str(f.value) for f in entry.fields}
        rows.append((entry.key, entry_to_row(entry.entry_type, fields)))
    return rows, warnings


def import_bibtex(review: Review, text: str, filename: str = "") -> BibtexImport:
    """Add the papers of the BibTeX ``text`` the review does not have yet.

    Raises:
        BibtexImportError: If the text holds no BibTeX entry.
    """
    from scilex.gui.services import paper_log
    from scilex.gui.services.extend import backup, read_results, write_results
    from scilex.gui.services.screening import paper_key

    entries, warnings = parse_bibtex(text)
    summary = BibtexImport(entries=len(entries), warnings=warnings)
    previous = read_results(review.results_path)
    known = (
        set()
        if previous is None
        else {paper_key(r) for r in previous.to_dict("records")}
    )
    today = dt.date.today()
    origin = f"bibtex {Path(filename).name} {today.isoformat()}".replace("  ", " ")
    new_rows = []
    for key, row in entries:
        if not row.get("title"):
            summary.skipped.append(key)
            continue
        pkey = paper_key(row)
        if pkey in known:
            summary.already_there += 1
            continue
        known.add(pkey)
        row[ORIGIN_COLUMN] = origin
        new_rows.append(row)
    summary.added = len(new_rows)
    if not new_rows:
        return summary

    added = pd.DataFrame(new_rows)
    if previous is None:
        review.collection_dir.mkdir(parents=True, exist_ok=True)
        merged = added
    else:
        backup(review.results_path)
        if ORIGIN_COLUMN not in previous.columns:
            previous = previous.copy()
            previous[ORIGIN_COLUMN] = ""
        merged = pd.concat([previous, added], ignore_index=True)
    write_results(merged, review.results_path)
    try:
        paper_log.update(review.folder, merged, when=today, fresh=previous is None)
    except OSError:
        logger.warning("Cannot update the paper log", exc_info=True)
    from scilex.gui.services import journal

    journal.append(
        review.folder,
        "import-bibtex",
        used={"file": Path(filename).name},
        generated={
            "entries": summary.entries,
            "added": summary.added,
            "already_there": summary.already_there,
            "results_rows": len(merged),
        },
        message=summary.message(),
    )
    return summary
