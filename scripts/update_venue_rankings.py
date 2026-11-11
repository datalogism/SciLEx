"""Download the full CORE and SCImago SJR rankings into scilex/data/venue_rankings.

Usage: python scripts/update_venue_rankings.py [--core-source CORE2023] [--sjr-file PATH]

SCImago sits behind a Cloudflare browser check, so the automatic SJR download
usually fails. Download the export by hand from
https://www.scimagojr.com/journalrank.php ("Download data") and pass it with
--sjr-file.

Output files use the simplified schemas read by scilex.pipeline.venue_ranking:
core_conferences.csv (title,acronym,rank) and sjr_journals.csv (title,quartile).
"""

import argparse
import csv
import io
from pathlib import Path

import requests

CORE_EXPORT_URL = (
    "https://portal.core.edu.au/conf-ranks/?search=&by=all&source={source}"
    "&sort=arank&page=1&do=Export"
)
SJR_URL = "https://www.scimagojr.com/journalrank.php?out=xls"
OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "scilex" / "data" / "venue_rankings"
)
VALID_CORE_RANKS = {"A*", "A", "B", "C"}
REQUEST_TIMEOUT_SECONDS = 120
USER_AGENT = {"User-Agent": "SciLEx venue ranking updater"}


def fetch_core(source):
    """Return CORE rows ``(title, acronym, rank)``; the export has no header.

    Columns: id, title, acronym, source, rank, note, dblp, for, comments, rating.
    """
    response = requests.get(
        CORE_EXPORT_URL.format(source=source),
        headers=USER_AGENT,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    rows = []
    for record in csv.reader(io.StringIO(response.text)):
        if len(record) >= 5 and record[4].strip() in VALID_CORE_RANKS:
            rows.append((record[1].strip(), record[2].strip(), record[4].strip()))
    return rows


def fetch_sjr():
    """Download the SJR export and return its rows (fails behind Cloudflare)."""
    response = requests.get(
        SJR_URL, headers=USER_AGENT, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return parse_sjr(response.text)


def parse_sjr(text):
    """Return SJR rows ``(title, best quartile)`` from the semicolon-separated export."""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    return [
        (row["Title"].strip(), row["SJR Best Quartile"].strip())
        for row in reader
        if row.get("SJR Best Quartile", "").strip() in {"Q1", "Q2", "Q3", "Q4"}
    ]


def write_csv(path, header, rows):
    """Write ``rows`` under ``header`` to ``path``."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path}")


def main():
    """Download both rankings and overwrite the shipped CSV files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", default="CORE2023")
    parser.add_argument(
        "--sjr-file", help="SJR export downloaded by hand (semicolon-separated CSV)"
    )
    args = parser.parse_args()
    write_csv(
        OUTPUT_DIR / "core_conferences.csv",
        ("title", "acronym", "rank"),
        fetch_core(args.core_source),
    )
    if args.sjr_file:
        sjr_rows = parse_sjr(Path(args.sjr_file).read_text(encoding="utf-8"))
    else:
        try:
            sjr_rows = fetch_sjr()
        except requests.RequestException as error:
            print(
                f"SJR download failed ({error}); use --sjr-file. SJR file left as is."
            )
            return
    write_csv(OUTPUT_DIR / "sjr_journals.csv", ("title", "quartile"), sjr_rows)


if __name__ == "__main__":
    main()
