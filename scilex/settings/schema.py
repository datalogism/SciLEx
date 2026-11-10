"""Pydantic models describing the ``scilex.yml`` and ``keys.yml`` formats.

The models mirror ADR 0003 section 2. Every model forbids unknown keys so a
typo is reported instead of being silently ignored.
"""

import copy
import difflib
import logging
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from scilex.config_defaults import (
    COLLECTOR_API_NAMES,
    DEFAULT_APPLY_CITATION_FILTER,
    DEFAULT_APPLY_RELEVANCE_RANKING,
    DEFAULT_BYPASS_ITEM_TYPES,
    DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD,
    DEFAULT_COLLECT_ENABLED,
    DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
    DEFAULT_ENRICH_AUTHOR_HINDEX,
    DEFAULT_ENRICH_UNPAYWALL,
    DEFAULT_GENERATE_PRISMA_REPORT,
    DEFAULT_GENERATE_QUALITY_REPORT,
    DEFAULT_MAX_PAPERS,
    DEFAULT_RECOVER_MISSING_DOIS,
    DEFAULT_RELEVANCE_WEIGHTS,
    DEFAULT_TRACK_DUPLICATE_SOURCES,
    DEFAULT_USE_OPENCITATIONS,
    DEFAULT_USE_VENUE_RANKING,
    DEFAULT_VALIDATE_YEAR_RANGE,
    MAX_ABSTRACT_WORDS,
    MIN_ABSTRACT_WORDS,
    MIN_AUTHOR_COUNT,
)

REQUIRE_CHOICES = ("abstract", "doi", "year", "open_access")
_YEAR_RANGE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$")
logger = logging.getLogger(__name__)

_STRICT = ConfigDict(extra="forbid")
MIN_YEAR, MAX_YEAR = 1000, 3000


def _reject_bool(value: Any) -> Any:
    """Refuse ``true``/``false`` where an integer is expected (``False`` is 0)."""
    if isinstance(value, bool):
        raise ValueError("expected an integer, not a boolean (true/false)")
    return value


Integer = Annotated[int, BeforeValidator(_reject_bool)]
Year = Annotated[int, BeforeValidator(_reject_bool), Field(ge=MIN_YEAR, le=MAX_YEAR)]


class SettingsError(ValueError):
    """Raised when a configuration file is invalid; the message is user-ready."""


class ConfigFileNotFoundError(FileNotFoundError):
    """Raised when a configuration or keys file cannot be found (message names it)."""


