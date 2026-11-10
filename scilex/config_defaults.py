"""Configuration defaults for SciLEx.

This module centralizes all sensible defaults that users rarely need to change.
The main configuration file only needs to specify essential research parameters.
Users can optionally override these defaults with their own values.

When a configuration value is not specified in scilex.config.yml, the system
will use the corresponding default from this module.
"""

import copy
import os

# ============================================================================
# COLLECTOR REGISTRY
# ============================================================================

COLLECTOR_API_NAMES = (
    "DBLP",
    "Arxiv",
    "BioRxiv",
    "Elsevier",
    "IEEE",
    "Springer",
    "SemanticScholar",
    "OpenAlex",
    "HAL",
    "Istex",
    "PubMed",
    "PubMedCentral",
    "OpenAIRE",
    "ORKG",
)
"""Names accepted in ``search.apis``. Kept here (a light module) so the settings
schema can validate them without importing the collectors; a test checks it
matches ``api_collectors`` and ``FORMAT_CONVERTERS``."""

# ============================================================================
# OUTPUT AND FILE SETTINGS
# ============================================================================

# Compute project root (parent of src/) to ensure consistent paths
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")
"""Base directory for all collection and aggregation output.
Absolute path to ensure consistency regardless of working directory."""

DEFAULT_AGGREGATED_FILENAME = "aggregated_results.csv"
"""Filename for aggregated and deduplicated papers."""

# ============================================================================
# ABSTRACT QUALITY THRESHOLDS
# ============================================================================

MIN_ABSTRACT_WORDS = 50
"""Minimum abstract length in words. Detects truncated or stub abstracts.
Typical range: 50-100 words. Set to 0 to disable."""

MAX_ABSTRACT_WORDS = 1000
"""Maximum abstract length in words. Detects copy-paste errors or non-abstracts.
Typical range: 500-1000 words. Set to 0 to disable."""

MIN_ABSTRACT_QUALITY_SCORE = 60
"""Minimum acceptable quality score for abstracts (0-100 scale).
Used when validate_abstracts is enabled."""

# ============================================================================
# AUTHOR AND METADATA VALIDATION
# ============================================================================

MIN_AUTHOR_COUNT = 2
"""Minimum number of authors required for a paper record.
Set to 1 for at least one author, 2 to exclude single-author papers."""

# ============================================================================
# RELEVANCE SCORING WEIGHTS
# ============================================================================

DEFAULT_RELEVANCE_WEIGHTS = {
    "keywords": 0.45,  # 45% - Content relevance to search terms (primary)
    "quality": 0.25,  # 25% - Metadata completeness and richness
    "itemtype": 0.20,  # 20% - Publication venue quality (scholarly types)
    "citations": 0.10,  # 10% - Research impact (minimized for recency bias)
}
"""Component weights for composite relevance scoring (must sum to 1.0).
Each component is normalized to 0-10 scale before weighting.
Prioritizes content relevance and quality over citations."""

DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS = {
    "journalArticle": True,  # Peer-reviewed journal articles
    "conferencePaper": True,  # Conference proceedings papers
    "bookSection": True,  # Book chapters
    "book": True,  # Complete books and monographs
}
"""ItemTypes that receive full weight (10 points) in relevance scoring.
Papers with these types are considered high-quality scholarly publications.
Papers with missing or unlisted itemTypes receive 0 points."""

# ============================================================================
# DEFAULT ITEMTYPE BYPASS AND FILTERING
# ============================================================================

DEFAULT_ENABLE_ITEMTYPE_BYPASS = True
"""Enable fast-track validation bypass for trusted publication types.
Papers with bypass itemTypes skip subsequent quality filters."""

DEFAULT_BYPASS_ITEM_TYPES = [
    "journalArticle",
    "conferencePaper",
]
"""Publication types that bypass subsequent quality filters.
Trusted sources: journalArticle, conferencePaper (peer-reviewed, high quality)."""

