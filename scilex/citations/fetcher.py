"""Citation resolution engine for the aggregation pipeline.

Public entry point: :func:`fetch_citations_for_dataframe`.

Papers flow through sequential phases; each phase resolves a subset and passes
the rest on:

    1.  Batch cache lookup (one SQL query)
    2.  Semantic Scholar counts already in the DataFrame (in-memory)
    2b. OpenAlex counts already in the DataFrame (in-memory)
    3.  CrossRef batch API (N/20 HTTP requests)
    4.  OpenCitations count API (threaded, 2 requests per DOI, 3 req/s shared)

Progress is checkpointed as the *set of resolved positions* (plus the result
arrays), because phases 3 and 4 do not complete papers in DataFrame order.
Checkpoints written by older versions (a ``last_index`` watermark meaning
positions ``0..last_index`` are done) are still readable.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import NamedTuple

import pandas as pd
from tqdm import tqdm

import scilex.citations.citations_tools as cit_tools
from scilex.citations import cache
from scilex.constants import normalize_doi

STAT_KEYS = (
    "success",
    "timeout",
    "error",
    "no_doi",
    "cache_hit",
    "cache_miss",
    "ss_used",
    "oa_used",
    "cr_used",
    "opencitations_used",
)

# citation source name -> stats counter incremented when a paper is resolved by it
_SOURCE_STAT = {
    "semantic_scholar": "ss_used",
    "openalex": "oa_used",
    "crossref": "cr_used",
}


class _Paper(NamedTuple):
    """Citation-relevant data of one paper still waiting for resolution."""

    doi: str
    ss_citations: int | None
    ss_references: int | None
    oa_citations: int | None


@dataclass
class _FetchState:
    """Mutable state shared by the phases (only touched from the calling thread)."""

    total: int
    extras: list
    nb_citeds: list
    nb_citations: list
    stats: dict
    cache_path: object = None
    resolved: set = field(default_factory=set)
    pbar: object = None

    @property
    def use_cache(self):
        """Whether the citation cache is enabled for this run."""
        return self.cache_path is not None


# ---------------------------------------------------------------------------
# Checkpoint IO
# ---------------------------------------------------------------------------


def _load_checkpoint(checkpoint_path):
    """Load checkpoint data if the file exists and is readable, else None."""
    try:
        with open(checkpoint_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"Could not load checkpoint: {e}")
        return None


def _save_checkpoint(checkpoint_path, data):
    """Save checkpoint data."""
    try:
        with open(checkpoint_path, "w") as f:
            json.dump(data, f)
        logging.debug(f"Checkpoint saved to {checkpoint_path}")
    except OSError as e:
        logging.warning(f"Could not save checkpoint: {e}")


def _write_checkpoint(state, checkpoint_path):
    """Persist the resolved positions, result arrays and stats."""
    _save_checkpoint(
        checkpoint_path,
        {
            "resolved_positions": sorted(state.resolved),
            "stats": dict(state.stats),
            "extras": state.extras,
            "nb_citeds": state.nb_citeds,
            "nb_citations": state.nb_citations,
        },
    )


def _restore_checkpoint(state, checkpoint):
    """Fill ``state`` from a checkpoint (new or legacy format)."""
    available = min(
        state.total,
        *(
            len(checkpoint.get(key, []))
            for key in ("extras", "nb_citeds", "nb_citations")
        ),
    )

    if "resolved_positions" in checkpoint:
        done = {
            pos
            for pos in checkpoint["resolved_positions"]
            if isinstance(pos, int) and 0 <= pos < available
        }
    else:
        # Legacy watermark: positions 0..last_index were considered done.
        expected = checkpoint.get("last_index", -1) + 1
        done = set(range(min(expected, available)))
        if len(done) < expected:
            logging.warning(
                f"Checkpoint data truncated: expected {expected} entries, "
                f"found {len(done)}. Re-fetching missing entries."
            )

    for pos in done:
        state.extras[pos] = checkpoint["extras"][pos]
        state.nb_citeds[pos] = checkpoint["nb_citeds"][pos]
        state.nb_citations[pos] = checkpoint["nb_citations"][pos]
    state.resolved = done
    state.stats.update(checkpoint.get("stats", {}))
    logging.info(f"Resuming: {len(done)}/{state.total} papers already resolved")


class _Checkpointer:
    """Save a checkpoint every ``interval`` newly resolved papers."""

    def __init__(self, state, path, interval):
        self.state = state
        self.path = path
        self.interval = interval
        self._last_saved_count = len(state.resolved)

    def maybe_save(self, force=False):
        """Write a checkpoint if enough papers were resolved since the last one."""
        if not self.path:
            return
        newly_resolved = len(self.state.resolved) - self._last_saved_count
        if newly_resolved <= 0:
            return
        if force or (self.interval and newly_resolved >= self.interval):
            _write_checkpoint(self.state, self.path)
            self._last_saved_count = len(self.state.resolved)
            logging.info(f"Checkpoint saved ({len(self.state.resolved)} resolved)")


# ---------------------------------------------------------------------------
# Per-paper extraction helpers
# ---------------------------------------------------------------------------


def _get_ss_citations_if_available(row):
    """Extract Semantic Scholar citation data from a paper row.

    Args:
        row: Pandas Series representing a paper with potential SS citation fields

    Returns:
        tuple: (citation_count, reference_count) or (None, None) if not available
    """
    ss_citation_count = row.get("ss_citation_count")
    ss_reference_count = row.get("ss_reference_count")

    # 0 is a valid value meaning "API confirmed 0 citations"
    has_ss_data = pd.notna(ss_citation_count) or pd.notna(ss_reference_count)

    if has_ss_data:
        citation_count = int(ss_citation_count) if pd.notna(ss_citation_count) else 0
        reference_count = int(ss_reference_count) if pd.notna(ss_reference_count) else 0
        return (citation_count, reference_count)

    return (None, None)


def _get_oa_citations_if_available(row):
    """Extract OpenAlex citation data from a paper row.

    OpenAlex provides cited_by_count (how many papers cite this one) but
    not a reference count.

    Args:
        row: Pandas Series representing a paper with potential OA citation fields

    Returns:
        int or None: Citation count if available, None otherwise
    """
    oa_citation_count = row.get("oa_citation_count")

    if pd.notna(oa_citation_count):
        return int(oa_citation_count)

    return None


def _update_pbar_postfix(pbar, stats, use_cache):
    """Update progress bar postfix with current statistics."""
    postfix = {
        "✓": stats["success"],
        "✗": stats["error"],
        "⏱": stats["timeout"],
        "⊘": stats["no_doi"],
    }
    if use_cache:
        postfix["💾"] = stats["cache_hit"]
        postfix["🔬"] = stats["ss_used"]
        postfix["🅰"] = stats["oa_used"]
        postfix["📚"] = stats["cr_used"]
        postfix["🔗"] = stats["opencitations_used"]
    pbar.set_postfix(postfix)


# ---------------------------------------------------------------------------
# Result bookkeeping
# ---------------------------------------------------------------------------


def _store_result(state, pos, citations, nb_cited, nb_citation):
    """Write one paper's result into the result arrays."""
    state.extras[pos] = str(citations)
    state.nb_citeds[pos] = nb_cited
    state.nb_citations[pos] = nb_citation


