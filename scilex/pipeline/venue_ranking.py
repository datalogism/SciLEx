"""Venue ranking: CORE (conferences) and SCImago SJR quartile (journals), issue #3.

Adds a ``venue_rank`` column (A*, A, B, C for conferences; Q1-Q4 for journals;
``MISSING_VALUE`` when the venue is unknown). Data are CSV files shipped in
``scilex/data/venue_rankings`` and refreshable with
``scripts/update_venue_rankings.py``.
"""

import csv
import logging
import re
import unicodedata
from functools import lru_cache
from importlib import resources

from scilex.constants import MISSING_VALUE, is_valid

DATA_PACKAGE = "scilex.data.venue_rankings"
CORE_FILENAME = "core_conferences.csv"
SJR_FILENAME = "sjr_journals.csv"

# Score (0-10) of each rank, used when blending into the ranking venue score.
RANK_SCORES = {
    "A*": 10.0,
    "A": 8.0,
    "B": 6.0,
    "C": 4.0,
    "Q1": 10.0,
    "Q2": 7.5,
    "Q3": 5.0,
    "Q4": 2.5,
}

_NOISE_PATTERN = re.compile(
    r"\b(proceedings|proceeding|of|the|annual|international|"
    r"\d+(st|nd|rd|th)|(19|20)\d{2}|volume|vol)\b"
)
_ACRONYM_PATTERN = re.compile(
    r"\(([A-Za-z][A-Za-z0-9\-\*]{1,15})(?:[ '’]*(?:19|20)?\d{2})?\)"
)
MIN_CONTAINED_TITLE_LENGTH = 15


def normalize_venue(name):
    """Lowercase, strip accents, '&'->'and', drop punctuation, years, ordinals and filler words."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("&", " and "))
    text = _NOISE_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_acronyms(name):
    """Upper-cased acronyms found in parentheses, e.g. ``(ISWC 2023)`` -> ``ISWC``."""
    return [match.upper() for match in _ACRONYM_PATTERN.findall(str(name))]


def _read_rows(filename):
    try:
        with (
            resources.files(DATA_PACKAGE)
            .joinpath(filename)
            .open("r", encoding="utf-8", newline="") as handle
        ):
            return list(csv.DictReader(handle))
    except (FileNotFoundError, ModuleNotFoundError):
        logging.warning(f"Venue ranking data file not found: {filename}")
        return []


@lru_cache(maxsize=1)
def load_rankings():
    """Load ranking tables.

    Returns:
        tuple: ``(conference_by_title, conference_by_acronym, journal_by_title)``
        dicts mapping normalized keys to ranks.
    """
    by_title, by_acronym = {}, {}
    for row in _read_rows(CORE_FILENAME):
        rank = row["rank"].strip()
        by_title[normalize_venue(row["title"])] = rank
        if row.get("acronym"):
            by_acronym[row["acronym"].strip().upper()] = rank
    journals = {
        normalize_venue(row["title"]): row["quartile"].strip()
        for row in _read_rows(SJR_FILENAME)
    }
    return by_title, by_acronym, journals


def lookup_venue_rank(venue_name, rankings=None):
    """Return the rank of a venue name, or ``MISSING_VALUE``.

    Matching order: exact normalized journal title, exact normalized
    conference title, acronym in parentheses, then a CORE title contained in
    the venue name (at least ``MIN_CONTAINED_TITLE_LENGTH`` characters).
    """
    if not is_valid(venue_name):
        return MISSING_VALUE
    conference_titles, conference_acronyms, journals = rankings or load_rankings()
    normalized = normalize_venue(venue_name)
    if not normalized:
        return MISSING_VALUE
    if normalized in journals:
        return journals[normalized]
    if normalized in conference_titles:
        return conference_titles[normalized]
    for acronym in extract_acronyms(venue_name):
        if acronym in conference_acronyms:
            return conference_acronyms[acronym]
    for title, rank in conference_titles.items():
        if len(title) >= MIN_CONTAINED_TITLE_LENGTH and title in normalized:
            return rank
    return MISSING_VALUE


def add_venue_rank(df, rankings=None):
    """Add the ``venue_rank`` column from conferenceName / journalAbbreviation."""
    df = df.copy()

    def rank_for(row):
        for column in ("conferenceName", "journalAbbreviation"):
            rank = lookup_venue_rank(row.get(column), rankings)
            if rank != MISSING_VALUE:
                return rank
        return MISSING_VALUE

    df["venue_rank"] = df.apply(rank_for, axis=1) if len(df) else []
    ranked = int((df["venue_rank"] != MISSING_VALUE).sum()) if len(df) else 0
    logging.info(
        f"Venue ranking: {ranked:,}/{len(df):,} papers matched a CORE/SJR venue"
    )
    return df


def venue_rank_score(rank):
    """Rank -> 0-10 score, or None when the rank is unknown."""
    return RANK_SCORES.get(str(rank).strip())