DEFAULT_ENABLE_ITEMTYPE_FILTER = False
"""Enable whitelist filtering - only keep papers with allowed itemTypes.
When enabled, all other papers are removed (strict mode)."""

DEFAULT_ALLOWED_ITEM_TYPES = [
    "journalArticle",  # Peer-reviewed journal articles
    "conferencePaper",  # Conference proceedings
    "bookSection",  # Book chapters
    "book",  # Books and monographs
]
"""ItemTypes to keep when itemtype filtering is enabled.
All other papers will be removed from aggregated results."""

# ============================================================================
# QUALITY FILTER REQUIREMENTS
# ============================================================================

DEFAULT_REQUIRE_ABSTRACT = True
"""Require papers to have an abstract.
Set to True for literature reviews, False for bibliometric studies."""

DEFAULT_REQUIRE_DOI = False
"""Require papers to have a DOI for citation tracking.
Set to False if using APIs like Google Scholar (often lack DOIs)."""

DEFAULT_REQUIRE_YEAR = True
"""Require publication year to be present.
Essential for temporal analysis and citation filtering."""

DEFAULT_REQUIRE_OPEN_ACCESS = False
"""Require papers to be open access (free to read).
Optional filter - reduces collection size significantly."""

# ============================================================================
# VALIDATION FEATURES
# ============================================================================

DEFAULT_VALIDATE_YEAR_RANGE = True
"""Validate papers fall within configured year range.
Uses years from main config - removes papers outside timeframe."""

DEFAULT_GENERATE_QUALITY_REPORT = True
"""Generate quality validation report during aggregation.
Reports show: papers filtered, reasons, data completeness stats."""

DEFAULT_VALIDATE_ABSTRACTS = False
"""Validate abstract quality and filter out poor abstracts.
When True, detects truncation, boilerplate, and encoding issues,
then removes papers below the min_abstract_quality_score threshold."""

# ============================================================================
# CITATION AND RELEVANCE FEATURES
# ============================================================================

DEFAULT_APPLY_CITATION_FILTER = True
"""Apply time-aware citation filtering based on paper age.
Focuses on impactful papers while keeping recent work."""

DEFAULT_USE_SEMANTIC_SCHOLAR_CITATIONS = True
"""Use Semantic Scholar citation data as fallback for OpenCitations.
Improves citation completeness for preprints and recent papers."""

DEFAULT_USE_OPENALEX_CITATIONS = True
"""Use OpenAlex as citation fallback (read by the aggregation orchestrator)."""

DEFAULT_USE_OPENCITATIONS = True
"""Query the OpenCitations count API for papers no earlier source resolved
(last citation phase, 2 requests per DOI at 3 req/s: the slowest one)."""

DEFAULT_APPLY_RELEVANCE_RANKING = True
"""Apply composite relevance scoring to rank papers by importance.
Papers sorted by relevance_score (higher = more relevant)."""

DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD = 0.5
"""Relative gap between citation sources above which a discrepancy is logged
(canonical_citation_count, issue #47)."""

DEFAULT_RECOVER_MISSING_DOIS = False
"""Opt-in: look up missing DOIs through CrossRef title+author search (#36)."""

DEFAULT_DOI_RECOVERY_MIN_SIMILARITY = 0.90
"""Minimum title similarity (0-1) to accept a CrossRef DOI candidate (#36)."""

DEFAULT_ENRICH_UNPAYWALL = False
"""Opt-in: add the oa_type column from Unpaywall (#44). Needs an email."""

DEFAULT_UNPAYWALL_EMAIL = ""
"""Contact email required by the Unpaywall API (falls back to api_config Unpaywall.email)."""

DEFAULT_ENRICH_AUTHOR_HINDEX = False
"""Opt-in: add first/last author h-index from Semantic Scholar (#45)."""

DEFAULT_USE_VENUE_RANKING = False
"""Opt-in: add venue_rank (CORE / SCImago) and blend it into the venue score (#3)."""