def _mark_resolved(state, pos):
    """Record a paper as done: remember its position and advance the bar."""
    state.resolved.add(pos)
    state.pbar.update(1)


def _write_cache(state, entries):
    """Write results to the cache, skipping failed ones and disabled caches."""
    if not state.use_cache:
        return
    cacheable = [entry for entry in entries if cache.should_cache_result(entry)]
    if cacheable:
        cache.cache_citations_batch(cacheable, state.cache_path)


def _resolve_from_counts(state, pos, doi, source, nb_cited, nb_citation):
    """Resolve a paper from plain counts (SS / OpenAlex / CrossRef).

    Builds the citations dict, stores it, updates the stats and marks the
    paper resolved.

    Returns:
        The cache entry for this result (to be written in a batch).
    """
    citations = {
        "citing_dois": [],
        "cited_dois": [],
        "nb_cited": nb_cited,
        "nb_citations": nb_citation,
        "source": source,
    }
    _store_result(state, pos, citations, nb_cited, nb_citation)
    state.stats[_SOURCE_STAT[source]] += 1
    state.stats["success"] += 1
    _mark_resolved(state, pos)
    return {
        "doi": doi,
        "citations_json": str(citations),
        "nb_cited": nb_cited,
        "nb_citations": nb_citation,
        "api_stats": {
            "cit_status": "success",
            "ref_status": "success",
            "source": source,
        },
    }


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


