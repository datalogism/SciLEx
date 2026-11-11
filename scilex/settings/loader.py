"""Discovery, merging, validation and legacy conversion of SciLEx settings.

Precedence for ``scilex.yml`` values (lowest to highest):
code defaults < preset < file < CLI overrides.  API keys come from ``keys.yml``
and are overridden by ``SCILEX_<API>_<FIELD>`` environment variables.
"""

import copy
import difflib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scilex.config_defaults import (
    COLLECTOR_API_NAMES,
    DEFAULT_ALLOWED_ITEM_TYPES,
    DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS,
    DEFAULT_RELEVANCE_WEIGHTS,
    MIN_ABSTRACT_QUALITY_SCORE,
)
from scilex.settings.presets import PRESETS, get_preset
from scilex.settings.schema import (
    ConfigFileNotFoundError,
    KeysSettings,
    ScilexSettings,
    SettingsError,
    default_settings_dict,
    format_validation_error,
    migrate_deprecated_huggingface,
)

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "scilex.yml"
USER_KEYS_PATH = Path("~/.config/scilex/keys.yml")
LEGACY_KEYS_PATH = Path(__file__).resolve().parent.parent / "api.config.yml"
# Block names of keys.yml, spelled as the consumers read them (api_config.get(...)).
KEY_BLOCK_NAMES = (
    *COLLECTOR_API_NAMES,
    "CrossRef",
    "Unpaywall",
    "openrouter",
    "Zotero",
    "HuggingFace",
    "ORCID",
)
# SCILEX_* variables that are not API key overrides.
RESERVED_ENV_VARIABLES = frozenset(
    {"SCILEX_CONFIG", "SCILEX_KEYS", "SCILEX_CORS_ORIGINS", "SCILEX_PROFILES_DIR"}
)


@dataclass
class LoadedSettings:
    """Result of :func:`load_settings`."""

    settings: ScilexSettings
    keys: KeysSettings
    provenance: dict[str, str] = field(default_factory=dict)
    config_path: Path | None = None
    keys_path: Path | None = None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def find_config_file(cli_path: str | Path | None = None) -> Path | None:
    """Locate ``scilex.yml``: ``--config`` > ``$SCILEX_CONFIG`` > ``./scilex.yml``.

    Args:
        cli_path: Path given on the command line, if any.

    Returns:
        The path found, or None when nothing exists (the caller handles the
        legacy format).

    Raises:
        FileNotFoundError: If an explicit path (CLI or env) does not exist.
    """
    explicit = cli_path or os.environ.get("SCILEX_CONFIG")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigFileNotFoundError(f"Configuration file not found: {path}")
        return path
    local = Path.cwd() / CONFIG_FILENAME
    return local if local.is_file() else None


def find_keys_file(cli_path: str | Path | None = None) -> Path | None:
    """Locate ``keys.yml``.

    Order: ``--keys`` > ``$SCILEX_KEYS`` > ``~/.config/scilex/keys.yml`` >
    legacy ``scilex/api.config.yml`` (with a deprecation warning).

    Args:
        cli_path: Path given on the command line, if any.

    Returns:
        The path found, or None.

    Raises:
        FileNotFoundError: If an explicit path (CLI or env) does not exist.
    """
    explicit = cli_path or os.environ.get("SCILEX_KEYS")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigFileNotFoundError(f"Keys file not found: {path}")
        return path
    user_path = USER_KEYS_PATH.expanduser()
    if user_path.is_file():
        return user_path
    if LEGACY_KEYS_PATH.is_file():
        logger.warning(
            "Reading API keys from the legacy file %s (deprecated). "
            "Move them to %s or set SCILEX_KEYS.",
            LEGACY_KEYS_PATH,
            USER_KEYS_PATH,
        )
        return LEGACY_KEYS_PATH
    return None


# ---------------------------------------------------------------------------
# Merging and provenance
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (mutates ``base``).

    An empty mapping in ``override`` changes nothing; only ``None`` replaces a
    section.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to ``{dotted.path: leaf}`` (empty dicts are leaves)."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(_flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


