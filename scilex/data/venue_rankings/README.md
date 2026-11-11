# Venue rankings

- `core_conferences.csv` (title,acronym,rank): full CORE2023 conference ranking (A*, A, B, C),
  downloaded from portal.core.edu.au.
- `sjr_journals.csv` (title,quartile): **empty by default**. SCImago blocks automated downloads
  (Cloudflare), so journals get no rank until you download the SJR export by hand from
  https://www.scimagojr.com/journalrank.php and run
  `python scripts/update_venue_rankings.py --sjr-file <export.csv>`.

Refresh both with `python scripts/update_venue_rankings.py`. No Impact Factor (proprietary).
