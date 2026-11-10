"""Read, validate, save and test the global ``keys.yml`` (no UI code)."""

import contextlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from scilex.gui.services.config_editor import leading_comments
from scilex.settings.loader import (
    KEY_BLOCK_NAMES,
    RESERVED_ENV_VARIABLES,
    USER_KEYS_PATH,
)
from scilex.settings.schema import KeysSettings

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class ApiSpec:
    """What the keys screen needs to know about one API block."""

    name: str
    label: str
    field: str = "api_key"
    required: bool = False
    help_url: str = ""
    note: str = ""
    testable: bool = False


API_SPECS: tuple[ApiSpec, ...] = (
    ApiSpec(
        "SemanticScholar",
        "Semantic Scholar",
        help_url="https://www.semanticscholar.org/product/api#api-key-form",
        note="Optional but strongly recommended (higher rate limit).",
        testable=True,
    ),
    ApiSpec(
        "OpenAlex",
        "OpenAlex",
        help_url="https://openalex.org/settings/api",
        note="Optional, free.",
        testable=True,
    ),
    ApiSpec(
        "IEEE",
        "IEEE Xplore",
        required=True,
        help_url="https://developer.ieee.org/",
        note="Required to collect from IEEE.",
        testable=True,
    ),
    ApiSpec(
        "Elsevier",
        "Elsevier (Scopus)",
        required=True,
        help_url="https://dev.elsevier.com/apikey/manage",
        note="Required to collect from Elsevier.",
        testable=True,
    ),
    ApiSpec(
        "Springer",
        "Springer Nature",
        required=True,
        help_url="https://dev.springernature.com/",
        note="Required to collect from Springer.",
        testable=True,
    ),
    ApiSpec(
        "PubMed",
        "PubMed (NCBI)",
        help_url="https://www.ncbi.nlm.nih.gov/account/settings/",
        note="Optional: 10 requests/s instead of 3.",
        testable=True,
    ),
    ApiSpec(
        "openrouter",
        "OpenRouter (LLM screening)",
        help_url="https://openrouter.ai/keys",
        note="Optional, only for LLM screening.",
        testable=True,
    ),
)
ZOTERO_HELP_URL = "https://www.zotero.org/settings/keys"
EMAIL_BLOCKS = {
    "Unpaywall": ("email", "required by the Unpaywall enrichment"),
    "CrossRef": ("mailto", "optional, polite pool"),
}


def keys_path() -> Path:
    """Return the keys file to edit: ``$SCILEX_KEYS``, else the user default.

    The legacy ``scilex/api.config.yml`` is never written to.
    """
    explicit = os.environ.get("SCILEX_KEYS")
    if explicit:
        return Path(explicit).expanduser()
    return USER_KEYS_PATH.expanduser()


def load_keys(path: Path | None = None) -> dict:
    """Load a keys file (the global one by default) as a dict ({} if absent)."""
    path = keys_path() if path is None else Path(path)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def validate(data: dict) -> None:
    """Raise ``ValueError`` if ``data`` is not a valid keys mapping."""
    KeysSettings.model_validate(data)


def _backup_previous(path: Path) -> None:
    """Copy the current keys file to ``keys.yml.bak`` (mode 0600)."""
    backup = path.with_name(path.name + ".bak")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(path.read_bytes())
    os.chmod(backup, 0o600)


def save_keys(data: dict, path: Path | None = None) -> Path:
    """Validate then write ``data`` atomically with mode 0600.

    Callers pass the full dict they loaded (``load_keys``) with their edits,
    so blocks this module does not know about are preserved.

    Args:
        data: Keys mapping.
        path: File to write (the global keys file by default).
    """
    validate(data)
    path = keys_path() if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if path.is_file():
        # Keep the header comments of the user's file (yaml drops comments).
        text = leading_comments(path.read_text(encoding="utf-8")) + text
        _backup_previous(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".keys-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return path


def get_keys_list(block: dict | None, field_name: str = "api_key") -> list[str]:
    """Return the keys of a block as a list (string, list, or Springer mapping)."""
    value = (block or {}).get(field_name)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item]
    return [str(value)]


def set_keys_list(
    data: dict, api: str, keys: list[str], field_name: str = "api_key"
) -> None:
    """Store ``keys`` in ``data[api][field_name]``: a string, a list, or removed."""
    keys = [key.strip() for key in keys if key and key.strip()]
    block = dict(data.get(api) or {})
    if keys == get_keys_list(block, field_name):
        return  # unchanged: keep the original shape (e.g. Springer's meta/openaccess mapping)
    if not keys:
        block.pop(field_name, None)
    else:
        block[field_name] = keys[0] if len(keys) == 1 else keys
    if block:
        data[api] = block
    else:
        data.pop(api, None)


def env_overrides() -> dict[str, str]:
    """Map ``"<Api>.<field>"`` to the env variable currently overriding it."""
    api_by_upper = {name.upper(): name for name in KEY_BLOCK_NAMES}
    found = {}
    for variable in os.environ:
        if not variable.startswith("SCILEX_") or variable in RESERVED_ENV_VARIABLES:
            continue
        api_part, _, field_part = variable[len("SCILEX_") :].partition("_")
        api = api_by_upper.get(api_part.upper())
        if api and field_part:
            found[f"{api}.{field_part.lower()}"] = variable
    return found


@dataclass
class _Request:
    url: str
    headers: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