def _normalize_layer(layer: dict) -> dict:
    """Expand shorthands of a user layer so deep merging behaves.

    ``enrichment.paperswithcode: true`` becomes ``{enabled: true}`` and a block
    without ``enabled`` means enabled. The deprecated ``huggingface`` key is
    renamed first (with a warning) so it merges onto the right default.
    """
    layer = copy.deepcopy(layer)
    enrichment = layer.get("enrichment")
    if isinstance(enrichment, dict) and "huggingface" in enrichment:
        try:
            layer["enrichment"] = enrichment = migrate_deprecated_huggingface(
                enrichment
            )
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
    if isinstance(enrichment, dict) and "paperswithcode" in enrichment:
        block = enrichment["paperswithcode"]
        if isinstance(block, bool):
            enrichment["paperswithcode"] = {"enabled": block}
        elif isinstance(block, dict) and "enabled" not in block:
            block["enabled"] = True
    return layer


def _read_yaml(path: Path) -> dict:
    """Parse a YAML mapping file."""
    try:
        with open(path) as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise SettingsError(f"{path}: invalid YAML ({exc})") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a mapping at the top level")
    return data


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def _suggestion(name: str, candidates) -> str:
    """Return `` Did you mean 'X'?`` for the closest candidate (case-insensitive)."""
    by_lower = {candidate.lower(): candidate for candidate in candidates}
    close = difflib.get_close_matches(name.lower(), list(by_lower), n=1, cutoff=0.6)
    return f" Did you mean {by_lower[close[0]]!r}?" if close else ""


def _warn_unknown_key_blocks(keys_raw: dict, keys_path: Path | None) -> None:
    """Warn about ``keys.yml`` blocks no consumer reads (typos such as ``Crossref``)."""
    accepted = set(KEY_BLOCK_NAMES) | {"rate_limits", "zotero", "vpn"}
    for name in keys_raw:
        if name not in accepted:
            logger.warning(
                "%s: unknown block %r is ignored.%s",
                keys_path or "keys",
                name,
                _suggestion(name, KEY_BLOCK_NAMES),
            )


def _apply_env_keys(keys_raw: dict, provenance: dict[str, str]) -> None:
    """Apply ``SCILEX_<API>_<FIELD>`` environment overrides to ``keys_raw``.

    The block is created when the file does not have it. The block name is the
    canonical spelling read by the consumers (``CrossRef``, ``Unpaywall``,
    ``openrouter``...). An unknown API name is reported, not ignored.
    """
    api_by_upper = {name.upper(): name for name in KEY_BLOCK_NAMES}
    for variable, value in os.environ.items():
        if not variable.startswith("SCILEX_") or variable in RESERVED_ENV_VARIABLES:
            continue
        api_part, _, field_part = variable[len("SCILEX_") :].partition("_")
        api_name = api_by_upper.get(api_part.upper())
        if api_name is None or not field_part:
            logger.warning(
                "%s is not a valid override (expected SCILEX_<API>_<FIELD>) "
                "and is ignored.%s",
                variable,
                _suggestion(api_part, KEY_BLOCK_NAMES) if api_name is None else "",
            )
            continue
        block = keys_raw.get(api_name)
        if not isinstance(block, dict):
            block = keys_raw[api_name] = {}
        block[field_part.lower()] = value
        provenance[f"keys.{api_name}.{field_part.lower()}"] = "env"