def _phase_cache(state, remaining):
    """Phase 1: resolve papers found in the citation cache."""
    state.pbar.set_description("Citations [cache]")
    cached = cache.get_cached_citations_batch(
        [paper.doi for paper in remaining.values()], state.cache_path
    )
    hits = [pos for pos, paper in remaining.items() if paper.doi in cached]
    for pos in hits:
        data = cached[remaining[pos].doi]
        _store_result(
            state, pos, data["citations"], data["nb_cited"], data["nb_citations"]
        )
        state.stats["cache_hit"] += 1
        api_stats = data["api_stats"]
        if (
            api_stats["cit_status"] == "success"
            and api_stats["ref_status"] == "success"
        ):
            state.stats["success"] += 1
        _mark_resolved(state, pos)
        del remaining[pos]
    state.stats["cache_miss"] += len(remaining)
    logging.debug(f"Phase 1 (cache): {len(hits)} hits, {len(remaining)} remaining")


def _phase_in_memory(state, remaining, label, source, extract_counts):
    """Phases 2 / 2b: resolve from counts already present in the DataFrame.

    Args:
        state: Shared fetch state.
        remaining: Unresolved papers, ``{position: _Paper}`` (mutated).
        label: Progress bar label.
        source: Citation source name (key of ``_SOURCE_STAT``).
        extract_counts: ``paper -> (nb_cited, nb_citation)`` or None if the
            paper has no data for this source.
    """
    state.pbar.set_description(f"Citations [{label}]")
    entries = []
    resolved_here = []
    for pos, paper in remaining.items():
        counts = extract_counts(paper)
        if counts is None:
            continue
        entries.append(
            _resolve_from_counts(state, pos, paper.doi, source, counts[0], counts[1])
        )
        resolved_here.append(pos)
    for pos in resolved_here:
        del remaining[pos]
    _write_cache(state, entries)
    logging.debug(
        f"Phase {label}: {len(resolved_here)} resolved, {len(remaining)} remaining"
    )


def _semantic_scholar_counts(paper):
    if paper.ss_citations is None and paper.ss_references is None:
        return None
    return (paper.ss_references or 0, paper.ss_citations or 0)


def _openalex_counts(paper):
    if paper.oa_citations is None:
        return None
    return (0, paper.oa_citations)  # OpenAlex gives no reference count


def _phase_crossref(state, remaining, checkpointer, crossref_mailto):
    """Phase 3: resolve through the CrossRef batch API."""
    state.pbar.set_description("Citations [CrossRef]")
    pending = [(pos, paper.doi) for pos, paper in remaining.items()]
    batch_size = cit_tools.CROSSREF_BATCH_SIZE

    for batch_start in range(0, len(pending), batch_size):
        batch = pending[batch_start : batch_start + batch_size]
        try:
            cr_results = cit_tools.getCrossRefCitationsBatch(
                [doi for _, doi in batch], mailto=crossref_mailto
            )
        except Exception as e:
            logging.debug(f"CrossRef batch request failed: {e}")
            cr_results = None
        cr_results = cr_results or {}

        entries = []
        for pos, doi in batch:
            if doi in cr_results:
                cr_cit, cr_ref = cr_results[doi]
                entries.append(
                    _resolve_from_counts(state, pos, doi, "crossref", cr_ref, cr_cit)
                )
                del remaining[pos]
        _write_cache(state, entries)
        checkpointer.maybe_save()
        _update_pbar_postfix(state.pbar, state.stats, state.use_cache)

    checkpointer.maybe_save(force=True)
    logging.debug(
        f"Phase 3 (CrossRef): {state.stats['cr_used']} resolved, "
        f"{len(remaining)} remaining for OpenCitations"
    )


def _fetch_opencitations_for_doi(doi):
    """OpenCitations worker (runs in a thread, touches no shared state).

    Returns:
        dict with ``citations``, ``api_stats``, ``nb_cited`` and ``nb_citations``.
    """
    counts, api_stats = cit_tools.getCitationCounts(doi)
    citations = {
        "citing_dois": [],
        "cited_dois": [],
        **counts,
        "source": "opencitations",
    }
    return {
        "citations": citations,
        "api_stats": {**api_stats, "source": "opencitations"},
        "nb_cited": counts["nb_cited"],
        "nb_citations": counts["nb_citations"],
    }


def _apply_opencitations_result(state, pos, doi, result):
    """Store an OpenCitations result and update stats; return True if resolved.

    Failed or timed-out lookups are stored (counts of zero, as before) but
    neither cached nor marked resolved, so a resumed run retries them.
    """
    api_stats = result["api_stats"]
    _store_result(
        state, pos, result["citations"], result["nb_cited"], result["nb_citations"]
    )
    if cache.should_cache_result(result):
        state.stats["success"] += 1
        _write_cache(
            state,
            [
                {
                    "doi": doi,
                    "citations_json": str(result["citations"]),
                    "nb_cited": result["nb_cited"],
                    "nb_citations": result["nb_citations"],
                    "api_stats": api_stats,
                }
            ],
        )
        return True
    if "timeout" in (api_stats["cit_status"], api_stats["ref_status"]):
        state.stats["timeout"] += 1
    else:
        state.stats["error"] += 1
    return False


