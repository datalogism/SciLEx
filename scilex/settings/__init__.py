"""Simplified configuration system (see docs/decisions/0003)."""

from scilex.settings.loader import (
    LoadedSettings,
    find_config_file,
    find_keys_file,
    load_settings,
    to_legacy,
)
from scilex.settings.migrate import legacy_to_settings, migrate_files
from scilex.settings.presets import PRESETS
from scilex.settings.schema import (
    KeysSettings,
    ScilexSettings,
    SettingsError,
    format_validation_error,
)

__all__ = [
    "PRESETS",
    "KeysSettings",
    "LoadedSettings",
    "ScilexSettings",
    "SettingsError",
    "find_config_file",
    "find_keys_file",
    "format_validation_error",
    "legacy_to_settings",
    "load_settings",
    "migrate_files",
    "to_legacy",
]