DEFAULT_MAX_PAPERS = 1000
"""Maximum number of papers to keep after all filtering.
Set to None to keep all papers that pass filters.
Recommended: 500-1000 for focused reviews, None for comprehensive studies."""

DEFAULT_TRACK_DUPLICATE_SOURCES = True
"""Track which APIs found which papers and analyze overlap.
Generates reports showing API value and optimization recommendations."""

# ============================================================================
# COLLECTION WORKFLOW SETTINGS
# ============================================================================

DEFAULT_COLLECT_ENABLED = True
"""Enable collection phase by default.
Set to False to skip collection and only aggregate existing data."""

# ============================================================================
# API RATE LIMITS (requests per second)
# ============================================================================

DEFAULT_RATE_LIMITS = {
    "SemanticScholar": {"without_key": 1.0, "with_key": 1.0},
    "OpenAlex": {"without_key": 10.0, "with_key": 10.0},
    "Arxiv": {"without_key": 0.33, "with_key": 0.33},  # 1 req per 3 seconds
    "BioRxiv": {"without_key": 1.0, "with_key": 1.0},  # No official limit
    "IEEE": {"without_key": 2.0, "with_key": 2.0},
    "Elsevier": {"without_key": 2.0, "with_key": 9.0},  # Scopus: 9 req/sec with key
    "Springer": {"without_key": 1.67, "with_key": 1.67},  # 100 req/min
    "HAL": {"without_key": 10.0, "with_key": 10.0},  # No documented limit
    "DBLP": {"without_key": 1.0, "with_key": 1.0},  # 1-2s between requests
    "Crossref": {
        "without_key": 5.0,
        "with_key": 10.0,
    },  # public: 5 req/sec, polite pool (mailto): 10 req/sec
    "Istex": {"without_key": 5.0, "with_key": 5.0},  # No documented limit
    "PubMed": {
        "without_key": 3.0,
        "with_key": 10.0,
    },  # NCBI: 3/sec free, 10/sec with key
    "PubMedCentral": {"without_key": 3.0, "with_key": 10.0},  # Same NCBI limits
    "OpenAIRE": {
        "without_key": 0.2,
        "with_key": 1.0,
    },  # anonymous: 5s gap; registered token: ~1 req/s
    "ORKG": {
        "without_key": 0.5,
        "with_key": 0.5,
    },  # 2s between requests; timeouts at higher rates
}
"""Rate limits for each API provider (requests per second).
Each entry has without_key/with_key values. The correct rate is auto-selected
based on whether the collector has an API key configured."""

# ============================================================================
# QUALITY FILTER CONFIGURATION SCHEMA (for reference)
# ============================================================================

QUALITY_FILTER_SCHEMA = {
    "enable_itemtype_bypass": bool,
    "bypass_item_types": list,
    "enable_itemtype_filter": bool,
    "allowed_item_types": list,
    "require_abstract": bool,
    "require_doi": bool,
    "require_year": bool,
    "require_open_access": bool,
    "min_author_count": int,
    "min_abstract_words": int,
    "max_abstract_words": int,
    "validate_year_range": bool,
    "validate_abstracts": bool,
    "min_abstract_quality_score": int,
    "generate_quality_report": bool,
    "apply_citation_filter": bool,
    "use_semantic_scholar_citations": bool,
    "use_openalex_citations": bool,
    "use_opencitations": bool,
    "apply_relevance_ranking": bool,
    "relevance_weights": dict,
    "itemtype_relevance_weights": dict,
    "max_papers": (int, type(None)),
    "track_duplicate_sources": bool,
}
"""Schema documenting all available quality filter options."""


