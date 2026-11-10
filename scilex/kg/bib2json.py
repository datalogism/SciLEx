"""Generic BibLaTeX -> JSON (stage 1 of the scilex-lpwc-ap mapping pipeline).

Port of the profile's ``scripts/bib2json.py`` (iteration 3) to bibtexparser 2
(SciLEx's version; the profile uses 1.x and both cannot be installed together).
The output has the same shape, which is what the profile's RML mapping reads::

    {"source": "...bib", "entries": [{"ID": ..., "ENTRYTYPE": ..., "title": ...}],
     "creators": [{"entry": ID, "role": "author", "position": 1,
                   "family": ..., "given": ..., "suffix": ..., "full": ...}],
     "lists": [{"entry": ID, "field": "keywords", "position": 1, "value": ...}],
     "identifiers": [{"entry": ID, "field": "issn", "position": 1, "value": ...}]}

Like the original it applies only BibLaTeX syntax rules and keeps every field:
LaTeX -> Unicode, case-protection braces removed, name lists split with the BibTeX
name rules (First von Last / von Last, Jr, First) and harmonised across the
library, separated lists (keywords) and multi-valued identifiers (ISSN, ISBN)
split, null tokens ("nan", "None") dropped. Verbatim fields (URLs, DOIs, files)
are not decoded.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

import bibtexparser
from bibtexparser.middlewares.names import parse_single_name_into_parts
from bibtexparser.model import DuplicateFieldKeyBlock
from pylatexenc.latex2text import LatexNodes2Text

logger = logging.getLogger(__name__)

NAME_LIST_FIELDS = ("author", "editor", "bookauthor", "translator")
SEPARATED_LIST_FIELDS = ("keywords",)
# Identifier fields real exports fill with several values ("print, online" ISSN).
MULTI_IDENTIFIER_FIELDS = ("issn", "isbn")
# Field values that mean "no value" (dataframe-based exports write NaN as text).
NULL_TOKENS = {"nan", "none", "null", "n/a"}
# BibLaTeX verbatim fields: no LaTeX inside ("%" in a URL is not a comment).
VERBATIM_FIELDS = frozenset({"url", "urlraw", "doi", "eprint", "file", "pdf", "verba", "verbb"})

_TEXT_COMMANDS = {
    r"\textasciicircum": "^",
    r"\textless": "<",
    r"\textgreater": ">",
    r"\textasciitilde": "~",
    r"\textbackslash": "\\",
}
_DECODER = LatexNodes2Text(math_mode="verbatim")
_LIGATURES = re.compile(r"-{2,3}|''|``|`")


def clean(value: str) -> str:
    """Decode LaTeX escapes and remove BibTeX case-protection braces.

    TeX ligatures are kept as typed, like the profile's decoder does: ``--``
    stays a page-range separator and ``''`` stays two quotes (an empty item of
    the citation lists SciLEx writes as a Python literal).
    """
    for cmd, char in _TEXT_COMMANDS.items():
        value = value.replace(cmd, char)
    kept: dict[str, str] = {}

    def _keep(match: re.Match) -> str:
        token = chr(0xF0000 + len(kept))  # one private-use character: no collision
        kept[token] = match.group(0)
        return token

    value = _LIGATURES.sub(_keep, value)
    try:
        value = _DECODER.latex_to_text(value)
    except Exception:  # pylatexenc is lenient, but never lose a field over it
        value = re.sub(r"(?<!\\)[{}]", "", value)
    for token, text in kept.items():
        value = value.replace(token, text)
    return re.sub(r"\s+", " ", value).strip()


def clean_verbatim(value: str) -> str:
    """Strip the braces BibTeX may wrap a verbatim value in."""
    return value.strip().strip("{}").strip()


def strip_enclosing(value: str) -> str:
    """Remove the braces or quotes enclosing a raw field value, if they enclose all of it."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    if len(value) >= 2 and value[0] == "{" and value[-1] == "}":
        depth = 0
        for index, char in enumerate(value):
            if char == "{" and (index == 0 or value[index - 1] != "\\"):
                depth += 1
            elif char == "}" and value[index - 1] != "\\":
                depth -= 1
                if depth == 0:
                    return value[1:-1] if index == len(value) - 1 else value
    return value


def split_name(name: str) -> dict:
    """Split one BibTeX/BibLaTeX name with the BibTeX rules.

    ``explicit`` records whether the name was written in the comma form, which
    states the family/given split (used by :func:`harmonise_names`).
    """
    raw = name.strip()
    # ", Given Family": empty family part, whole name in the given part; written by
    # SciLEx/Zotero exports that put the whole name in firstName (ORSD D4).
    lossy = re.match(r"^,\s*([^,]+)$", raw)
    if lossy:
        raw = lossy.group(1).strip()
    # ", Given, Family": second lossy form, rewritten as "Family, Given".
    lossy2 = re.match(r"^,\s*([^,]+),\s*([^,]+)$", name.strip())
    if lossy2:
        raw = f"{lossy2.group(2).strip()}, {lossy2.group(1).strip()}"
        lossy = lossy2
    try:
        parts = parse_single_name_into_parts(raw, strict=False)
        first, von, last, jr = parts.first, parts.von, parts.last, parts.jr
    except Exception:  # unbalanced braces etc.: keep the whole name as family name
        first, von, last, jr = [], [], [raw], []
    given = clean(" ".join(first))
    family = clean(" ".join(von + last))
    suffix = clean(" ".join(jr))
    full = " ".join(x for x in (given, family, suffix) if x)
    return {
        "family": family,
        "given": given,
        "suffix": suffix,
        "full": full,
        "explicit": "," in re.sub(r"{[^{}]*}", "", raw),
        "repaired": bool(lossy),
    }