def _build_request(api: str, key: str) -> _Request | None:
    """Return the minimal authenticated request for ``api`` (None if untestable)."""
    if api == "SemanticScholar":
        return _Request(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"x-api-key": key},
            {"query": "test", "limit": 1},
        )
    if api == "OpenAlex":
        return _Request(
            "https://api.openalex.org/works", params={"api_key": key, "per-page": 1}
        )
    if api == "IEEE":
        return _Request(
            "https://ieeexploreapi.ieee.org/api/v1/search/articles",
            params={"apikey": key, "querytext": "test", "max_records": 1},
        )
    if api == "Elsevier":
        return _Request(
            "https://api.elsevier.com/content/search/scopus",
            {"X-ELS-APIKey": key, "Accept": "application/json"},
            {"query": "TITLE(test)", "count": 1},
        )
    if api == "Springer":
        return _Request(
            "https://api.springernature.com/meta/v2/json",
            params={"q": "test", "api_key": key, "p": 1},
        )
    if api == "PubMed":
        return _Request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": "test", "retmax": 1, "api_key": key},
        )
    if api == "openrouter":
        return _Request(
            "https://openrouter.ai/api/v1/auth/key",
            {"Authorization": f"Bearer {key}"},
        )
    return None


def _get(url: str, headers: dict, params: dict) -> tuple[bool, str]:
    try:
        response = requests.get(
            url, headers=headers, params=params, timeout=CHECK_TIMEOUT_SECONDS
        )
    except requests.Timeout:
        return False, "Timeout: the service did not answer in time."
    except requests.RequestException as exc:
        return False, f"Network error ({type(exc).__name__})."
    return _interpret_status(response.status_code)


def check_key(api: str, key: str) -> tuple[bool, str]:
    """Make one minimal HTTP request to see whether ``key`` is accepted.

    Never logs or returns the key.

    Returns:
        ``(ok, message)``.
    """
    key = (key or "").strip()
    if not key:
        return False, "Enter a key first."
    request = _build_request(api, key)
    if request is None:
        return False, "This API cannot be tested automatically."
    return _get(request.url, request.headers, request.params)


def check_zotero(api_key: str, user_id: str, user_mode: str) -> tuple[bool, str]:
    """Check the Zotero credentials with one ``items?limit=1`` request."""
    if not (api_key and user_id):
        return False, "Enter the API key and the library id first."
    scope = "groups" if user_mode == "group" else "users"
    return _get(
        f"https://api.zotero.org/{scope}/{user_id.strip()}/items",
        {"Zotero-API-Key": api_key.strip()},
        {"limit": 1},
    )


def _interpret_status(status: int) -> tuple[bool, str]:
    if 200 <= status < 300:
        return True, "Key accepted."
    if status in (401, 403):
        return False, f"Key rejected (HTTP {status})."
    if status == 429:
        return True, "Key accepted, but the service is rate limiting (HTTP 429)."
    return False, f"Unexpected answer (HTTP {status})."


# ---------------------------------------------------------------------------
# Keys of one review: global keys, overridden field by field
# ---------------------------------------------------------------------------

REVIEW_KEYS_FILENAME = "review_keys.yml"
# Blocks of the legacy api.config.yml that are not API keys.
NON_KEY_BLOCKS = frozenset({"vpn"})


def review_keys_path(folder: Path) -> Path:
    """Return the file holding a review's own keys (overrides of the global ones)."""
    return Path(folder) / REVIEW_KEYS_FILENAME


def merge_keys(base: dict, override: dict) -> dict:
    """Return ``base`` with each field of ``override`` replacing the same field.

    Blocks merge field by field, so a review can change only its Zotero
    library id and keep the global Zotero key.
    """
    merged = {
        name: dict(block) if isinstance(block, dict) else block
        for name, block in base.items()
    }
    for name, block in (override or {}).items():
        if isinstance(block, dict) and isinstance(merged.get(name), dict):
            merged[name] = {**merged[name], **block}
        else:
            merged[name] = block
    return merged


def effective_keys(folder: Path | None) -> dict:
    """Return the keys a review uses: global keys plus its own overrides."""
    global_keys = load_keys()
    if folder is None:
        return global_keys
    return merge_keys(global_keys, load_keys(review_keys_path(folder)))


def save_review_keys(folder: Path, data: dict) -> Path | None:
    """Write a review's overrides; remove the file when there is none.

    Returns:
        The file written, or None when the review now uses the global keys only.
    """
    path = review_keys_path(folder)
    cleaned = {name: block for name, block in data.items() if block}
    if not cleaned:
        path.unlink(missing_ok=True)
        return None
    return save_keys(cleaned, path)


def legacy_keys_path() -> Path:
    """Return the legacy ``scilex/api.config.yml`` of this installation."""
    from scilex.settings.loader import LEGACY_KEYS_PATH

    return LEGACY_KEYS_PATH


def legacy_blocks_to_import(global_keys: dict) -> dict:
    """Return the key blocks of the legacy file that the global file lacks.

    Never raises: an unreadable legacy file just offers nothing.
    """
    path = legacy_keys_path()
    try:
        legacy = load_keys(path) if path.is_file() else {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    missing = {}
    for name, block in legacy.items():
        if name in NON_KEY_BLOCKS or not block:
            continue
        if name == "rate_limits":
            new = {
                k: v for k, v in block.items() if k not in (global_keys.get(name) or {})
            }
            if new:
                missing[name] = new
        elif isinstance(block, dict):
            new = {
                k: v
                for k, v in block.items()
                if v not in (None, "") and k not in (global_keys.get(name) or {})
            }
            if new:
                missing[name] = new
    return missing