class SearchSettings(BaseModel):
    """What to search for and where."""

    model_config = _STRICT

    keywords: list[list[str]]
    bonus_keywords: list[str] = Field(default_factory=list)
    years: list[Year]
    apis: list[str]
    max_articles_per_query: Integer | None = None
    semantic_scholar_mode: Literal["regular", "bulk"] = "regular"
    since: str | None = None

    @field_validator("since", mode="before")
    @classmethod
    def _normalize_since(cls, value: Any) -> Any:
        """Accept a YAML date or a ``YYYY-MM-DD`` string; reject anything else."""
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("expected a date in YYYY-MM-DD format") from exc

    @field_validator("keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, value: Any) -> Any:
        """Accept a flat list of strings as a single keyword group."""
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            return [value]
        return value

    @field_validator("keywords")
    @classmethod
    def _check_groups(cls, value: list[list[str]]) -> list[list[str]]:
        """Require 1 or 2 non-empty groups."""
        if not 1 <= len(value) <= 2:
            raise ValueError("expected 1 or 2 keyword groups")
        if any(not group for group in value):
            raise ValueError("a keyword group must not be empty")
        if any(not keyword.strip() for group in value for keyword in group):
            raise ValueError("keywords must not be empty strings")
        return value

    @field_validator("bonus_keywords")
    @classmethod
    def _check_bonus_keywords(cls, value: list[str]) -> list[str]:
        """Reject empty bonus keywords (they would match every paper)."""
        if any(not keyword.strip() for keyword in value):
            raise ValueError("bonus keywords must not be empty strings")
        return value

    @field_validator("years", mode="before")
    @classmethod
    def _normalize_years(cls, value: Any) -> Any:
        """Accept ``"YYYY-YYYY"`` or a single int and expand to a list."""
        if isinstance(value, str):
            match = _YEAR_RANGE.match(value)
            if not match:
                raise ValueError('expected a list of years or a "YYYY-YYYY" range')
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                raise ValueError("year range start is after its end")
            return list(range(start, end + 1))
        if isinstance(value, int) and not isinstance(value, bool):
            return [value]
        return value

    @field_validator("years")
    @classmethod
    def _check_years(cls, value: list[int]) -> list[int]:
        """Require at least one year; drop duplicates and sort."""
        if not value:
            raise ValueError("at least one year is required")
        return sorted(set(value))

    @field_validator("apis")
    @classmethod
    def _check_apis(cls, value: list[str]) -> list[str]:
        """Require at least one API, each one a known collector."""
        if not value:
            raise ValueError("at least one API is required")
        for name in value:
            if name not in COLLECTOR_API_NAMES:
                close = difflib.get_close_matches(str(name), COLLECTOR_API_NAMES, n=1)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                raise ValueError(
                    f"unknown API {name!r}.{hint} Available: {', '.join(COLLECTOR_API_NAMES)}"
                )
        return value


class FiltersSettings(BaseModel):
    """Quality filters applied during aggregation."""

    model_config = _STRICT

    item_types: list[str] | None = None
    always_keep: list[str] = Field(
        default_factory=lambda: list(DEFAULT_BYPASS_ITEM_TYPES)
    )
    require: list[Literal["abstract", "doi", "year", "open_access"]] = Field(
        default_factory=lambda: ["abstract", "year"]
    )
    min_authors: Integer = Field(default=MIN_AUTHOR_COUNT, ge=0)
    abstract_words: list[Integer] = Field(
        default_factory=lambda: [MIN_ABSTRACT_WORDS, MAX_ABSTRACT_WORDS]
    )
    abstract_quality: Integer | None = Field(default=None, ge=0, le=100)
    check_year_range: bool = DEFAULT_VALIDATE_YEAR_RANGE
    citations: bool = DEFAULT_APPLY_CITATION_FILTER

    @field_validator("item_types")
    @classmethod
    def _check_item_types(cls, value: list[str] | None) -> list[str] | None:
        """Refuse an empty list, which would keep nothing."""
        if value is not None and not value:
            raise ValueError(
                "an empty list would reject every paper; "
                "use null (or omit the key) to accept all item types"
            )
        return value

    @field_validator("abstract_words")
    @classmethod
    def _check_words(cls, value: list[int]) -> list[int]:
        """Require ``[min, max]`` with ``0 <= min <= max``."""
        if len(value) != 2:
            raise ValueError("expected [min, max]")
        if value[0] < 0 or value[0] > value[1]:
            raise ValueError("expected [min, max] with 0 <= min <= max")
        return value


class CitationsSettings(BaseModel):
    """Citation fetching."""

    model_config = _STRICT

    fetch: bool = True
    fallbacks: list[Literal["semantic_scholar", "openalex"]] = Field(
        default_factory=lambda: ["semantic_scholar", "openalex"]
    )
    opencitations: bool = DEFAULT_USE_OPENCITATIONS
    discrepancy_threshold: float = Field(
        default=DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD, ge=0
    )


class RankingSettings(BaseModel):
    """Relevance ranking and size cap."""

    model_config = _STRICT

    enabled: bool = DEFAULT_APPLY_RELEVANCE_RANKING
    max_papers: Integer | None = Field(default=DEFAULT_MAX_PAPERS, ge=1)
    weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_RELEVANCE_WEIGHTS)
    )
    itemtype_weights: dict[str, bool] = Field(default_factory=dict)
    venue_ranking: bool = DEFAULT_USE_VENUE_RANKING

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        """Restrict weight names and forbid negative values."""
        unknown = sorted(set(value) - set(DEFAULT_RELEVANCE_WEIGHTS))
        if unknown:
            raise ValueError(
                f"unknown weight(s) {unknown}; expected {sorted(DEFAULT_RELEVANCE_WEIGHTS)}"
            )
        if any(weight < 0 for weight in value.values()):
            raise ValueError("weights must be >= 0")
        return value


class PapersWithCodeSettings(BaseModel):
    """Papers with Code enrichment; ``paperswithcode: true`` is a shorthand."""

    model_config = _STRICT

    enabled: bool = False
    fuzzy_match_threshold: Integer = Field(default=85, ge=0, le=100)
    cache_path: str = "output/pwc_cache.db"
    cache_ttl_days: Integer = Field(default=30, ge=0)
    workers: Integer = Field(default=4, ge=1, le=32)

    @model_validator(mode="before")
    @classmethod
    def _from_bool(cls, value: Any) -> Any:
        """Expand the boolean shorthand."""
        if isinstance(value, bool):
            return {"enabled": value}
        return value


