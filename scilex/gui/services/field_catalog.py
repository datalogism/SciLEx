"""What the Configure screen says about each ``scilex.yml`` field (ADR 0005).

UI-independent. Every leaf of :class:`ScilexSettings` has an entry in
:data:`FIELDS` (a test enforces it): a written label, a one-line help shown
under the field, an example, and suggestions for autocompletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import yaml

from scilex.init_templates import list_templates, resolve_template


@dataclass(frozen=True)
class FieldMeta:
    """Text and suggestions of one field."""

    label: str
    help: str
    example: str = ""  # placeholder of an empty input
    suggestions: tuple[str, ...] = ()  # autocompletion of free-text lists
    option_labels: tuple[tuple[str, str], ...] = ()  # value -> readable label
    advanced: bool = False  # shown only once "Show advanced fields" is on


@dataclass(frozen=True)
class SectionMeta:
    """Title and purpose of one section of the form."""

    label: str
    help: str
    advanced: bool = True


@dataclass(frozen=True)
class ApiInfo:
    """What a newcomer needs to choose a source."""

    label: str
    coverage: str
    key: str = "none"  # "required", "recommended" or "none"
    key_block: str = ""  # block of keys.yml holding its key


@dataclass(frozen=True)
class PresetInfo:
    """Readable description of a preset."""

    label: str
    help: str


# Document types the collectors produce (Zotero item types).
ITEM_TYPES: tuple[tuple[str, str], ...] = (
    ("journalArticle", "Journal article"),
    ("conferencePaper", "Conference paper"),
    ("preprint", "Preprint"),
    ("book", "Book"),
    ("bookSection", "Book chapter"),
    ("thesis", "Thesis"),
    ("report", "Report"),
    ("Manuscript", "Other / informal publication"),
)
ITEM_TYPE_VALUES: tuple[str, ...] = tuple(value for value, _ in ITEM_TYPES)

LLM_MODELS: tuple[str, ...] = (
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-chat",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen3-32b",
)

WEIGHT_LABELS: dict[str, str] = {
    "keywords": "Keyword match",
    "quality": "Metadata completeness",
    "itemtype": "Document type",
    "citations": "Citations",
}

PRESETS_INFO: dict[str, PresetInfo] = {
    "": PresetInfo(
        "Default rules",
        "Recommended quality filters (abstract and year required, short or "
        "long abstracts dropped) and the default size cap.",
    ),
    "literature_review": PresetInfo(
        "Literature review",
        "Same as the default rules, written explicitly in the file.",
    ),
    "bibliometrics": PresetInfo(
        "Bibliometrics",
        "Keep everything: no quality filter, no size cap. For counting and "
        "mapping a field rather than reading papers.",
    ),
}

API_INFO: dict[str, ApiInfo] = {
    "OpenAlex": ApiInfo(
        "OpenAlex",
        "All disciplines, ~250M works. Best default.",
        "recommended",
        "OpenAlex",
    ),
    "SemanticScholar": ApiInfo(
        "Semantic Scholar",
        "All disciplines, strong in computer science and biomedicine.",
        "recommended",
        "SemanticScholar",
    ),
    "PubMed": ApiInfo(
        "PubMed",
        "Biomedicine and life sciences (MEDLINE).",
        "recommended",
        "PubMed",
    ),
    "PubMedCentral": ApiInfo(
        "PubMed Central", "Open-access full texts in biomedicine.", "none", "PubMed"
    ),
    "Arxiv": ApiInfo("arXiv", "Preprints: physics, maths, computer science, q-bio."),
    "BioRxiv": ApiInfo("bioRxiv", "Biology preprints."),
    "DBLP": ApiInfo("DBLP", "Computer science venues (no abstracts)."),
    "HAL": ApiInfo("HAL", "French open archive, all disciplines."),
    "Istex": ApiInfo("ISTEX", "French national archive of licensed publications."),
    "OpenAIRE": ApiInfo("OpenAIRE", "European open-science graph, all disciplines."),
    "ORKG": ApiInfo(
        "ORKG",
        "Open Research Knowledge Graph: structured papers. No year filter on "
        "its side: other years are fetched, then dropped.",
    ),
    "IEEE": ApiInfo(
        "IEEE Xplore", "Engineering and computer science.", "required", "IEEE"
    ),
    "Elsevier": ApiInfo(
        "Elsevier (Scopus)",
        "All disciplines, Elsevier journals.",
        "required",
        "Elsevier",
    ),
    "Springer": ApiInfo(
        "Springer Nature",
        "All disciplines, Springer journals and books.",
        "required",
        "Springer",
    ),
}

SECTIONS: dict[str, SectionMeta] = {
    "filters": SectionMeta(
        "Filters",
        "Which papers are kept after collection. The defaults suit most reviews.",
        advanced=False,
    ),
    "citations": SectionMeta(
        "Citations", "Fetch citation counts, used by the citation filter and ranking."
    ),
    "ranking": SectionMeta(
        "Ranking", "Score each paper from 0 to 10 and keep the best ones."
    ),
    "enrichment": SectionMeta(
        "Enrichment", "Extra information added to each paper (slower)."
    ),
    "paperswithcode": SectionMeta(
        "Papers with Code",
        "Add tasks, methods, benchmarks and code repositories from Papers with Code.",
    ),
    "report": SectionMeta("Reports", "Files written next to the results."),
    "collect": SectionMeta(
        "Collection",
        "Re-run without collecting, and VPN rotation when a source blocks you.",
    ),
    "llm_screening": SectionMeta(
        "LLM screening",
        "Ask a language model to score each paper against your topic (paid, "
        "through OpenRouter).",
    ),
    "subcorpora": SectionMeta(
        "Sub-corpora",
        "Zotero collections every paper must belong to; checked in Consolidate.",
    ),
}

_TYPE_OPTIONS = ITEM_TYPES

FIELDS: dict[str, FieldMeta] = {
    # -- top level -----------------------------------------------------------
    "name": FieldMeta(
        "Review name",
        "Short name of the review; results go to <output folder>/<name>.",
        "metabolomics_kg_2025",
    ),
    "output_dir": FieldMeta(
        "Output folder",
        "Where results are written, relative to the review folder.",
        "output",
        advanced=True,
    ),
    "preset": FieldMeta(
        "Starting rules",
        "Sets the filter defaults below; your own changes always win.",
    ),
    # -- search --------------------------------------------------------------
    "search.keywords": FieldMeta(
        "Keywords",
        "Each term is sent as a search query to every source, then checked in "
        "titles and abstracts (case-insensitive). Use the phrase as authors "
        "write it, e.g. 'knowledge graph'. No wildcards or boolean operators.",
        "e.g. knowledge graph",
    ),
    "search.years": FieldMeta("Years", "Publication years to search."),
    "search.apis": FieldMeta(
        "Sources",
        "Databases queried. Each extra source adds queries; pick the ones "
        "covering your field.",
    ),
    "search.bonus_keywords": FieldMeta(
        "Bonus keywords",
        "Optional terms that raise a paper's relevance score; they never "
        "exclude a paper. With two keyword groups, a bonus term can also "
        "replace a missing group-2 term.",
        "e.g. benchmark",
    ),
    "search.max_articles_per_query": FieldMeta(
        "Max articles per query",
        "Stop each query once about this many articles are collected (APIs "
        "return whole pages, so a query can bring a page more). Empty means "
        "no limit; try 100 for a quick first look.",
        "no limit",
    ),
    "search.semantic_scholar_mode": FieldMeta(
        "Semantic Scholar mode",
        "'bulk' is about 10x faster but needs approval from Semantic Scholar.",
        option_labels=(("regular", "Regular"), ("bulk", "Bulk (approved keys only)")),
        advanced=True,
    ),
    "search.since": FieldMeta(
        "Only papers since",
        "Incremental update: only collect papers published from this date. "
        "Leave empty for a first collection.",
        "YYYY-MM-DD",
        advanced=True,
    ),
    # -- filters -------------------------------------------------------------
    "filters.item_types": FieldMeta(
        "Keep only these document types",
        "Empty keeps every type.",
        "all types",
        suggestions=ITEM_TYPE_VALUES,
        option_labels=_TYPE_OPTIONS,
    ),
    "filters.always_keep": FieldMeta(
        "Always keep these types",
        "Papers of these types skip the quality filters below (they are "
        "usually peer reviewed).",
        suggestions=ITEM_TYPE_VALUES,
        option_labels=_TYPE_OPTIONS,
    ),
    "filters.require": FieldMeta(
        "Required information",
        "Drop papers missing any of these.",
        option_labels=(
            ("abstract", "Abstract"),
            ("doi", "DOI"),
            ("year", "Publication year"),
            ("open_access", "Open-access link"),
        ),
    ),
    "filters.min_authors": FieldMeta(
        "Minimum number of authors", "0 keeps papers without listed authors."
    ),
    "filters.abstract_words": FieldMeta(
        "Abstract length (words)",
        "Drop papers whose abstract is shorter or longer than this, as 'min, max'.",
        "50, 1000",
    ),
    "filters.abstract_quality": FieldMeta(
        "Minimum abstract quality (0-100)",
        "Score based on length and structure of the abstract. Empty disables "
        "the check; 60 is a reasonable value.",
        "disabled",
        advanced=True,
    ),
    "filters.check_year_range": FieldMeta(
        "Drop papers outside the search years",
        "Some sources return papers from other years; this removes them.",
    ),
    "filters.citations": FieldMeta(
        "Citation threshold",
        "Drop old papers that are rarely cited (the threshold grows with "
        "the paper's age; recent papers are kept). Needs citation counts.",
    ),
    # -- citations -----------------------------------------------------------
    "citations.fetch": FieldMeta(
        "Fetch citation counts",
        "Slower, but needed by the citation threshold and the ranking.",
    ),
    "citations.fallbacks": FieldMeta(
        "Fallback sources",
        "Tried in order when the first source has no count for a paper.",
        option_labels=(
            ("semantic_scholar", "Semantic Scholar"),
            ("openalex", "OpenAlex"),
        ),
        advanced=True,
    ),
    "citations.opencitations": FieldMeta(
        "Ask OpenCitations last",
        "Query the free OpenCitations index (COCI) for papers no other source "
        "counted. Most complete for DOIs, but the slowest step (3 requests/s).",
    ),
    "citations.discrepancy_threshold": FieldMeta(
        "Discrepancy warning threshold",
        "Relative gap between two sources above which a count is flagged (0.5 = 50%).",
        advanced=True,
    ),
    # -- ranking -------------------------------------------------------------
    "ranking.enabled": FieldMeta(
        "Rank papers", "Compute a 0-10 relevance score and sort papers by it."
    ),
    "ranking.max_papers": FieldMeta(
        "Keep the top N papers",
        "Keep at most this many best-ranked papers. Empty means no cap.",
        "no cap",
    ),
    "ranking.weights": FieldMeta(
        "Score weights",
        "Share of each criterion in the score. They are relative: only "
        "their proportions matter.",
        advanced=True,
    ),
    "ranking.itemtype_weights": FieldMeta(
        "Document types scored as scholarly",
        "Types that get full points for the 'document type' criterion; "
        "other types get none.",
        suggestions=ITEM_TYPE_VALUES,
        option_labels=_TYPE_OPTIONS,
        advanced=True,
    ),
    "ranking.venue_ranking": FieldMeta(
        "Use venue rankings",
        "Boost papers from venues well ranked by CORE (conferences) and SJR "
        "(journals).",
    ),
    # -- enrichment ----------------------------------------------------------
    "enrichment.recover_dois": FieldMeta(
        "Recover missing DOIs", "Search CrossRef for the DOI of papers lacking one."
    ),
    "enrichment.doi_recovery_min_similarity": FieldMeta(
        "Title similarity for a recovered DOI",
        "0-1; a found DOI is accepted only if its title is at least this "
        "similar. Lower finds more but risks wrong matches.",
        advanced=True,
    ),
    "enrichment.unpaywall": FieldMeta(
        "Find open-access links",
        "Look up free full-text links with Unpaywall (needs an email on the "
        "API keys page).",
    ),
    "enrichment.author_hindex": FieldMeta(
        "Fetch author h-index", "Slow on large collections."
    ),
    "enrichment.paperswithcode.enabled": FieldMeta(
        "Link to Papers with Code",
        "Attach the tasks, methods, benchmarks and code repositories of each "
        "paper from Papers with Code, no key needed (run from the Analyses step).",
    ),
    "enrichment.paperswithcode.fuzzy_match_threshold": FieldMeta(
        "Title match threshold (0-100)",
        "How similar titles must be to link a paper. Higher is stricter.",
        advanced=True,
    ),
    "enrichment.paperswithcode.cache_path": FieldMeta(
        "Cache file",
        "Local cache of Papers with Code answers, relative to the review folder.",
        advanced=True,
    ),
    "enrichment.paperswithcode.cache_ttl_days": FieldMeta(
        "Cache lifetime (days)",
        "Cached answers older than this are fetched again.",
        advanced=True,
    ),
    "enrichment.paperswithcode.workers": FieldMeta(
        "Parallel requests",
        "1-32. More is faster but hits rate limits sooner.",
        advanced=True,
    ),
    # -- report --------------------------------------------------------------
    "report.quality_report": FieldMeta(
        "Data quality report", "Share of papers with abstract, DOI, authors, etc."
    ),
    "report.track_duplicates": FieldMeta(
        "Track duplicate sources", "Record which sources returned each paper."
    ),
    "report.prisma": FieldMeta(
        "PRISMA flow report",
        "Counts at each step, for the PRISMA diagram of a systematic review.",
    ),
    # -- collect -------------------------------------------------------------
    "collect.enabled": FieldMeta(
        "Collect new papers",
        "Turn off to only re-run aggregation on papers already collected.",
    ),
    "collect.vpn": FieldMeta(
        "VPN rotation (NordVPN)",
        "Switch NordVPN server when a source keeps blocking this IP (429/409), "
        "then retry the same page.",
        "enabled: true",
    ),
    # -- llm screening -------------------------------------------------------
    "llm_screening.enabled": FieldMeta(
        "Screen papers with an LLM",
        "Needs an OpenRouter key (API keys page). Runs at the Screen step.",
    ),
    "llm_screening.topic": FieldMeta(
        "What is relevant",
        "Describe in plain language which papers you want, as you would to a "
        "colleague. Required when screening is on.",
        "Papers that build or use knowledge graphs to integrate metabolomics "
        "data; exclude pure chemistry papers.",
    ),
    "llm_screening.model": FieldMeta(
        "Model",
        "OpenRouter model id. Cheap fast models are usually enough.",
        "deepseek/deepseek-v4-flash",
        suggestions=LLM_MODELS,
    ),
    "llm_screening.threshold": FieldMeta(
        "Minimum score (0-1)",
        "Drop papers scored below this. Empty keeps all papers and only adds "
        "the score.",
        "keep all",
    ),
    "llm_screening.max_papers": FieldMeta(
        "Max papers screened",
        "Safety cap on cost: at most this many papers not already scored are "
        "sent to the model.",
    ),
    "llm_screening.workers": FieldMeta("Parallel requests", "1-64.", advanced=True),
    "llm_screening.price_input_per_m": FieldMeta(
        "Input price ($ per million tokens)",
        "Used only to estimate the cost before screening.",
        advanced=True,
    ),
    "llm_screening.price_output_per_m": FieldMeta(
        "Output price ($ per million tokens)",
        "Used only to estimate the cost before screening.",
        advanced=True,
    ),
    # -- sub-corpora ----------------------------------------------------------
    "subcorpora.required": FieldMeta(
        "Required sub-corpora",
        "Every paper must be in at least one Zotero collection of these names, or "
        "under one (e.g. datasets, surveys, models). Consolidate lists the papers in "
        "none and adds them to one, in Zotero for linked papers.",
    ),
}


def field_meta(dotted: str) -> FieldMeta:
    """Return the entry of ``dotted``, or one derived from its name."""
    meta = FIELDS.get(dotted)
    if meta is not None:
        return meta
    name = dotted.rsplit(".", 1)[-1]
    return FieldMeta(name.replace("_", " ").capitalize(), "")


def label_of(dotted: str) -> str:
    """Readable label of a field or section path."""
    if dotted in FIELDS:
        return FIELDS[dotted].label
    section = SECTIONS.get(dotted.rsplit(".", 1)[-1])
    if section is not None:
        return section.label
    return field_meta(dotted).label


@cache
def template_keywords() -> tuple[str, ...]:
    """Keywords of the domain templates, as examples for the keyword groups."""
    terms: list[str] = []
    for name in list_templates():
        try:
            data = yaml.safe_load(resolve_template(name).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, ValueError):
            continue
        groups = ((data or {}).get("search") or {}).get("keywords") or []
        for group in groups:
            items = group if isinstance(group, list) else [group]
            terms.extend(str(term) for term in items if str(term) not in terms)
    return tuple(terms)
