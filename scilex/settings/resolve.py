"""Single resolution point turning any configuration source into legacy dicts.

Order for the main configuration: ``--config`` > ``$SCILEX_CONFIG`` >
``./scilex.yml`` > legacy ``scilex/scilex.config.yml`` (with a warning). A
legacy-format file given explicitly (it contains ``collect_name``) is accepted
with the same warning. Keys follow ``find_keys_file`` and the
``SCILEX_<API>_<FIELD>`` environment overrides.
"""

import logging
import os
from pathlib import Path

from scilex.settings.advanced import merge_advanced_config
from scilex.settings.loader import (
    USER_KEYS_PATH,
    _load_keys,
    _read_yaml,
    find_config_file,
    find_keys_file,
    keys_to_legacy,
    load_settings,
    to_legacy,
)
from scilex.settings.schema import ConfigFileNotFoundError

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
LEGACY_MAIN_NAME = "scilex.config.yml"
LEGACY_ADVANCED_NAME = "scilex.advanced.yml"


def is_legacy_format(data: dict) -> bool:
    """Tell whether a parsed config uses the legacy format (``collect_name``)."""
    return "collect_name" in data


def read_legacy_main(main_path: Path, advanced_path: Path | None = None) -> dict:
    """Read a legacy main file and merge the optional advanced file into it.

    Args:
        main_path: Legacy ``scilex.config.yml``.
        advanced_path: Legacy ``scilex.advanced.yml`` (ignored when missing).

    Returns:
        The merged legacy ``main_config`` dictionary.
    """
    main_config = _read_yaml(main_path)
    if advanced_path is not None and advanced_path.is_file():
        merge_advanced_config(main_config, _read_yaml(advanced_path))
        logger.info("Loaded advanced config from %s", advanced_path)
    return main_config


def _warn_legacy(path: Path) -> None:
    logger.warning(
        "Using the legacy configuration format (%s). Convert it with "
        "`scilex config migrate --write` to get a scilex.yml.",
        path,
    )


def resolve_main_config(config_path: str | Path | None = None) -> dict:
    """Resolve only the main configuration (no keys), see module docstring."""
    return _resolve(config_path, None)[0]


def _resolve(
    config_path: str | Path | None, keys_path: str | Path | None
) -> tuple[dict, dict]:
    found = find_config_file(config_path)
    if found is not None and not is_legacy_format(_read_yaml(found)):
        loaded = load_settings(found, keys_path)
        return to_legacy(loaded.settings, loaded.keys)

    if found is None:
        found = PACKAGE_DIR / LEGACY_MAIN_NAME
        if not found.is_file():
            raise ConfigFileNotFoundError(
                "No scilex.yml found (use --config, $SCILEX_CONFIG or create "
                f"./scilex.yml) and no legacy file at {found}"
            )
    _warn_legacy(found)
    main_config = read_legacy_main(found, found.parent / LEGACY_ADVANCED_NAME)
    keys = _load_keys(find_keys_file(keys_path), {})
    return main_config, keys_to_legacy(keys)


def resolve_legacy_configs(
    config_path: str | Path | None = None, keys_path: str | Path | None = None
) -> tuple[dict, dict]:
    """Return ``(main_config, api_config)`` legacy dictionaries.

    Args:
        config_path: Explicit config file (``--config``).
        keys_path: Explicit keys file (``--keys``).

    Returns:
        The legacy dictionaries consumed by the pipeline.

    Raises:
        FileNotFoundError: If an explicit file is missing or nothing is found.
        SettingsError: If a ``scilex.yml`` or ``keys.yml`` is invalid.
    """
    return _resolve(config_path, keys_path)


def keys_file_for_editing(fallback: Path) -> Path:
    """Path of the keys file a UI should read and write, without any warning.

    ``$SCILEX_KEYS`` > ``~/.config/scilex/keys.yml`` (when it exists) > ``fallback``
    (the legacy ``api.config.yml``, when it exists). With no keys file at all, a
    new one is created at ``~/.config/scilex/keys.yml``, never in the package.
    """
    explicit = os.environ.get("SCILEX_KEYS")
    if explicit:
        return Path(explicit).expanduser()
    user_path = USER_KEYS_PATH.expanduser()
    if user_path.is_file() or not fallback.is_file():
        return user_path
    return fallback