def _phase_opencitations(state, remaining, num_workers, checkpointer):
    """Phase 4: OpenCitations fallback, threaded; results applied on this thread."""
    state.pbar.set_description("Citations [OpenCitations]")
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_pos = {
            executor.submit(_fetch_opencitations_for_doi, paper.doi): pos
            for pos, paper in remaining.items()
        }
        for future in as_completed(future_to_pos):
            pos = future_to_pos[future]
            doi = remaining[pos].doi
            state.stats["opencitations_used"] += 1
            try:
                result = future.result()
            except Exception as e:
                logging.error(f"Unexpected error fetching citations for DOI {doi}: {e}")
                state.stats["error"] += 1
            else:
                if _apply_opencitations_result(state, pos, doi, result):
                    state.resolved.add(pos)
            state.pbar.update(1)
            _update_pbar_postfix(state.pbar, state.stats, state.use_cache)
            checkpointer.maybe_save()
    checkpointer.maybe_save(force=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _init_cache(cache_dir=None):
    """Initialize the citation cache and purge expired entries; return its path.

    Args:
        cache_dir: Folder holding ``citation_cache.db``. None falls back to
            ``./output``, which fails when the working directory is read-only
            (a packaged macOS app starts in ``/``).
    """
    cache_path = cache.initialize_cache(
        cache.get_cache_path(cache_dir) if cache_dir else None
    )
    logging.info(f"Citation cache initialized at {cache_path}")
    cache_stats = cache.get_cache_stats(cache_path)
    logging.info(
        f"Cache stats: {cache_stats['active_entries']} active entries, "
        f"{cache_stats['expired_entries']} expired"
    )
    if cache_stats["expired_entries"] > 0:
        removed = cache.cleanup_expired_cache(cache_path)
        logging.info(f"Cleaned up {removed} expired cache entries")
    return cache_path


def _collect_remaining(state, df_clean):
    """Resolve no-DOI papers and return the unresolved ones as ``{pos: _Paper}``.

    Positions already resolved (from a checkpoint) are skipped. DOIs are
    normalized so cache, CrossRef and OpenCitations lookups agree.
    """
    remaining = {}
    for position, (_df_index, row) in enumerate(df_clean.iterrows()):
        if position in state.resolved:
            continue
        doi = normalize_doi(row.get("DOI"))
        if doi is None:
            state.stats["no_doi"] += 1
            _mark_resolved(state, position)
            continue
        ss_citations, ss_references = _get_ss_citations_if_available(row)
        remaining[position] = _Paper(
            doi,
            ss_citations,
            ss_references,
            _get_oa_citations_if_available(row),
        )
    return remaining


def _log_summary(stats, total_papers, use_cache):
    """Log the end-of-run statistics."""
    total_with_doi = total_papers - stats["no_doi"]

    def rate(count, total):
        return count / total * 100 if total > 0 else 0.0

    lookups = stats["cache_hit"] + stats["cache_miss"]
    logging.info(
        f"Citation fetching complete: ✓ {stats['success']} successful, "
        f"✗ {stats['error']} errors, ⏱ {stats['timeout']} timeouts, "
        f"⊘ {stats['no_doi']} without DOI"
    )
    if use_cache:
        logging.info(
            f"Cache performance: {stats['cache_hit']} hits, {stats['cache_miss']} misses "
            f"({rate(stats['cache_hit'], lookups):.1f}% hit rate)"
        )

    logging.info("Citation resolution by phase (sequential fallthrough):")
    logging.info(f"  💾 Cache hits: {stats['cache_hit']} papers")
    for icon, name, key in (
        ("🔬", "Semantic Scholar", "ss_used"),
        ("🅰", "OpenAlex", "oa_used"),
        ("📚", "CrossRef", "cr_used"),
        ("🔗", "OpenCitations API", "opencitations_used"),
    ):
        logging.info(
            f"  {icon} {name}: {stats[key]} papers ({rate(stats[key], total_with_doi):.1f}%)"
        )

    api_calls_saved = (
        stats["cache_hit"] + stats["ss_used"] + stats["oa_used"] + stats["cr_used"]
    )
    if total_with_doi > 0:
        logging.info(
            f"  💰 OpenCitations API calls avoided: {api_calls_saved}/{total_with_doi} "
            f"({rate(api_calls_saved, total_with_doi):.1f}%)"
        )


def fetch_citations_for_dataframe(
    df_clean,
    num_workers=3,
    checkpoint_interval=100,
    checkpoint_path=None,
    resume=False,
    use_cache=True,
    crossref_mailto=None,
    api_config=None,
    cache_dir=None,
    use_opencitations=True,
):
    """Fetch citation counts for every paper of a DataFrame.

    Args:
        df_clean: DataFrame with a ``DOI`` column (and optionally
            ``ss_citation_count``, ``ss_reference_count``, ``oa_citation_count``).
        num_workers: Parallel workers for the OpenCitations phase.
        checkpoint_interval: Save a checkpoint every N newly resolved papers
            (0/None disables periodic saves; one is still written after
            phases 3 and 4 when ``checkpoint_path`` is set).
        checkpoint_path: Path of the checkpoint file (None disables checkpoints).
        resume: When true, restore progress from ``checkpoint_path`` if it exists.
        use_cache: Use the SQLite citation cache. When false, no cache call at all
            is made.
        crossref_mailto: Email for the CrossRef polite pool (optional).
        api_config: Optional API config dict; its CrossRef mailto is used when
            ``crossref_mailto`` is not given.
        cache_dir: Folder of the citation cache database (default: ``./output``).
        use_opencitations: Run the OpenCitations phase (4) for the papers the
            earlier sources left unresolved.

    Returns:
        tuple: ``(extras, nb_citeds, nb_citations, stats)``. The three lists have
        one entry per row; unresolved papers (no DOI) hold None. ``stats`` has
        the keys listed in ``STAT_KEYS``.
    """
    if crossref_mailto is None and api_config:
        crossref_mailto = api_config.get("CrossRef", {}).get("mailto")
    total_papers = len(df_clean)

    state = _FetchState(
        total=total_papers,
        extras=[None] * total_papers,
        nb_citeds=[None] * total_papers,
        nb_citations=[None] * total_papers,
        stats=dict.fromkeys(STAT_KEYS, 0),
        cache_path=_init_cache(cache_dir) if use_cache else None,
    )

    if resume and checkpoint_path:
        checkpoint = _load_checkpoint(checkpoint_path)
        if checkpoint:
            _restore_checkpoint(state, checkpoint)

    papers_with_doi = int(df_clean["DOI"].map(normalize_doi).notna().sum())
    logging.info(
        f"Fetching citation data for {papers_with_doi}/{total_papers} papers with valid DOIs"
    )
    if state.use_cache:
        logging.info("Using citation cache (30-day TTL) — batch mode for phases 1-3")
    if use_opencitations:
        logging.info(
            f"Using {num_workers} workers for OpenCitations fallback (phase 4)"
        )
        logging.info(
            "Phase strategy: Cache → SS → OpenAlex → CrossRef (batch) → OpenCitations (threaded)"
        )
    else:
        logging.info(
            "Phase strategy: Cache → SS → OpenAlex → CrossRef (batch); OpenCitations disabled"
        )

    with tqdm(
        total=total_papers,
        initial=len(state.resolved),
        desc="Citations [init]",
        unit="paper",
        position=0,
        leave=True,
    ) as pbar:
        state.pbar = pbar
        remaining = _collect_remaining(state, df_clean)
        checkpointer = _Checkpointer(state, checkpoint_path, checkpoint_interval)

        phases = []
        if state.use_cache:
            phases.append(lambda: _phase_cache(state, remaining))
        phases += [
            lambda: _phase_in_memory(
                state, remaining, "SS", "semantic_scholar", _semantic_scholar_counts
            ),
            lambda: _phase_in_memory(
                state, remaining, "OpenAlex", "openalex", _openalex_counts
            ),
            lambda: _phase_crossref(state, remaining, checkpointer, crossref_mailto),
        ]
        if use_opencitations:
            phases.append(
                lambda: _phase_opencitations(
                    state, remaining, num_workers, checkpointer
                )
            )
        _update_pbar_postfix(pbar, state.stats, state.use_cache)
        for run_phase in phases:
            if not remaining:
                break
            run_phase()
            _update_pbar_postfix(pbar, state.stats, state.use_cache)
        pbar.set_description("Citations [done]")

    _log_summary(state.stats, total_papers, state.use_cache)
    return state.extras, state.nb_citeds, state.nb_citations, state.stats
