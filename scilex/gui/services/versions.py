"""Saved versions of a review's configuration and eligibility criteria (SX-7, SX-8).

The journal (``workflow.jsonl``) identifies the ``scilex.yml`` and ``criteria.yml``
in force by their SHA-256 only. Each save also writes the version itself, so a
knowledge-graph dump (and a restore) can say *which* configuration a collect ran
with and *which* criteria discarded a paper:

- ``config_history/<sha256>.yml``: the **effective** configuration (defaults,
  preset and file merged, as ``scilex config show`` prints it), one row per
  value with ``default: true`` when the user did not set it. Never ``keys.yml``,
  and no key, token, e-mail address, VPN setting or local path.
- ``criteria_history/<sha256>.yml``: the criteria as saved.

``sha256`` is the hash of the saved file's text, the one the journal records.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG = "config"
CRITERIA = "criteria"
HISTORY_DIRS = {CONFIG: "config_history", CRITERIA: "criteria_history"}
SOURCE_FILES = {CONFIG: "scilex.yml", CRITERIA: "criteria.yml"}
# Values never kept, at any disclosure level (ORSD SR18, CFG7).
WITHHELD = re.compile(
    r"(api_?key|token|password|secret|e?mail|vpn|proxy|output_dir|path)", re.I
)


def sha256_text(text: str) -> str:
    """SHA-256 of a file's text, as the journal records it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def history_dir(folder: Path, kind: str) -> Path:
    """Folder of the saved versions of ``kind`` (``config`` or ``criteria``)."""
    return Path(folder) / HISTORY_DIRS[kind]


def _flatten(value, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{path}.{key}" if path else str(key))
    else:
        yield path, value


def effective_config(config_path: Path) -> list[dict]:
    """The effective configuration of a ``scilex.yml``: ``[{path, value, default}]``.

    Secrets and local paths are left out. An unreadable file gives ``[]``.
    """
    from scilex.settings.loader import load_settings

    try:
        loaded = load_settings(config_path=config_path)
    except Exception:  # invalid file, missing keys file...: no version, no failure
        logger.warning("Cannot read %s for its version", config_path, exc_info=True)
        return []
    rows = []
    for dotted, value in _flatten(loaded.settings.model_dump(mode="json")):
        if WITHHELD.search(dotted):
            continue
        rows.append(
            {
                "path": dotted,
                "value": value,
                "default": loaded.provenance.get(dotted, "default") == "default",
            }
        )
    return rows


def _write_version(folder: Path, kind: str, sha: str, body: dict) -> Path:
    target = history_dir(folder, kind) / f"{sha}.yml"
    if target.is_file():
        return target  # same content saved again: the first date stays
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return target


def record_config(folder: Path, text: str) -> str | None:
    """Save the version of the review's ``scilex.yml`` just written; return its hash.

    Never raises: a failed version must not make the save fail.
    """
    sha = sha256_text(text)
    try:
        values = effective_config(Path(folder) / SOURCE_FILES[CONFIG])
        _write_version(
            folder,
            CONFIG,
            sha,
            {
                "sha256": sha,
                "at": datetime.now().isoformat(timespec="seconds"),
                "file": SOURCE_FILES[CONFIG],
                "values": values,
            },
        )
    except OSError:
        logger.warning("Cannot save the configuration version", exc_info=True)
        return None
    return sha


def record_criteria(folder: Path, text: str, criteria: list[dict]) -> str | None:
    """Save the version of ``criteria.yml`` just written; return its hash."""
    sha = sha256_text(text)
    try:
        _write_version(
            folder,
            CRITERIA,
            sha,
            {
                "sha256": sha,
                "at": datetime.now().isoformat(timespec="seconds"),
                "file": SOURCE_FILES[CRITERIA],
                "criteria": criteria,
            },
        )
    except OSError:
        logger.warning("Cannot save the criteria version", exc_info=True)
        return None
    return sha


def current_hash(folder: Path, kind: str) -> str | None:
    """Hash of the file in force (None when there is none)."""
    path = Path(folder) / SOURCE_FILES[kind]
    try:
        return sha256_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def ensure_current(folder: Path, kind: str) -> str | None:
    """Save the file in force as a version if it is not one yet (files saved by
    hand or before versions were kept); return its hash."""
    path = Path(folder) / SOURCE_FILES[kind]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    sha = sha256_text(text)
    if (history_dir(folder, kind) / f"{sha}.yml").is_file():
        return sha
    if kind == CONFIG:
        return record_config(folder, text)
    try:
        criteria = yaml.safe_load(text) or []
    except yaml.YAMLError:
        criteria = []
    return record_criteria(folder, text, criteria if isinstance(criteria, list) else [])


def load_versions(folder: Path, kind: str) -> list[dict]:
    """Every saved version of ``kind``, oldest first."""
    versions = []
    for path in history_dir(folder, kind).glob("*.yml"):
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            logger.warning("Cannot read %s", path)
            continue
        if isinstance(body, dict) and body.get("sha256"):
            versions.append(body)
    return sorted(versions, key=lambda v: (str(v.get("at", "")), v["sha256"]))