def _load_keys(keys_path: Path | None, provenance: dict[str, str]) -> KeysSettings:
    keys_raw = _read_yaml(keys_path) if keys_path else {}
    for dotted in _flatten(keys_raw):
        provenance[f"keys.{dotted}"] = "file"
    _warn_unknown_key_blocks(keys_raw, keys_path)
    _apply_env_keys(keys_raw, provenance)
    try:
        return KeysSettings.model_validate(keys_raw)
    except ValidationError as exc:
        detail = format_validation_error(
            exc, keys_raw, model=KeysSettings, prefix="keys."
        )
        raise SettingsError(f"{keys_path or 'keys'}: invalid keys\n{detail}") from exc


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_settings(
    config_path: str | Path | None = None,
    keys_path: str | Path | None = None,
    cli_overrides: dict | None = None,
) -> LoadedSettings:
    """Load, merge and validate settings and keys.

    Args:
        config_path: Explicit ``scilex.yml`` path (otherwise discovered).
        keys_path: Explicit ``keys.yml`` path (otherwise discovered).
        cli_overrides: Nested dict in the ``scilex.yml`` format, highest precedence.

    Returns:
        The validated settings, keys and per-key provenance.

    Raises:
        FileNotFoundError: If no configuration file can be found.
        SettingsError: If the configuration is invalid.
    """
    resolved_config = find_config_file(config_path)
    if resolved_config is None:
        raise ConfigFileNotFoundError(
            f"No {CONFIG_FILENAME} found (use --config, $SCILEX_CONFIG or create ./{CONFIG_FILENAME})"
        )
    resolved_keys = find_keys_file(keys_path)

    file_layer = _normalize_layer(_read_yaml(resolved_config))
    cli_layer = _normalize_layer(cli_overrides or {})

    preset_name = cli_layer.get("preset", file_layer.get("preset"))
    if preset_name is not None and preset_name not in PRESETS:
        raise SettingsError(
            f"preset: unknown preset (got: {preset_name!r}). Available: {', '.join(PRESETS)}"
        )

    layers: list[tuple[str, dict]] = [("default", default_settings_dict())]
    if preset_name is not None:
        layers.append(
            (f"preset:{preset_name}", _normalize_layer(get_preset(preset_name)))
        )
    layers.append(("file", file_layer))
    layers.append(("cli", cli_layer))

    merged: dict = {}
    provenance: dict[str, str] = {}
    for source, layer in layers:
        _deep_merge(merged, layer)
        for dotted in _flatten(layer):
            provenance[dotted] = source

    try:
        settings = ScilexSettings.model_validate(merged)
    except ValidationError as exc:
        detail = format_validation_error(exc, merged)
        raise SettingsError(
            f"{resolved_config}: invalid configuration\n{detail}"
        ) from exc

    keys = _load_keys(resolved_keys, provenance)
    return LoadedSettings(
        settings=settings,
        keys=keys,
        provenance=provenance,
        config_path=resolved_config,
        keys_path=resolved_keys,
    )


# ---------------------------------------------------------------------------
# Legacy conversion
# ---------------------------------------------------------------------------


def _add_non_default_keys(
    main_config: dict, quality_filters: dict, settings: ScilexSettings
) -> None:
    """Emit the keys that legacy code reads with ``.get(key, DEFAULT)``.

    They are added only when they differ from their default, so a config without
    them yields exactly the historical legacy dictionary.
    """
    defaults = ScilexSettings.model_validate(
        {
            "name": "_",
            "search": {
                "keywords": [["_"]],
                "years": [2000],
                "apis": [COLLECTOR_API_NAMES[0]],
            },
        }
    )
    enrichment, default_enrichment = settings.enrichment, defaults.enrichment
    quality_pairs = (
        (
            "canonical_citation_discrepancy_threshold",
            settings.citations.discrepancy_threshold,
            defaults.citations.discrepancy_threshold,
        ),
        (
            "recover_missing_dois",
            enrichment.recover_dois,
            default_enrichment.recover_dois,
        ),
        (
            "doi_recovery_min_similarity",
            enrichment.doi_recovery_min_similarity,
            default_enrichment.doi_recovery_min_similarity,
        ),
        ("enrich_unpaywall", enrichment.unpaywall, default_enrichment.unpaywall),
        (
            "enrich_author_hindex",
            enrichment.author_hindex,
            default_enrichment.author_hindex,
        ),
        (
            "use_venue_ranking",
            settings.ranking.venue_ranking,
            defaults.ranking.venue_ranking,
        ),
    )
    for legacy_key, value, default in quality_pairs:
        if value != default:
            quality_filters[legacy_key] = value
    if settings.report.prisma != defaults.report.prisma:
        main_config["generate_prisma_report"] = settings.report.prisma
    if settings.search.since is not None:
        main_config["since"] = settings.search.since
    if settings.llm_screening != defaults.llm_screening:
        main_config["llm_screening"] = settings.llm_screening.model_dump()