def migrate_deprecated_huggingface(enrichment: dict) -> dict:
    """Move the deprecated ``huggingface`` key to ``paperswithcode``.

    ``use_papers_api`` (HuggingFace only) is silently dropped. Returns a new
    dict; the input is left untouched.

    Raises:
        ValueError: if both ``huggingface`` and ``paperswithcode`` are present.
    """
    if "huggingface" not in enrichment:
        return enrichment
    if "paperswithcode" in enrichment:
        raise ValueError(
            "enrichment.huggingface (deprecated) and enrichment.paperswithcode "
            "are both set; keep only enrichment.paperswithcode"
        )
    migrated = dict(enrichment)
    block = migrated.pop("huggingface")
    if isinstance(block, dict):
        block = {key: val for key, val in block.items() if key != "use_papers_api"}
    logger.warning(
        "enrichment.huggingface is deprecated: enrichment now uses Papers with "
        "Code. Rename it to enrichment.paperswithcode."
    )
    migrated["paperswithcode"] = block
    return migrated


class EnrichmentSettings(BaseModel):
    """Optional enrichment steps."""

    model_config = _STRICT

    paperswithcode: PapersWithCodeSettings = Field(
        default_factory=PapersWithCodeSettings
    )
    recover_dois: bool = DEFAULT_RECOVER_MISSING_DOIS
    doi_recovery_min_similarity: float = Field(
        default=DEFAULT_DOI_RECOVERY_MIN_SIMILARITY, ge=0, le=1
    )
    unpaywall: bool = DEFAULT_ENRICH_UNPAYWALL
    author_hindex: bool = DEFAULT_ENRICH_AUTHOR_HINDEX

    @model_validator(mode="before")
    @classmethod
    def _accept_deprecated_huggingface(cls, value: Any) -> Any:
        """Translate the deprecated ``huggingface`` key."""
        if isinstance(value, dict):
            return migrate_deprecated_huggingface(value)
        return value


class ReportSettings(BaseModel):
    """Aggregation reports."""

    model_config = _STRICT

    quality_report: bool = DEFAULT_GENERATE_QUALITY_REPORT
    track_duplicates: bool = DEFAULT_TRACK_DUPLICATE_SOURCES
    prisma: bool = DEFAULT_GENERATE_PRISMA_REPORT


class CollectSettings(BaseModel):
    """Rarely used collection options."""

    model_config = _STRICT

    enabled: bool = DEFAULT_COLLECT_ENABLED
    vpn: dict[str, Any] | None = None


class SubcorporaSettings(BaseModel):
    """Sub-corpora (Zotero collections) of a review.

    ``required``: every paper must belong to at least one collection with one of
    these names, or to a sub-collection of one (e.g. ``[datasets, surveys,
    models]``). Checked in Consolidate and filterable in Explore.
    """

    model_config = _STRICT

    required: list[str] = Field(default_factory=list)

    @field_validator("required")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if name and name.strip()]
        if len({name.casefold() for name in cleaned}) != len(cleaned):
            raise ValueError("subcorpora.required lists a name twice")
        return cleaned


class LLMScreeningSettings(BaseModel):
    """Optional LLM relevance screening (OpenRouter), see ``llm_relevance.py``."""

    model_config = _STRICT

    enabled: bool = False
    topic: str = ""
    model: str = "deepseek/deepseek-v4-flash"
    threshold: float | None = None
    max_papers: Integer = Field(default=500, ge=1)
    workers: Integer = Field(default=16, ge=1, le=64)
    price_input_per_m: float = Field(default=0.091, ge=0)
    price_output_per_m: float = Field(default=0.182, ge=0)

    @model_validator(mode="after")
    def _require_topic_when_enabled(self) -> "LLMScreeningSettings":
        """Screening without a topic cannot work: fail at load time."""
        if self.enabled and not self.topic.strip():
            raise ValueError(
                "llm_screening.topic is required when llm_screening.enabled is true"
            )
        return self


