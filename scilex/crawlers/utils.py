import os
import re

import yaml

# Query/form parameters whose value must never reach a log line.
_SECRET_PARAM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"((?:api[_-]?key|access[_-]?token|inst[_-]?token|token|key)=)"
    r"[^&\s\"'<>]+",
    re.IGNORECASE,
)


def sanitize_secrets(text):
    """Mask API keys and tokens (``apikey=``, ``api_key=``, ``token=``...) in text.

    Works on URLs as well as on free-form error messages that embed a URL.

    Args:
        text: String that may contain credentials (non-strings are stringified).

    Returns:
        str: The text with credential values replaced by ``***REDACTED***``.
    """
    return _SECRET_PARAM_PATTERN.sub(r"\1***REDACTED***", str(text))


def load_yaml_config(file_path):
    """
    Load a YAML configuration file.

    Args:
        file_path (str): Path to the YAML file.

    Returns:
        dict: Parsed YAML content as a dictionary.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(file_path) as ymlfile:
        return yaml.safe_load(ymlfile)


def load_all_configs(config_files):
    """
    Load configurations by name.

    ``main_config`` and ``api_config`` are resolved through
    :func:`scilex.settings.resolve.resolve_legacy_configs` (``scilex.yml`` /
    ``keys.yml`` first, legacy files as a fallback); the ``config_files`` paths
    given for those two names are ignored. Any other name is read as a YAML file
    relative to the scilex package directory.

    Args:
        config_files (dict): Config names mapped to relative file paths.

    Returns:
        dict: A dictionary containing loaded configurations keyed by their names.
    """
    from scilex.settings.resolve import resolve_legacy_configs, resolve_main_config

    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    resolved = {}
    if "api_config" in config_files:
        main_config, api_config = resolve_legacy_configs()
        resolved = {"main_config": main_config, "api_config": api_config}
    elif "main_config" in config_files:
        resolved = {"main_config": resolve_main_config()}
    return {
        key: (
            resolved[key]
            if key in resolved
            else load_yaml_config(os.path.join(package_dir, path))
        )
        for key, path in config_files.items()
    }
