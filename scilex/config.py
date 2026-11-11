"""Centralized configuration service for SciLEx.

Provides a single entry point for loading, merging, and saving configuration.
Replaces the scattered config loading pattern (load_all_configs + advanced merge)
that was duplicated across run_collection.py, aggregate_collect.py,
push_to_zotero.py, export_to_bibtex.py, and enrich_with_hf.py.

Usage:
    # From CLI entry points (reads YAML files):
    config = SciLExConfig.from_files()

    # From web API (pass dicts directly, no file I/O):
    config = SciLExConfig.from_dicts(main_config, api_config)

    # Access config values:
    config.main["keywords"]
    config.api["SemanticScholar"]["api_key"]
    config.quality_filters["require_abstract"]
"""

import copy
import logging
import os
from pathlib import Path

import yaml

from scilex.config_defaults import DEFAULT_OUTPUT_DIR, get_default_quality_filters
from scilex.settings.advanced import merge_advanced_config
from scilex.settings.resolve import resolve_legacy_configs

logger = logging.getLogger(__name__)

# Package directory where config files live (scilex/)
_PACKAGE_DIR = Path(__file__).parent


class SciLExConfig:
    """Unified configuration container for SciLEx.

    Holds main config, API config, and merged quality filters.
    Constructed via from_files() or from_dicts() class methods.
    """

    def __init__(self, main_config: dict, api_config: dict):
        self.main = main_config
        self.api = api_config

    @property
    def quality_filters(self) -> dict:
        """Quality filters with defaults applied for any unspecified keys."""
        merged = get_default_quality_filters()
        merged.update(self.main.get("quality_filters", {}))
        return merged

    @classmethod
    def from_files(
        cls,
        config_dir: Path | None = None,
        config_path: str | Path | None = None,
        keys_path: str | Path | None = None,
    ) -> "SciLExConfig":
        """Load configuration from files on disk.

        Without arguments the files are discovered by
        :func:`scilex.settings.resolve.resolve_legacy_configs` (``scilex.yml``
        first, legacy files as a fallback).

        Args:
            config_dir: Force the legacy format: read ``scilex.config.yml``,
                ``api.config.yml`` and the optional ``scilex.advanced.yml``
                from this directory.
            config_path: Explicit ``scilex.yml`` (``--config``).
            keys_path: Explicit ``keys.yml`` (``--keys``).

        Returns:
            SciLExConfig with all configs loaded and merged.
        """
        if config_dir is None:
            return cls(*resolve_legacy_configs(config_path, keys_path))

        config_dir = Path(config_dir)
        main_config = _load_yaml(config_dir / "scilex.config.yml")
        api_config = _load_yaml(config_dir / "api.config.yml")
        advanced_path = config_dir / "scilex.advanced.yml"
        if advanced_path.is_file():
            merge_advanced_config(main_config, _load_yaml(advanced_path) or {})
            logger.info("Loaded advanced config from %s", advanced_path)
        return cls(main_config, api_config)

    @classmethod
    def from_collection(
        cls,
        collection: str | None,
        config_dir: Path | None = None,
        use_current_config: bool = False,
    ) -> "SciLExConfig":
        """Load configuration for an existing collection.

        If ``collection`` is None this is equivalent to ``from_files()``.
        Otherwise the main config is loaded from the ``config_used.yml``
        snapshot saved inside that collection directory. ``collection`` may be
        a plain collection name (looked up under ``output_dir`` of the current
        ``scilex.config.yml``) or a full path to the collection directory.
        The API config always comes from ``api.config.yml`` (empty if absent).

        Args:
            collection: Collection name, full path, or None.
            config_dir: Directory containing config files (default: scilex/).
            use_current_config: Replay mode. Keep the current configuration
                (filters, ranking, keywords...) and only point it at the
                collection's directory, instead of loading the collection's
                ``config_used.yml`` snapshot. Aggregation still reads the
                snapshot for the query-to-keywords mapping.

        Returns:
            SciLExConfig for the requested collection.

        Raises:
            FileNotFoundError: If the collection has no saved config_used.yml.
        """
        if collection is None:
            return cls.from_files(config_dir)

        discovered = None
        if config_dir is None:
            try:
                discovered = resolve_legacy_configs()
            except FileNotFoundError:
                discovered = None
        config_dir = Path(config_dir) if config_dir else _PACKAGE_DIR

        if os.path.isabs(collection) or os.sep in collection or "/" in collection:
            collect_dir = collection
        else:
            try:
                current_main = (
                    discovered[0]
                    if discovered
                    else _load_yaml(config_dir / "scilex.config.yml")
                )
                output_dir = current_main.get("output_dir", DEFAULT_OUTPUT_DIR)
            except FileNotFoundError:
                output_dir = DEFAULT_OUTPUT_DIR
            collect_dir = os.path.join(output_dir, collection)

        config_path = Path(collect_dir) / "config_used.yml"
        if use_current_config:
            if not config_path.is_file():
                raise FileNotFoundError(
                    f"Cannot find saved config at {config_path}. Make sure the "
                    "collection name or path is correct and the collection has "
                    "been started at least once."
                )
            current = cls.from_files(config_dir if config_dir != _PACKAGE_DIR else None)
            collect_path = Path(collect_dir)
            current.main["output_dir"] = str(collect_path.parent)
            current.main["collect_name"] = collect_path.name
            return current
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Cannot find saved config at {config_path}. Make sure the "
                "collection name or path is correct and the collection has "
                "been started at least once."
            )
        # The snapshot is complete (advanced options were merged when it was
        # written): merging scilex.advanced.yml again would alter the original run.
        main_config = _load_yaml(config_path)

        try:
            api_config = (
                discovered[1]
                if discovered
                else _load_yaml(config_dir / "api.config.yml")
            )
        except FileNotFoundError:
            api_config = {}

        logger.info("Loaded config for collection from %s", config_path)
        return cls(main_config, api_config)

    @classmethod
    def from_dicts(
        cls, main_config: dict, api_config: dict | None = None
    ) -> "SciLExConfig":
        """Create config from in-memory dictionaries.

        Used by the web API to avoid file I/O. Deep-copies inputs
        to prevent mutation of the caller's data.

        Args:
            main_config: Main configuration dictionary.
            api_config: API configuration dictionary (default: empty).

        Returns:
            SciLExConfig wrapping the provided dicts.
        """
        return cls(
            copy.deepcopy(main_config),
            copy.deepcopy(api_config or {}),
        )

    def save_main_config(self, path: Path | None = None) -> None:
        """Save main configuration to YAML file.

        Args:
            path: Target file path. Defaults to scilex/scilex.config.yml.
        """
        if path is None:
            path = _PACKAGE_DIR / "scilex.config.yml"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.main, f, default_flow_style=False)

    def save_api_config(self, path: Path | None = None) -> None:
        """Save API configuration to YAML file.

        Args:
            path: Target file path. Defaults to scilex/api.config.yml.
        """
        if path is None:
            path = _PACKAGE_DIR / "api.config.yml"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.api, f, default_flow_style=False)


def _load_yaml(file_path: Path) -> dict:
    """Load a YAML file, raising FileNotFoundError if missing.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    with open(file_path) as f:
        return yaml.safe_load(f) or {}


# Backward-compatible alias (tests and external code import the old name).
_merge_advanced_config = merge_advanced_config