class ScilexSettings(BaseModel):
    """Top-level model of ``scilex.yml``."""

    model_config = _STRICT

    name: str = Field(min_length=1)
    output_dir: str = "output"
    preset: Literal["literature_review", "bibliometrics"] | None = None
    search: SearchSettings
    filters: FiltersSettings = Field(default_factory=FiltersSettings)
    citations: CitationsSettings = Field(default_factory=CitationsSettings)
    ranking: RankingSettings = Field(default_factory=RankingSettings)
    enrichment: EnrichmentSettings = Field(default_factory=EnrichmentSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    collect: CollectSettings = Field(default_factory=CollectSettings)
    llm_screening: LLMScreeningSettings = Field(default_factory=LLMScreeningSettings)
    subcorpora: SubcorporaSettings = Field(default_factory=SubcorporaSettings)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        """The name is a folder under ``output_dir``: keep it a single plain component."""
        if not value.strip():
            raise ValueError("name must not be blank")
        if "/" in value or "\\" in value or value.startswith("."):
            raise ValueError(
                "name is used as a folder name: no '/', '\\' and no leading '.'"
            )
        return value


class KeysSettings(BaseModel):
    """Content of ``keys.yml``: one free-form mapping per API plus rate limits."""

    model_config = ConfigDict(extra="allow")

    rate_limits: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_api_blocks(self) -> "KeysSettings":
        """Require each API entry to be a mapping (``None`` becomes empty)."""
        for api_name, block in (self.model_extra or {}).items():
            if block is None:
                self.model_extra[api_name] = {}
            elif not isinstance(block, dict):
                raise ValueError(
                    f"{api_name}: expected a mapping of fields (got {block!r})"
                )
        return self


# ---------------------------------------------------------------------------
# Defaults and error formatting
# ---------------------------------------------------------------------------

_REQUIRED_SEARCH_KEYS = ("keywords", "years", "apis")


def default_settings_dict() -> dict:
    """Return the raw defaults (every field except the required ones)."""
    probe = ScilexSettings.model_validate(
        {
            "name": "_",
            "search": {
                "keywords": [["_"]],
                "years": [2000],
                "apis": [COLLECTOR_API_NAMES[0]],
            },
        }
    ).model_dump(mode="python")
    probe.pop("name")
    for key in _REQUIRED_SEARCH_KEYS:
        probe["search"].pop(key)
    return copy.deepcopy(probe)


def known_paths(model: type[BaseModel] = ScilexSettings, prefix: str = "") -> list[str]:
    """List every dotted configuration path accepted by ``model``."""
    paths: list[str] = []
    for field_name, field in model.model_fields.items():
        dotted = f"{prefix}{field_name}"
        annotation = field.annotation
        paths.append(dotted)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(known_paths(annotation, f"{dotted}."))
    return paths


def _suggest(unknown_path: str, candidates: list[str]) -> str | None:
    """Return the known path whose last segment best matches the unknown key."""
    parent, _, last = unknown_path.rpartition(".")
    best_score, best_path = 0.0, None
    for path in candidates:
        candidate_parent, _, candidate_last = path.rpartition(".")
        score = difflib.SequenceMatcher(None, last, candidate_last).ratio()
        if candidate_parent == parent:
            score += 0.01  # prefer the same section on near ties
        if score > best_score:
            best_score, best_path = score, path
    return best_path if best_score >= 0.7 else None


def _lookup(raw: Any, loc: tuple) -> tuple[bool, Any]:
    """Fetch ``raw[loc...]``; return ``(found, value)``."""
    current = raw
    for part in loc:
        if (
            isinstance(current, dict)
            and part in current
            or (
                isinstance(current, list)
                and isinstance(part, int)
                and part < len(current)
            )
        ):
            current = current[part]
        else:
            return False, None
    return True, current


def _short(value: Any, limit: int = 60) -> str:
    """Return a truncated ``repr`` of ``value``."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_validation_error(
    exc: ValidationError,
    raw_dict: dict,
    *,
    model: type[BaseModel] = ScilexSettings,
    prefix: str = "",
) -> str:
    """Render a pydantic error as readable ``path: message (got: value)`` lines.

    Args:
        exc: The validation error raised by pydantic.
        raw_dict: The raw mapping that was validated (used to show offending values).
        model: Model whose field paths feed the "did you mean" suggestions.
        prefix: Prepended to every path (for example ``"keys."``).

    Returns:
        A multi-line message, one line per problem.
    """
    candidates = known_paths(model)
    lines = []
    for error in exc.errors():
        loc = tuple(error["loc"])
        dotted = ".".join(str(part) for part in loc)
        path = prefix + dotted
        kind = error["type"]
        found, value = _lookup(raw_dict, loc)
        if not found:
            value = error.get("input")
        if kind == "missing":
            lines.append(f"{path}: required key is missing")
        elif kind == "extra_forbidden":
            suggestion = _suggest(dotted, candidates)
            hint = f" Did you mean {prefix}{suggestion}?" if suggestion else ""
            lines.append(f"{path}: unknown key.{hint}")
        else:
            message = error["msg"].removeprefix("Value error, ")
            lines.append(f"{path}: {message} (got: {_short(value)})")
    return "\n".join(lines)
