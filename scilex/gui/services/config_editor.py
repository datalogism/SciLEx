"""Read, validate and write a review's ``scilex.yml`` for the form editor.

UI-independent. The editor works on a plain nested dict (the "editable"
dict): code defaults, then the review's preset, then the values of the file.
Saving writes back **only** what differs from defaults (and preset), so the
file stays short; YAML comments of the previous file are not kept.
"""

from __future__ import annotations

import copy
import os
import re
import types
import typing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError

from scilex.config_defaults import COLLECTOR_API_NAMES
from scilex.gui.services.workspace import Review
from scilex.settings.loader import _deep_merge, _flatten, _normalize_layer
from scilex.settings.presets import PRESETS, get_preset
from scilex.settings.schema import (
    ScilexSettings,
    SettingsError,
    _suggest,
    default_settings_dict,
    format_validation_error,
    known_paths,
)

API_NAMES: tuple[str, ...] = COLLECTOR_API_NAMES
MAX_KEYWORD_GROUPS = 2
_YEAR_RANGE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$")

# Keys always written, even when equal to their (empty) default.
REQUIRED_PATHS = (
    ("name",),
    ("search", "keywords"),
    ("search", "years"),
    ("search", "apis"),
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_file_layer(path: Path) -> dict:
    """Parse ``path`` into a mapping (``{}`` when empty)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsError(f"{path}: not valid YAML ({exc})") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError(f"{path}: expected a mapping at the top level")
    return raw


def _expand_years(value: Any) -> Any:
    """Turn ``"2020-2023"`` or ``2020`` into a list; other values are untouched."""
    if isinstance(value, str):
        match = _YEAR_RANGE.match(value)
        if match and int(match.group(1)) <= int(match.group(2)):
            return list(range(int(match.group(1)), int(match.group(2)) + 1))
    elif isinstance(value, int) and not isinstance(value, bool):
        return [value]
    return value


def _normalize_file_layer(layer: dict) -> dict:
    """Expand the shorthands of a file so the form sees canonical values."""
    layer = _normalize_layer(layer)
    search = layer.get("search")
    if isinstance(search, dict):
        keywords = search.get("keywords")
        if (
            isinstance(keywords, list)
            and keywords
            and all(isinstance(k, str) for k in keywords)
        ):
            search["keywords"] = [keywords]
        if "years" in search:
            search["years"] = _expand_years(search["years"])
        since = search.get("since")
        if isinstance(since, datetime):
            search["since"] = since.date().isoformat()
        elif isinstance(since, date):
            search["since"] = since.isoformat()
    return layer


def base_dict(preset: str | None = None) -> dict:
    """Return the values in force without the file: defaults, then ``preset``."""
    base = default_settings_dict()
    base["name"] = ""
    base["search"].update({"keywords": [[]], "years": [], "apis": []})
    if preset in PRESETS:
        _deep_merge(base, _normalize_layer(get_preset(preset)))
    base.setdefault("preset", None)
    return base


def load_editable(review: Review) -> dict:
    """Return the review's values: defaults < preset < ``scilex.yml``.

    Raises:
        SettingsError: If the file is not valid YAML.
        FileNotFoundError: If the review has no ``scilex.yml``.
    """
    layer = _normalize_file_layer(_read_file_layer(review.config_path))
    preset = layer.get("preset")
    merged = base_dict(preset if isinstance(preset, str) else None)
    _deep_merge(merged, layer)
    return merged


def origins(review: Review) -> dict[str, str]:
    """Return ``{dotted.path: "preset" | "file"}`` for the non-default values."""
    layer = _normalize_file_layer(_read_file_layer(review.config_path))
    result: dict[str, str] = {}
    preset = layer.get("preset")
    if isinstance(preset, str) and preset in PRESETS:
        for dotted in _flatten(_normalize_layer(get_preset(preset))):
            result[dotted] = "preset"
    for dotted in _flatten(layer):
        result[dotted] = "file"
    return result


def origin_of(path: str, known: dict[str, str]) -> str:
    """Origin of ``path`` (a leaf or a section) given :func:`origins`."""
    if path in known:
        return known[path]
    inner = [origin for key, origin in known.items() if key.startswith(f"{path}.")]
    if "file" in inner:
        return "file"
    return "preset" if inner else "default"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(data: dict) -> list[tuple[str, str]]:
    """Validate ``data`` with the pydantic model.

    Returns:
        ``(dotted_path, message)`` pairs; empty when the data is valid.
    """
    try:
        ScilexSettings.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            path = ".".join(str(part) for part in error["loc"])
            kind = error["type"]
            if kind == "missing":
                message = "this value is required"
            elif kind == "extra_forbidden":
                message = "unknown key"
            else:
                message = error["msg"].removeprefix("Value error, ")
            problems.append((path, message))
        return problems
    return []


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

_SAME = object()


def _diff(value: Any, base: Any) -> Any:
    """Return the part of ``value`` that differs from ``base`` (``_SAME`` if none)."""
    if isinstance(value, dict) and isinstance(base, dict):
        changed = {}
        for key, item in value.items():
            if key not in base:
                changed[key] = copy.deepcopy(item)
                continue
            inner = _diff(item, base[key])
            if inner is not _SAME:
                changed[key] = inner
        return changed if changed else _SAME
    return _SAME if value == base else copy.deepcopy(value)


def _compact_years(years: Any) -> Any:
    """Write a run of 3+ consecutive years as ``"YYYY-YYYY"``."""
    if (
        isinstance(years, list)
        and len(years) >= 3
        and all(isinstance(y, int) for y in years)
        and years == list(range(years[0], years[-1] + 1))
    ):
        return f"{years[0]}-{years[-1]}"
    return years


def _keep_explicit(result: dict, data: dict, explicit: dict) -> None:
    """Copy into ``result`` the values of ``data`` the user wrote in the file.

    A value equal to the code default is still written when the file had it:
    otherwise a later change of that default would silently change the review.
    """
    for key, written in explicit.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(written, dict) and isinstance(value, dict):
            nested = result.get(key)
            nested = nested if isinstance(nested, dict) else {}
            _keep_explicit(nested, value, written)
            if nested:
                result[key] = nested
        elif key not in result:
            result[key] = copy.deepcopy(value)


def to_file_dict(data: dict, explicit: dict | None = None) -> dict:
    """Return the minimal dict to write for ``data``.

    Args:
        data: Full form data.
        explicit: Mapping already written in the file; its keys are kept even
            when their value equals the default.

    Returns:
        Non-default values, required keys and the file's explicit keys.
    """
    preset = data.get("preset")
    changed = _diff(data, base_dict(preset if isinstance(preset, str) else None))
    result: dict = {} if changed is _SAME else changed
    if explicit:
        _keep_explicit(result, data, explicit)
    for path in REQUIRED_PATHS:
        source, target = data, result
        for key in path[:-1]:
            source = source[key]
            target = target.setdefault(key, {})
        target[path[-1]] = copy.deepcopy(source[path[-1]])
    result["search"]["years"] = _compact_years(sorted(set(result["search"]["years"])))
    ordered = {
        key: result[key] for key in ("name", "output_dir", "preset") if key in result
    }
    ordered.update({key: value for key, value in result.items() if key not in ordered})
    return ordered


def _atomic_write(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` through a temporary file, cleaned on failure.

    Each save of a ``scilex.yml`` is journaled with the file's fingerprint (a
    rename is journaled when the review is next read, see workspace).
    """
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    import hashlib

    from scilex.gui.services import journal

    journal.append(
        target.parent,
        "configure",
        generated={"scilex.yml sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
    )


def save(review: Review, data: dict) -> Path:
    """Validate ``data`` and write it atomically to the review's ``scilex.yml``.

    Raises:
        SettingsError: If ``data`` is invalid (nothing is written).
    """
    problems = validate(data)
    if problems:
        raise SettingsError(
            "\n".join(f"{path}: {message}" for path, message in problems)
        )
    target = review.config_path
    previous = target.read_text(encoding="utf-8") if target.is_file() else ""
    try:
        explicit = yaml.safe_load(previous) if previous.strip() else None
    except yaml.YAMLError:
        explicit = None
    body = yaml.safe_dump(
        to_file_dict(data, explicit if isinstance(explicit, dict) else None),
        sort_keys=False,
        allow_unicode=True,
    )
    _atomic_write(target, leading_comments(previous) + body)
    return target


def leading_comments(text: str) -> str:
    """Return the comment block at the top of ``text`` (template header)."""
    header = []
    for line in text.splitlines(keepends=True):
        if not line.lstrip().startswith("#"):
            break
        header.append(line)
    return "".join(header)


# ---------------------------------------------------------------------------
# Raw text editing (repair of a file the form cannot handle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextCheck:
    """Result of checking the raw text of a ``scilex.yml``."""

    problems: list[str]  # readable messages; empty when the text is valid
    unknown_keys: list[tuple[str, str | None]]  # (dotted path, suggestion)

    @property
    def valid(self) -> bool:
        """Whether the text can be saved as is."""
        return not self.problems


def read_text(review: Review) -> str:
    """Return the raw text of the review's ``scilex.yml`` (``""`` if absent)."""
    try:
        return review.config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def check_text(text: str) -> TextCheck:
    """Check ``text`` as a ``scilex.yml``: YAML syntax, then the schema.

    Unknown keys are listed in ``unknown_keys`` with a "did you mean" hint.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        reason = getattr(exc, "problem", None) or str(exc)
        return TextCheck([f"Invalid YAML, {where}{reason}"], [])
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return TextCheck(["The top level of scilex.yml must be a mapping."], [])
    layer = _normalize_file_layer(copy.deepcopy(raw))
    preset = layer.get("preset")
    merged = base_dict(preset if isinstance(preset, str) else None)
    _deep_merge(merged, layer)
    try:
        ScilexSettings.model_validate(merged)
    except ValidationError as exc:
        candidates = known_paths()
        unknown = [
            (dotted, _suggest(dotted, candidates))
            for dotted in (
                ".".join(str(part) for part in error["loc"])
                for error in exc.errors()
                if error["type"] == "extra_forbidden"
            )
        ]
        return TextCheck(format_validation_error(exc, merged).splitlines(), unknown)
    return TextCheck([], [])


def write_text(review: Review, text: str) -> Path:
    """Write ``text`` verbatim and atomically (comments are kept).

    Raises:
        SettingsError: If ``text`` does not pass :func:`check_text`.
    """
    check = check_text(text)
    if not check.valid:
        raise SettingsError("\n".join(check.problems))
    target = review.config_path
    _atomic_write(target, text)
    return target


def _delete_key_lines(text: str, dotted: str) -> str | None:
    """Delete the line of key ``dotted`` and its indented children; None if not found."""
    lines = text.splitlines(keepends=True)
    keys = dotted.split(".")
    depth = 0
    parent_indent = -1
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.strip() or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if depth > 0 and indent <= parent_indent:
            return None  # left the parent block without finding the key
        match = re.match(r"""["']?([^"':\s]+)["']?\s*:""", stripped)
        if not match or match.group(1) != keys[depth]:
            continue
        if depth < len(keys) - 1:
            depth += 1
            parent_indent = indent
            continue
        end = index + 1
        while end < len(lines):
            following = lines[end].lstrip()
            if (
                following.strip()
                and not following.startswith("#")
                and len(lines[end]) - len(following) <= indent
            ):
                break
            end += 1
        # Comments and blank lines just before the next key belong to it.
        while end > index + 1 and (
            not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")
        ):
            end -= 1
        return "".join(lines[:index] + lines[end:])
    return None


def _parses_to_mapping(text: str) -> bool:
    try:
        return isinstance(yaml.safe_load(text), dict)
    except yaml.YAMLError:
        return False


def remove_unknown_keys(review: Review) -> list[str]:
    """Rewrite the file without its unknown keys; return the removed paths.

    The keys are deleted line by line so the comments elsewhere survive; the
    file is dumped from the parsed data only if that edit does not validate.

    Other problems may remain in the written file: the page reloads and shows them.

    Raises:
        SettingsError: If the file is not valid YAML, or has problems but no
            unknown key to remove.
    """
    text = read_text(review)
    check = check_text(text)
    raw = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(raw, dict) or (check.problems and not check.unknown_keys):
        raise SettingsError("\n".join(check.problems))
    removed = [dotted for dotted, _ in check.unknown_keys]
    edited: str | None = text
    for dotted in removed:
        edited = _delete_key_lines(edited, dotted) if edited is not None else None
    if edited is not None and (
        check_text(edited).unknown_keys or not _parses_to_mapping(edited)
    ):
        edited = None
    if edited is None:
        for dotted in removed:
            *parents, last = dotted.split(".")
            node: Any = raw
            for key in parents:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, dict):
                node.pop(last, None)
        edited = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    _atomic_write(review.config_path, edited)
    return removed


# ---------------------------------------------------------------------------
# Form description (drives the generic form)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """How the form edits one field."""

    kind: str  # bool int float str choice multichoice strlist intlist floatmap yaml
    nullable: bool = False
    options: tuple = ()


def _unwrap(annotation: Any) -> tuple[Any, bool]:
    """Strip ``Annotated`` and ``| None``; return ``(core, nullable)``."""
    nullable = False
    while True:
        origin = get_origin(annotation)
        if origin is typing.Annotated:
            annotation = get_args(annotation)[0]
        elif origin in (typing.Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            nullable = nullable or len(args) < len(get_args(annotation))
            if len(args) != 1:
                return annotation, nullable
            annotation = args[0]
        else:
            return annotation, nullable


def describe_field(annotation: Any) -> FieldSpec:
    """Map a pydantic field annotation to a :class:`FieldSpec`."""
    core, nullable = _unwrap(annotation)
    origin = get_origin(core)
    if core is bool:
        return FieldSpec("bool", nullable)
    if core is int:
        return FieldSpec("int", nullable)
    if core is float:
        return FieldSpec("float", nullable)
    if core is str:
        return FieldSpec("str", nullable)
    if origin is Literal:
        return FieldSpec("choice", nullable, get_args(core))
    if origin is list:
        item, _ = _unwrap(get_args(core)[0])
        if get_origin(item) is Literal:
            return FieldSpec("multichoice", nullable, get_args(item))
        if item is int:
            return FieldSpec("intlist", nullable)
        return FieldSpec("strlist", nullable)
    if origin is dict:
        value, _ = _unwrap(get_args(core)[1])
        return FieldSpec("floatmap" if value is float else "yaml", nullable)
    return FieldSpec("yaml", nullable)


def sections() -> list[tuple[str, type[BaseModel]]]:
    """Top-level sub-models of the settings, in file order, except ``search``."""
    result = []
    for name, field in ScilexSettings.model_fields.items():
        core, _ = _unwrap(field.annotation)
        if name != "search" and isinstance(core, type) and issubclass(core, BaseModel):
            result.append((name, core))
    return result


def years_shape(review: Review) -> str | None:
    """Return how ``search.years`` is written in the file: ``"range"``, ``"list"`` or None.

    A ``"YYYY-YYYY"`` string is a range; an explicit YAML list is a list of
    specific years. None when the file has no usable ``years``.
    """
    try:
        raw = _read_file_layer(review.config_path)
    except (SettingsError, OSError):
        return None
    search = raw.get("search")
    years = search.get("years") if isinstance(search, dict) else None
    if isinstance(years, str):
        return "range"
    if isinstance(years, list) and years:
        return "list"
    return None


def years_as_range(years: Any) -> tuple[int, int] | None:
    """Return ``(first, last)`` if ``years`` is a run of consecutive years."""
    if (
        isinstance(years, list)
        and years
        and all(isinstance(y, int) and not isinstance(y, bool) for y in years)
        and sorted(years) == list(range(min(years), max(years) + 1))
    ):
        return min(years), max(years)
    return None


# ---------------------------------------------------------------------------
# Guidance for the form (ADR 0005)
# ---------------------------------------------------------------------------


def estimate_queries(data: dict) -> int:
    """Number of queries a collection would send (rules of ``queryCompositor``).

    Two non-empty keyword groups give one query per pair of terms; otherwise
    one per term of the first group. Each is sent for every year and source.
    """
    search = data.get("search") or {}
    groups = [g for g in (search.get("keywords") or []) if isinstance(g, list)]
    if len(groups) == 2 and groups[0] and groups[1]:
        combinations = len(groups[0]) * len(groups[1])
    elif groups and groups[0]:
        combinations = len(groups[0])
    else:
        combinations = 0
    years = search.get("years")
    year_count = len(years) if isinstance(years, list) else 0
    return combinations * year_count * len(search.get("apis") or [])


def default_value(dotted: str, preset: str | None = None) -> Any:
    """Value of ``dotted`` without the file (defaults, then ``preset``)."""
    node: Any = base_dict(preset)
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def format_default(value: Any) -> str:
    """Short readable form of a default value for the help line."""
    if value is None or value == [] or value == {}:
        return "empty"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key} {item}" for key, item in value.items())
    return str(value)


def _has_key(keys: dict, block: str, field_name: str = "api_key") -> bool:
    from scilex.gui.services.keys_editor import env_overrides, get_keys_list

    if f"{block}.{field_name.lower()}" in env_overrides():
        return True
    entry = keys.get(block)
    return bool(get_keys_list(entry if isinstance(entry, dict) else None, field_name))


def key_status(api: str, keys: dict) -> str:
    """``"ok"``, ``"missing"`` (required key absent) or ``"advised"`` (recommended)."""
    from scilex.gui.services.field_catalog import API_INFO

    info = API_INFO.get(api)
    if info is None or info.key == "none" or not info.key_block:
        return "ok"
    if _has_key(keys, info.key_block):
        return "ok"
    return "missing" if info.key == "required" else "advised"


def _placeholder_terms() -> set[str]:
    """Example keywords of the blank template, lower-cased."""
    from scilex.init_templates import skeleton_text

    skeleton = yaml.safe_load(skeleton_text("x")) or {}
    return {
        str(term).lower()
        for group in skeleton.get("search", {}).get("keywords", [])
        for term in group
    }


def dependency_warnings(data: dict, keys: dict) -> list[tuple[str, str]]:
    """Settings that will not work as the user expects: ``(path, message)``."""
    from scilex.gui.services.field_catalog import API_INFO

    warnings: list[tuple[str, str]] = []
    for api in data.get("search", {}).get("apis") or []:
        if key_status(api, keys) == "missing":
            warnings.append(
                (
                    "search.apis",
                    f"{API_INFO[api].label} needs an API key: add it on the API "
                    "keys page or untick it, otherwise it returns nothing.",
                )
            )
    citations_fetched = data.get("citations", {}).get("fetch", True)
    if not citations_fetched and data.get("filters", {}).get("citations"):
        warnings.append(
            (
                "filters.citations",
                "The citation threshold has no effect while 'Fetch citation "
                "counts' is off.",
            )
        )
    if data.get("enrichment", {}).get("unpaywall") and not _has_key(
        keys, "Unpaywall", "email"
    ):
        warnings.append(
            (
                "enrichment.unpaywall",
                "Unpaywall needs an email address on the API keys page.",
            )
        )
    if data.get("llm_screening", {}).get("enabled") and not _has_key(
        keys, "openrouter"
    ):
        warnings.append(
            (
                "llm_screening.enabled",
                "LLM screening needs an OpenRouter key on the API keys page.",
            )
        )
    search = data.get("search", {})
    placeholders = _placeholder_terms()
    examples = [
        str(term)
        for group in search.get("keywords") or []
        for term in group or []
        if str(term).lower() in placeholders
    ]
    if examples:
        warnings.append(
            (
                "search.keywords",
                "Keywords still look like the template's examples ("
                + ", ".join(examples)
                + "): replace them with your own terms.",
            )
        )
    max_per_query = search.get("max_articles_per_query")
    if isinstance(max_per_query, int) and max_per_query <= 0:
        warnings.append(
            (
                "search.max_articles_per_query",
                "0 or less means no limit: leave the field empty instead.",
            )
        )
    years = _expand_years(search.get("years"))
    early = (
        [y for y in years if isinstance(y, int) and y < 1900]
        if isinstance(years, list)
        else []
    )
    if early:
        warnings.append(
            (
                "search.years",
                f"Year {min(early)} is before 1900: the APIs index almost nothing "
                "that old; check the years.",
            )
        )
    if estimate_queries(data) > 2000:
        warnings.append(
            (
                "search.keywords",
                "Over 2000 queries: the collection may take hours. Use fewer "
                "terms, years or sources, or set a max per query.",
            )
        )
    return warnings


_MESSAGE_REWRITES: tuple[tuple[str, str], ...] = (
    ("Input should be a valid integer", "must be a whole number"),
    ("Input should be a valid number", "must be a number"),
    ("Input should be greater than or equal to", "must be at least"),
    ("Input should be less than or equal to", "must be at most"),
    ("Input should be greater than", "must be more than"),
    ("String should have at least 1 character", "must not be empty"),
    ("Input should be a valid list", "must be a list"),
    ("Input should be a valid dictionary", "must be a mapping"),
    ("Input should be a valid string", "must be text"),
    ("year range start is after its end", "'From' is after 'To'"),
)


def readable_problem(path: str, message: str) -> str:
    """``"<Field label>: <plain message>"`` for the summary under the form."""
    from scilex.gui.services.field_catalog import label_of

    known = set(known_paths())
    parts = path.split(".")
    # A list item ("search.years.0") or a sub-key: name the field it belongs to.
    while len(parts) > 1 and ".".join(parts) not in known:
        parts.pop()
    for raw, plain in _MESSAGE_REWRITES:
        if message.startswith(raw):
            message = plain + message[len(raw) :]
            break
    return f"{label_of('.'.join(parts))}: {message}"
