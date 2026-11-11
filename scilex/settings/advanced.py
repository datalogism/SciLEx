"""Merge of the legacy ``scilex.advanced.yml`` into the main configuration."""

import copy


def deep_merge_dicts(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (mutates and returns base).

    Nested dicts are merged key by key; any other value in ``override``
    replaces the one in ``base``. Values copied from ``override`` are
    deep-copied so the result never aliases the override.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge_dicts(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def merge_advanced_config(main_config: dict, advanced_config: dict | None) -> None:
    """Merge advanced config into main config (mutates main_config).

    Precedence:
      * ``quality_filters``: deep-merged, advanced values override the main
        config's, recursively (a partial ``relevance_weights`` override keeps
        the other weights). A null ``quality_filters`` on either side is
        treated as empty.
      * Every other key: taken from the advanced config only if absent from
        the main config (main always wins).

    Args:
        main_config: Main configuration to merge into.
        advanced_config: Advanced overrides to apply (None is a no-op).
    """
    for key, value in (advanced_config or {}).items():
        if key == "quality_filters":
            main_config["quality_filters"] = deep_merge_dicts(
                main_config.get("quality_filters") or {}, value or {}
            )
        elif key not in main_config:
            main_config[key] = value
