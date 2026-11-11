"""Shared helpers for the per-API ``*toZoteroFormat`` converters.

The converters turn heterogeneous raw API payloads into one flat record whose
keys (and key order) are the column order of the aggregated CSV. These helpers
centralise the boilerplate that used to be copy-pasted in every converter:
building the empty record, reading a field defensively, walking nested
payloads and joining author lists.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from scilex.constants import MISSING_VALUE, is_valid

ZOTERO_FIELDS: tuple[str, ...] = (
    "title",
    "publisher",
    "itemType",
    "authors",
    "language",
    "abstract",
    "archiveID",
    "archive",
    "date",
    "DOI",
    "url",
    "rights",
    "pages",
    "journalAbbreviation",
    "volume",
    "serie",
    "issue",
    "pdf_url",
)
"""Base columns of a converted record, in CSV column order."""

AUTHOR_SEPARATOR = ";"

_CONTAINER_TYPES = (list, tuple, set, frozenset, dict)


def new_record(
    archive: str,
    *,
    item_type: str = MISSING_VALUE,
    extra_keys: Iterable[str] = (),
) -> dict[str, Any]:
    """Build an empty Zotero-style record.

    Args:
        archive: Name of the source API, stored in the ``archive`` field.
        item_type: Initial ``itemType`` (defaults to ``MISSING_VALUE``).
        extra_keys: Additional keys appended after the base fields and
            initialised to ``MISSING_VALUE`` (e.g. ``("tags",)``).

    Returns:
        A dict with every base field set to ``MISSING_VALUE``.
    """
    record = dict.fromkeys(ZOTERO_FIELDS, MISSING_VALUE)
    record.update(dict.fromkeys(extra_keys, MISSING_VALUE))
    record["archive"] = archive
    record["itemType"] = item_type
    return record


def fill_record(record: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Set the given fields on ``record``, skipping values that are ``None``.

    Pair it with ``get_valid`` / ``dig`` so that absent data leaves the
    ``MISSING_VALUE`` default untouched.
    """
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    return record


def get_valid(row: Any, key: str) -> Any:
    """Return ``row[key]`` if it holds real data, else ``None``.

    Missing keys, ``None``, ``""``, NaN, ``"NA"`` and empty containers all give
    ``None``. Zero is real data and is returned. Non-dict ``row`` gives ``None``.
    """
    if not isinstance(row, Mapping):
        return None
    return valid_or_none(row.get(key))


def valid_or_none(value: Any) -> Any:
    if isinstance(value, _CONTAINER_TYPES):
        return value if len(value) > 0 else None
    try:
        return value if is_valid(value) else None
    except (TypeError, ValueError):
        # Array-likes make pd.isna ambiguous; treat non-empty ones as data.
        return value if getattr(value, "size", 1) else None


def first_valid(row: Any, *keys: str) -> Any:
    """Return the first ``get_valid(row, key)`` that is not ``None`` (else ``None``)."""
    for key in keys:
        value = get_valid(row, key)
        if value is not None:
            return value
    return None


def dig(obj: Any, *path: str | int, default: Any = None) -> Any:
    """Walk a nested payload without ever raising.

    Each path element is a dict key or a list index. Any missing key, bad
    index, wrong container type or final ``None`` yields ``default``.
    """
    current = obj
    for step in path:
        if isinstance(current, Mapping):
            current = current.get(step)
        elif (
            isinstance(current, Sequence)
            and not isinstance(current, str)
            and isinstance(step, int)
            and -len(current) <= step < len(current)
        ):
            current = current[step]
        else:
            return default
    return default if current is None else current


def first_of(value: Any) -> Any:
    """Return the first element of a list/tuple (``None`` if empty), else ``value``."""
    if isinstance(value, list | tuple):
        return value[0] if value else None
    return value


def join_values(values: Any) -> str:
    """Join the valid entries of ``values`` with ``;`` (``MISSING_VALUE`` if none).

    A bare string is treated as a single entry.
    """
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable) or isinstance(values, Mapping):
        return MISSING_VALUE
    kept = [str(value) for value in values if valid_or_none(value) is not None]
    return AUTHOR_SEPARATOR.join(kept) if kept else MISSING_VALUE


def join_authors(names: Any) -> str:
    """Join author names with ``;`` or return ``MISSING_VALUE`` when there are none."""
    return join_values(names)


def page_range(first: Any, last: Any) -> str:
    """Format ``first-last``, or ``MISSING_VALUE`` unless both ends are valid."""
    if valid_or_none(first) is None or valid_or_none(last) is None:
        return MISSING_VALUE
    return f"{first}-{last}"


def map_item_type(value: Any, mapping: Mapping[str, str], default: str) -> str:
    """Look ``value`` up in ``mapping``; unknown, missing or unhashable gives ``default``."""
    try:
        return mapping.get(value, default)
    except TypeError:
        return default


def item_type_from_text(
    value: Any, patterns: Sequence[tuple[str, str]], default: str
) -> str:
    """Return the item type of the first pattern contained in ``value``.

    ``value`` may be a string (substring test) or a list (membership test).
    Patterns are tried in order.
    """
    if not isinstance(value, str | list | tuple):
        return default
    for pattern, item_type in patterns:
        if pattern in value:
            return item_type
    return default
