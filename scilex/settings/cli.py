"""Command-line helpers: shared ``--config/--keys`` options and ``scilex config``."""

import argparse
import functools
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from scilex.config_defaults import COLLECTOR_API_NAMES
from scilex.settings.loader import _flatten, _read_yaml, find_config_file, load_settings
from scilex.settings.migrate import migrate_files
from scilex.settings.resolve import (
    PACKAGE_DIR,
    is_legacy_format,
    resolve_legacy_configs,
)
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError

CONFIG_FILENAME = "scilex.yml"


def add_config_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--config`` and ``--keys`` options to ``parser``."""
    group = parser.add_argument_group("configuration files")
    group.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to scilex.yml (default: $SCILEX_CONFIG, then ./scilex.yml)",
    )
    group.add_argument(
        "--keys",
        metavar="PATH",
        default=None,
        help="Path to keys.yml (default: $SCILEX_KEYS, then ~/.config/scilex/keys.yml)",
    )


def apply_config_arguments(args: argparse.Namespace) -> None:
    """Publish ``--config`` / ``--keys`` through ``SCILEX_CONFIG`` / ``SCILEX_KEYS``.

    Every configuration loader reads these variables, so one assignment here
    reaches all of them (including code running in worker threads).
    """
    if getattr(args, "config", None):
        os.environ["SCILEX_CONFIG"] = str(args.config)
    if getattr(args, "keys", None):
        os.environ["SCILEX_KEYS"] = str(args.keys)


def exit_on_config_error(main: Callable) -> Callable:
    """Decorate a CLI ``main`` so an invalid or missing configuration exits cleanly.

    ``SettingsError`` and ``ConfigFileNotFoundError`` become a readable message on
    stderr and exit code 1 instead of a Python traceback. Other exceptions are
    left untouched.
    """

    @functools.wraps(main)
    def wrapper(*args, **kwargs):
        try:
            return main(*args, **kwargs)
        except (SettingsError, ConfigFileNotFoundError) as error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)

    return wrapper


# ---------------------------------------------------------------------------
# ``scilex config show | migrate | check``
# ---------------------------------------------------------------------------

_SECRET_FIELDS = ("key", "token", "secret", "password")


def _is_secret(dotted_path: str) -> bool:
    return any(word in dotted_path.lower() for word in _SECRET_FIELDS)


def _read_main_file() -> tuple[Path | None, dict | None]:
    """Locate the main config file (legacy package file as a fallback) and parse it."""
    found = find_config_file()
    if found is None:
        legacy = PACKAGE_DIR / "scilex.config.yml"
        found = legacy if legacy.is_file() else None
    return (found, _read_yaml(found)) if found else (None, None)


def config_show() -> int:
    """Print the effective configuration with the origin of every value."""
    try:
        found, raw = _read_main_file()
    except (FileNotFoundError, SettingsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if found is not None and is_legacy_format(raw):
        print(
            f"{found} uses the legacy format; run `scilex config migrate` "
            "to see the new format."
        )
        return 1
    try:
        loaded = load_settings()
    except (FileNotFoundError, SettingsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"# config: {loaded.config_path}")
    print(f"# keys:   {loaded.keys_path or '(none)'}")
    flat = _flatten(loaded.settings.model_dump(mode="python"))
    for dotted, value in flat.items():
        source = loaded.provenance.get(dotted, "default")
        print(f"{dotted} = {json.dumps(value, default=str)}   ({source})")
    keys_flat = _flatten(loaded.keys.model_dump(mode="python"))
    for dotted, value in keys_flat.items():
        if value is None:
            continue
        shown = "***" if _is_secret(dotted) else json.dumps(value, default=str)
        print(
            f"keys.{dotted} = {shown}   ({loaded.provenance.get(f'keys.{dotted}', 'file')})"
        )
    return 0


def config_migrate(
    legacy_dir: str | Path | None, write: bool = False, force: bool = False
) -> int:
    """Convert the legacy files; print the result or write ``./scilex.yml``."""
    source = Path(legacy_dir) if legacy_dir else PACKAGE_DIR
    try:
        text = migrate_files(source)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if not write:
        print(text, end="")
        return 0
    target = Path.cwd() / CONFIG_FILENAME
    if target.exists() and not force:
        print(
            f"Error: {target} already exists (use --force to overwrite)",
            file=sys.stderr,
        )
        return 1
    target.write_text(text)
    print(f"Written: {target}")
    return 0


def config_check() -> int:
    """Validate the configuration without running anything (0 valid, 1 invalid)."""
    try:
        found, raw = _read_main_file()
        if found is not None and is_legacy_format(raw):
            main_config, _ = resolve_legacy_configs()
            problems = [
                f"{key}: required key is missing"
                for key in ("keywords", "years", "apis")
                if not main_config.get(key)
            ]
            apis = main_config.get("apis") or []
            print(f"{found}: legacy format (run `scilex config migrate`)")
        else:
            loaded = load_settings()
            problems = []
            apis = loaded.settings.search.apis
            print(f"{loaded.config_path}: scilex.yml format")
            print(f"keys: {loaded.keys_path or '(none found)'}")
    except (FileNotFoundError, SettingsError) as error:
        print(f"Invalid configuration:\n{error}", file=sys.stderr)
        return 1
    unknown = sorted(set(apis) - set(COLLECTOR_API_NAMES))
    if unknown:
        problems.append(
            f"search.apis: unknown API(s) {unknown}; available: {sorted(COLLECTOR_API_NAMES)}"
        )
    if problems:
        print("Invalid configuration:\n" + "\n".join(problems), file=sys.stderr)
        return 1
    print("Configuration is valid.")
    return 0


def config_main(argv: list[str] | None = None) -> int:
    """Entry point of ``scilex config``."""
    parser = argparse.ArgumentParser(
        prog="scilex config", description="Inspect, check or migrate the configuration."
    )
    commands = parser.add_subparsers(dest="action", required=True)
    for name, text in (
        ("show", "Show the effective configuration and where each value comes from"),
        ("check", "Validate the configuration (exit code 0 when valid)"),
    ):
        add_config_arguments(commands.add_parser(name, help=text))
    migrate = commands.add_parser(
        "migrate", help="Convert the legacy files to scilex.yml"
    )
    migrate.add_argument(
        "--from",
        dest="legacy_dir",
        metavar="DIR",
        help="Directory with the legacy files (default: the scilex package)",
    )
    migrate.add_argument(
        "--write", action="store_true", help="Write ./scilex.yml instead of printing"
    )
    migrate.add_argument(
        "--force", action="store_true", help="Overwrite an existing ./scilex.yml"
    )
    args = parser.parse_args(argv)
    apply_config_arguments(args)
    if args.action == "show":
        return config_show()
    if args.action == "check":
        return config_check()
    return config_migrate(args.legacy_dir, args.write, args.force)