def get_default_quality_filters():
    """Return all default quality filter settings as a dictionary."""
    return copy.deepcopy(
        {
            "enable_itemtype_bypass": DEFAULT_ENABLE_ITEMTYPE_BYPASS,
            "bypass_item_types": DEFAULT_BYPASS_ITEM_TYPES,
            "enable_itemtype_filter": DEFAULT_ENABLE_ITEMTYPE_FILTER,
            "allowed_item_types": DEFAULT_ALLOWED_ITEM_TYPES,
            "require_abstract": DEFAULT_REQUIRE_ABSTRACT,
            "require_doi": DEFAULT_REQUIRE_DOI,
            "require_year": DEFAULT_REQUIRE_YEAR,
            "require_open_access": DEFAULT_REQUIRE_OPEN_ACCESS,
            "min_author_count": MIN_AUTHOR_COUNT,
            "min_abstract_words": MIN_ABSTRACT_WORDS,
            "max_abstract_words": MAX_ABSTRACT_WORDS,
            "validate_year_range": DEFAULT_VALIDATE_YEAR_RANGE,
            "validate_abstracts": DEFAULT_VALIDATE_ABSTRACTS,
            "min_abstract_quality_score": MIN_ABSTRACT_QUALITY_SCORE,
            "generate_quality_report": DEFAULT_GENERATE_QUALITY_REPORT,
            "apply_citation_filter": DEFAULT_APPLY_CITATION_FILTER,
            "use_semantic_scholar_citations": DEFAULT_USE_SEMANTIC_SCHOLAR_CITATIONS,
            "use_openalex_citations": DEFAULT_USE_OPENALEX_CITATIONS,
            "use_opencitations": DEFAULT_USE_OPENCITATIONS,
            "apply_relevance_ranking": DEFAULT_APPLY_RELEVANCE_RANKING,
            "relevance_weights": DEFAULT_RELEVANCE_WEIGHTS,
            "itemtype_relevance_weights": DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS,
            "max_papers": DEFAULT_MAX_PAPERS,
            "track_duplicate_sources": DEFAULT_TRACK_DUPLICATE_SOURCES,
        }
    )


def get_rate_limit(api_name: str, has_api_key: bool = False) -> float:
    """Get rate limit for a specific API, selecting with_key/without_key rate.

    Args:
        api_name: Name of the API (e.g., 'SemanticScholar', 'IEEE')
        has_api_key: Whether the collector has an API key configured

    Returns:
        Rate limit in requests per second
    """
    entry = DEFAULT_RATE_LIMITS.get(api_name)
    if entry is None:
        return 5.0
    if isinstance(entry, dict):
        return entry["with_key"] if has_api_key else entry["without_key"]
    # Backward compat: if someone passes a plain float
    return float(entry)  # type: ignore[arg-type]


# ============================================================================
# GRAPH ANALYSIS SETTINGS (scilex-analyze)
# ============================================================================

DEFAULT_GRAPH_TYPE = "cocitation"
"""Graph to build: 'cocitation', 'coupling' or 'both'."""

DEFAULT_LOUVAIN_RESOLUTION = 1.0
"""Louvain resolution; higher values give more, smaller communities (typical 0.5-2.0)."""

DEFAULT_GRAPH_MIN_WEIGHT = 1
"""Minimum edge weight kept; increase to drop weak links and get cleaner clusters."""

DEFAULT_GRAPH_FORMAT = "gexf"
"""Graph export format: 'gexf' (Gephi) or 'graphml'."""

# ============================================================================
# SNOWBALL SAMPLING SETTINGS (scilex-snowball)
# ============================================================================

DEFAULT_SNOWBALL_DIRECTION = "both"
"""Direction: 'backward' (references), 'forward' (citing papers) or 'both'."""

DEFAULT_SNOWBALL_TOP_K = 200
"""Number of top-ranked candidates kept; higher finds more papers but is slower."""

DEFAULT_SNOWBALL_MIN_FREQUENCY = 2
"""A candidate must be cited by (or cite) at least this many corpus papers."""


# ---------------------------------------------------------------------------
# Lot B keys (read with config.get(key, DEFAULT_*); not part of the quality schema)
# ---------------------------------------------------------------------------
DEFAULT_GENERATE_PRISMA_REPORT = True
DEFAULT_SINCE = None
