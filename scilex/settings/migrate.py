"""Convert the legacy configuration files to the new ``scilex.yml`` format."""

import copy
import logging
from pathlib import Path

import yaml

from scilex.config_defaults import (
    DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD,
    DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
    DEFAULT_ENRICH_AUTHOR_HINDEX,
    DEFAULT_ENRICH_UNPAYWALL,
    DEFAULT_GENERATE_PRISMA_REPORT,
    DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS,
    DEFAULT_RECOVER_MISSING_DOIS,
    DEFAULT_RELEVANCE_WEIGHTS,
    DEFAULT_USE_VENUE_RANKING,
    get_default_quality_filters,
)
from scilex.settings.advanced import merge_advanced_config
from scilex.settings.schema import (
    REQUIRE_CHOICES,
    ConfigFileNotFoundError,
    default_settings_dict,
)

logger = logging.getLogger(__name__)
_DEFAULT_NAME = "my_review"

# Legacy keys the migration translates (anything else is reported and dropped).
_HANDLED_TOP_LEVEL = frozenset(
    {
        "collect_name",
        "output_dir",
        "keywords",
        "years",
        "apis",
        "bonus_keywords",
        "max_articles_per_query",
        "semantic_scholar_mode",
        "quality_filters",
        "aggregate_get_citations",
        "hf_enrichment",
        "pwc_enrichment",
        "since",
        "llm_screening",
        "collect",
        "vpn",
        "generate_prisma_report",
    }
)
_HANDLED_QUALITY_FILTERS = frozenset(get_default_quality_filters()) | {
    "use_venue_ranking",
    "recover_missing_dois",
    "doi_recovery_min_similarity",
    "enrich_unpaywall",
    "enrich_author_hindex",
    "canonical_citation_discrepancy_threshold",
    "unpaywall_email",  # reported separately: it belongs in keys.yml
}


def _warn_ignored_keys(merged: dict) -> None:
    """Log one warning per legacy key that has no equivalent in ``scilex.yml``."""
    for key in merged:
        if key not in _HANDLED_TOP_LEVEL:
            logger.warning(
                "Legacy key %r has no equivalent in scilex.yml and was ignored.", key
            )
    for key in merged.get("quality_filters") or {}:
        if key not in _HANDLED_QUALITY_FILTERS:
            logger.warning(
                "Legacy key 'quality_filters.%s' has no equivalent in scilex.yml "
                "and was ignored.",
                key,
            )
    pwc_defaults = default_settings_dict()["enrichment"]["paperswithcode"]
    for block_name in ("hf_enrichment", "pwc_enrichment"):
        for key in merged.get(block_name) or {}:
            if key not in ("enabled", "use_papers_api") and key not in pwc_defaults:
                logger.warning(
                    "Legacy key '%s.%s' has no equivalent in scilex.yml "
                    "and was ignored.",
                    block_name,
                    key,
                )


def _clean_keyword_groups(keywords):
    """Drop empty groups at the end (``[[a], []]`` becomes ``[[a]]``)."""
    if not isinstance(keywords, list):
        return keywords
    groups = list(keywords)
    while groups and isinstance(groups[-1], list) and not groups[-1]:
        groups.pop()
    return groups


def _allowed_item_types(qf: dict):
    """Item types to keep, or None for "all" (filter disabled or empty list)."""
    if not qf["enable_itemtype_filter"]:
        return None
    allowed = list(qf["allowed_item_types"] or [])
    if not allowed:
        logger.warning(
            "quality_filters.allowed_item_types is empty: migrated as filters."
            "item_types: null (all types accepted)."
        )
        return None
    return allowed


def _llm_screening_block(llm_block: dict, defaults: dict) -> dict:
    """Translate ``llm_screening``; unknown keys are reported and dropped."""
    llm_defaults = defaults["llm_screening"]
    changed = {}
    for key, value in llm_block.items():
        if key not in llm_defaults:
            logger.warning(
                "llm_screening.%s is not a known option (expected one of %s) "
                "and was ignored.",
                key,
                ", ".join(sorted(llm_defaults)),
            )
        elif llm_defaults[key] != value:
            changed[key] = value
    topic = str(changed.get("topic") or "").strip()
    if changed.get("enabled") and not topic:
        logger.warning(
            "llm_screening is enabled without a topic (it could not run): "
            "migrated as disabled. Set llm_screening.topic to enable it."
        )
        changed["enabled"] = False
    return changed