def name_key(text: str) -> str:
    """Accent-, case- and punctuation-insensitive key of a name (any script)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"\w+", text.casefold()))


def harmonise_names(creators: list[dict]) -> int:
    """Give every occurrence of one person the same family/given split.

    Variants differing only in punctuation, case or accents are one person; the
    explicit (comma) split wins, else the most frequent, else the longest.
    Returns the number of occurrences changed.
    """
    variants: dict[str, Counter] = {}
    for c in creators:
        v = variants.setdefault(name_key(c["full"]), Counter())
        v[(c["family"], c["given"], c["full"])] += 1 + 1000 * c["explicit"]
    changed = 0
    for c in creators:
        v = variants[name_key(c["full"])]
        ref = max(v, key=lambda x: (v[x], len(x[2])))
        if (c["family"], c["given"], c["full"]) != ref:
            c["family"], c["given"], c["full"] = ref
            changed += 1
    return changed


def split_separated_list(value: str) -> list[str]:
    """Split a BibLaTeX separated list on commas at bracket depth 0."""
    items, depth, buf = [], 0, ""
    for ch in value:
        if ch in "([<":
            depth += 1
        elif ch in ")]>" and depth:
            depth -= 1
        if ch == "," and depth == 0:
            items.append(buf)
            buf = ""
        else:
            buf += ch
    items.append(buf)
    return [i.strip() for i in items if i.strip()]


def split_identifiers(field: str, value: str) -> list[str]:
    """Split a multi-valued ISSN / ISBN field (", " "; " " and " or spaces)."""
    values = [
        v for v in re.split(r"[,;\s]+(?:and\s+)?", value) if len(re.sub(r"[^0-9Xx]", "", v)) >= 8
    ]
    if field == "issn":  # canonical NNNN-NNNC form
        values = [
            re.sub(r"^(\d{4})-?(\d{3}[\dXx])$", lambda m: f"{m[1]}-{m[2].upper()}", v)
            for v in values
        ]
    return [v.strip() for v in values]


def convert_string(text: str, source: str) -> dict:
    """Convert BibLaTeX ``text`` to the generic JSON tables."""
    library = bibtexparser.parse_string(text)
    raw_entries = [(entry, False) for entry in library.entries]
    failed = 0
    for block in library.failed_blocks:
        # Zotero repeats some fields (several ``annotation``): bibtexparser 1.x,
        # used by the profile, keeps the first value; 2.x rejects the entry, and
        # its fallback entry skipped the middleware removing enclosing braces.
        if isinstance(block, DuplicateFieldKeyBlock) and block.ignore_error_block is not None:
            raw_entries.append((block.ignore_error_block, True))
        else:
            failed += 1
    if failed:
        logger.warning("%s: %d unparsable block(s) skipped", source, failed)

    entries, creators, lists, identifiers = [], [], [], []
    seen: set[str] = set()
    for raw, enclosed in raw_entries:
        key = raw.key
        if key in seen:
            logger.warning("%s: duplicate key %s skipped", source, key)
            continue
        seen.add(key)
        entry = {"ID": key, "ENTRYTYPE": raw.entry_type.lower()}
        fields: dict[str, str] = {}
        for f in raw.fields:  # a repeated field keeps its first value, as in bibtexparser 1.x
            fields.setdefault(f.key.lower(), strip_enclosing(str(f.value)) if enclosed else str(f.value))
        for name, value in fields.items():
            if clean(value).casefold() in NULL_TOKENS:
                continue  # "nan" etc.: no value
            if name in MULTI_IDENTIFIER_FIELDS:
                entry[name] = clean(value)
                for pos, item in enumerate(split_identifiers(name, entry[name])):
                    identifiers.append({"entry": key, "field": name, "position": pos + 1, "value": item})
            elif name in NAME_LIST_FIELDS:
                # Split on the raw value: " and " inside braces is a literal.
                names = re.split(r"\s+and\s+(?![^{]*})", value)
                for pos, person in enumerate(n for n in names if n.strip()):
                    creators.append(
                        {"entry": key, "role": name, "position": pos + 1, **split_name(person)}
                    )
                entry[name] = clean(value)
            elif name in SEPARATED_LIST_FIELDS:
                entry[name] = clean(value)
                for pos, item in enumerate(split_separated_list(entry[name])):
                    lists.append({"entry": key, "field": name, "position": pos + 1, "value": item})
            elif name in VERBATIM_FIELDS:
                entry[name] = clean_verbatim(value)
            else:
                entry[name] = clean(value)
        entries.append(entry)
    harmonise_names(creators)
    repaired = 0
    for c in creators:
        del c["explicit"]
        repaired += c.pop("repaired")
    if repaired:
        logger.info("%s: %d names in a lossy ', Given Family' form re-split", source, repaired)
    return {
        "source": source,
        "entries": entries,
        "creators": creators,
        "lists": lists,
        "identifiers": identifiers,
    }


def convert(bib_path: Path) -> dict:
    """Convert the BibLaTeX file at ``bib_path``."""
    bib_path = Path(bib_path)
    return convert_string(bib_path.read_text(encoding="utf-8"), bib_path.name)