def keys_to_legacy(keys: KeysSettings | None) -> dict:
    """Convert validated keys to the legacy ``api_config`` dictionary."""
    if keys is None:
        return {}
    api_config: dict[str, Any] = {
        name: copy.deepcopy(block) for name, block in (keys.model_extra or {}).items()
    }
    if keys.rate_limits is not None:
        api_config["rate_limits"] = copy.deepcopy(keys.rate_limits)
    return api_config


def to_legacy(
    settings: ScilexSettings, keys: KeysSettings | None = None
) -> tuple[dict, dict]:
    """Convert settings to the legacy ``(main_config, api_config)`` dicts.

    Args:
        settings: Validated settings.
        keys: Validated API keys (None means no keys).

    Returns:
        ``(main_config, api_config)`` in the shape consumed by ``SciLExConfig``.
    """
    search, filters = settings.search, settings.filters
    ranking, pwc = settings.ranking, settings.enrichment.paperswithcode

    quality_filters = {
        "enable_itemtype_bypass": bool(filters.always_keep),
        "bypass_item_types": list(filters.always_keep),
        "enable_itemtype_filter": filters.item_types is not None,
        "allowed_item_types": list(
            filters.item_types
            if filters.item_types is not None
            else DEFAULT_ALLOWED_ITEM_TYPES
        ),
        "require_abstract": "abstract" in filters.require,
        "require_doi": "doi" in filters.require,
        "require_year": "year" in filters.require,
        "require_open_access": "open_access" in filters.require,
        "min_author_count": filters.min_authors,
        "min_abstract_words": filters.abstract_words[0],
        "max_abstract_words": filters.abstract_words[1],
        "validate_year_range": filters.check_year_range,
        "validate_abstracts": filters.abstract_quality is not None,
        "min_abstract_quality_score": (
            filters.abstract_quality
            if filters.abstract_quality is not None
            else MIN_ABSTRACT_QUALITY_SCORE
        ),
        "generate_quality_report": settings.report.quality_report,
        "apply_citation_filter": filters.citations,
        "use_semantic_scholar_citations": "semantic_scholar"
        in settings.citations.fallbacks,
        "use_openalex_citations": "openalex" in settings.citations.fallbacks,
        "use_opencitations": settings.citations.opencitations,
        "apply_relevance_ranking": ranking.enabled,
        "relevance_weights": {**DEFAULT_RELEVANCE_WEIGHTS, **ranking.weights},
        "itemtype_relevance_weights": {
            **DEFAULT_ITEMTYPE_RELEVANCE_WEIGHTS,
            **ranking.itemtype_weights,
        },
        "max_papers": ranking.max_papers,
        "track_duplicate_sources": settings.report.track_duplicates,
    }

    main_config: dict[str, Any] = {
        "collect_name": settings.name,
        "output_dir": settings.output_dir,
        "keywords": [list(group) for group in search.keywords],
        "bonus_keywords": list(search.bonus_keywords),
        "years": list(search.years),
        "apis": list(search.apis),
        "semantic_scholar_mode": search.semantic_scholar_mode,
        "aggregate_get_citations": settings.citations.fetch,
        "pwc_enrichment": (
            pwc.model_dump(exclude=set() if pwc.workers != 4 else {"workers"})
            if pwc.enabled
            else {"enabled": False}
        ),
        "quality_filters": quality_filters,
    }
    if search.max_articles_per_query is not None:
        main_config["max_articles_per_query"] = search.max_articles_per_query
    if not settings.collect.enabled:
        main_config["collect"] = False
    if settings.collect.vpn is not None:
        main_config["vpn"] = copy.deepcopy(settings.collect.vpn)
    if settings.subcorpora.required:
        main_config["required_subcorpora"] = list(settings.subcorpora.required)
    _add_non_default_keys(main_config, quality_filters, settings)

    return main_config, keys_to_legacy(keys)