def _set_if_different(
    target: dict, section: str, key: str, value, defaults: dict
) -> None:
    """Store ``value`` under ``target[section][key]`` unless it equals the default."""
    if value != defaults[section][key]:
        target.setdefault(section, {})[key] = value


def _paperswithcode_block(pwc_legacy: dict | None, defaults: dict):
    """Translate a legacy ``pwc_enrichment``/``hf_enrichment`` block.

    Returns None when it is the default (disabled).
    """
    default_block = defaults["enrichment"]["paperswithcode"]
    if pwc_legacy is None:
        # Legacy consumers treat a missing block as enabled.
        return True
    if not pwc_legacy.get("enabled", True):
        return None
    extras = {
        key: value
        for key, value in pwc_legacy.items()
        if key != "enabled" and key in default_block and value != default_block[key]
    }
    return {"enabled": True, **extras} if extras else True


def legacy_to_settings(main_config: dict, advanced_config: dict | None = None) -> dict:
    """Translate legacy configuration dicts to the new format.

    Values equal to the defaults are omitted so the result stays short.

    Args:
        main_config: Content of ``scilex.config.yml``.
        advanced_config: Content of ``scilex.advanced.yml`` (optional).

    Returns:
        A dict ready to be dumped as ``scilex.yml``.
    """
    merged = copy.deepcopy(main_config)
    merge_advanced_config(merged, advanced_config)
    _warn_ignored_keys(merged)
    defaults = default_settings_dict()
    qf = {**get_default_quality_filters(), **(merged.get("quality_filters") or {})}

    result: dict = {"name": merged.get("collect_name", _DEFAULT_NAME)}
    if "output_dir" in merged:
        result["output_dir"] = merged["output_dir"]

    search: dict = {
        "keywords": _clean_keyword_groups(merged.get("keywords", [])),
        "years": merged.get("years", []),
        "apis": merged.get("apis", []),
    }
    if merged.get("bonus_keywords"):
        search["bonus_keywords"] = merged["bonus_keywords"]
    max_articles = merged.get("max_articles_per_query")
    if max_articles is not None and max_articles != -1:
        search["max_articles_per_query"] = max_articles
    mode = merged.get("semantic_scholar_mode", "regular")
    if mode != defaults["search"]["semantic_scholar_mode"]:
        search["semantic_scholar_mode"] = mode
    result["search"] = search

    filters: dict = {}
    wanted = {
        "item_types": _allowed_item_types(qf),
        "always_keep": (
            list(qf["bypass_item_types"]) if qf["enable_itemtype_bypass"] else []
        ),
        "require": [name for name in REQUIRE_CHOICES if qf[f"require_{name}"]],
        "min_authors": qf["min_author_count"],
        "abstract_words": [qf["min_abstract_words"], qf["max_abstract_words"]],
        "abstract_quality": (
            qf["min_abstract_quality_score"] if qf["validate_abstracts"] else None
        ),
        "check_year_range": qf["validate_year_range"],
        "citations": qf["apply_citation_filter"],
    }
    for key, value in wanted.items():
        _set_if_different(filters, "filters", key, value, defaults)
    result.update(filters)

    citations: dict = {}
    _set_if_different(
        citations,
        "citations",
        "fetch",
        merged.get("aggregate_get_citations", True),
        defaults,
    )
    fallbacks = [
        name
        for name, flag in (
            ("semantic_scholar", qf["use_semantic_scholar_citations"]),
            ("openalex", qf["use_openalex_citations"]),
        )
        if flag
    ]
    _set_if_different(citations, "citations", "fallbacks", fallbacks, defaults)
    _set_if_different(
        citations,
        "citations",
        "opencitations",
        qf.get("use_opencitations", True),
        defaults,
    )
    result.update(citations)

    ranking: dict = {}
    _set_if_different(
        ranking, "ranking", "enabled", qf["apply_relevance_ranking"], defaults
    )
    max_papers = qf["max_papers"]
    if isinstance(max_papers, int) and max_papers <= 0:
        max_papers = None  # 0 or negative meant "unlimited" in the legacy format
    _set_if_different(ranking, "ranking", "max_papers", max_papers, defaults)
    weights = {}
    for key, value in qf["relevance_weights"].items():
        if key not in DEFAULT_RELEVANCE_WEIGHTS:
            logger.warning(
                "Legacy weight 'relevance_weights.%s' is unknown (expected %s) "
                "and was ignored.",
                key,
                ", ".join(sorted(DEFAULT_RELEVANCE_WEIGHTS)),
            )
        elif DEFAULT_RELEVANCE_WEIGHTS[key] != value:
            weights[key] = value
    if weights:
        ranking.setdefault("ranking", {})["weights"] = weights
    legacy_types = qf["itemtype_relevance_weights"]
    itemtype_weights = {
        key: bool(legacy_types.get(key, False))
        for key in DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS
        if bool(legacy_types.get(key, False)) != DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS[key]
    }
    itemtype_weights.update(
        {
            k: bool(v)
            for k, v in legacy_types.items()
            if k not in DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS
        }
    )
    if itemtype_weights:
        ranking.setdefault("ranking", {})["itemtype_weights"] = itemtype_weights
    _set_if_different(
        ranking,
        "ranking",
        "venue_ranking",
        bool(qf.get("use_venue_ranking", DEFAULT_USE_VENUE_RANKING)),
        defaults,
    )
    result.update(ranking)

    enrichment: dict = {}
    legacy_block = (
        merged["pwc_enrichment"]
        if "pwc_enrichment" in merged
        else merged.get("hf_enrichment")
    )
    paperswithcode = _paperswithcode_block(legacy_block, defaults)
    if paperswithcode is not None:
        enrichment["paperswithcode"] = paperswithcode
    for new_key, legacy_key, default in (
        ("recover_dois", "recover_missing_dois", DEFAULT_RECOVER_MISSING_DOIS),
        (
            "doi_recovery_min_similarity",
            "doi_recovery_min_similarity",
            DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
        ),
        ("unpaywall", "enrich_unpaywall", DEFAULT_ENRICH_UNPAYWALL),
        ("author_hindex", "enrich_author_hindex", DEFAULT_ENRICH_AUTHOR_HINDEX),
    ):
        value = qf.get(legacy_key, default)
        if value != default:
            enrichment[new_key] = value
    if enrichment:
        result["enrichment"] = enrichment
    if qf.get("unpaywall_email"):
        logger.warning(
            "quality_filters.unpaywall_email cannot be stored in scilex.yml: "
            "put it in keys.yml under Unpaywall.email."
        )

    report: dict = {}
    _set_if_different(
        report, "report", "quality_report", qf["generate_quality_report"], defaults
    )
    _set_if_different(
        report, "report", "track_duplicates", qf["track_duplicate_sources"], defaults
    )
    prisma = merged.get("generate_prisma_report", DEFAULT_GENERATE_PRISMA_REPORT)
    if prisma != defaults["report"]["prisma"]:
        report.setdefault("report", {})["prisma"] = prisma
    result.update(report)

    threshold = qf.get(
        "canonical_citation_discrepancy_threshold",
        DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD,
    )
    if threshold != defaults["citations"]["discrepancy_threshold"]:
        result.setdefault("citations", {})["discrepancy_threshold"] = threshold
    if merged.get("since"):
        result["search"]["since"] = str(merged["since"])
    llm_block = merged.get("llm_screening")
    if isinstance(llm_block, dict):
        changed = _llm_screening_block(llm_block, defaults)
        if changed:
            result["llm_screening"] = changed

    collect: dict = {}
    if merged.get("collect") is False:
        collect["enabled"] = False
    if merged.get("vpn"):
        collect["vpn"] = merged["vpn"]
    if collect:
        result["collect"] = collect
    return result


def migrate_files(legacy_dir: str | Path) -> str:
    """Convert ``scilex.config.yml`` (+ optional advanced file) to ``scilex.yml`` text.

    Args:
        legacy_dir: Directory holding the legacy files.

    Returns:
        YAML text of the new-format configuration.

    Raises:
        FileNotFoundError: If ``scilex.config.yml`` is missing.
    """
    legacy_dir = Path(legacy_dir)
    main_path = legacy_dir / "scilex.config.yml"
    if not main_path.is_file():
        raise ConfigFileNotFoundError(f"Configuration file not found: {main_path}")
    main_config = yaml.safe_load(main_path.read_text()) or {}
    advanced_path = legacy_dir / "scilex.advanced.yml"
    advanced = (
        (yaml.safe_load(advanced_path.read_text()) or {})
        if advanced_path.is_file()
        else None
    )
    new_format = legacy_to_settings(main_config, advanced)
    return yaml.safe_dump(
        new_format, sort_keys=False, default_flow_style=None, allow_unicode=True
    )
