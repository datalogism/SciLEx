"""``scilex-init``: create a new-format ``scilex.yml`` in the current directory.

Sources, in order: ``--template NAME`` (built-in domain template from
``scilex/templates/*.yml`` or a saved profile), an interactive questionnaire
when stdin is a terminal, otherwise a commented skeleton. Templates and
profiles use the ``scilex.yml`` format; a profile saved in the legacy format is
converted when read.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from scilex.settings.loader import USER_KEYS_PATH
from scilex.settings.migrate import legacy_to_settings
from scilex.settings.presets import PRESETS
from scilex.settings.resolve import is_legacy_format
from scilex.settings.schema import (
    ScilexSettings,
    SettingsError,
    format_validation_error,
)

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
CONFIG_FILENAME = "scilex.yml"
PROFILES_DIR_ENV = "SCILEX_PROFILES_DIR"
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_APIS = ["SemanticScholar", "OpenAlex", "Arxiv"]

SKELETON = """\
# scilex.yml: one file per literature review. Only list what differs from the defaults.
# Full reference: scilex.yml.example. Check this file with: scilex config check
name: {name}
# preset: literature_review      # or: bibliometrics

search:
  keywords:                      # 1 group (OR) or 2 groups (group1 AND group2)
    - [keyword one, keyword two]
    - [other keyword]
  years: {year_start}-{year_end}            # range; a list [2022, 2024] means only those years
  apis: [SemanticScholar, OpenAlex, Arxiv]

# filters:
#   item_types: [journalArticle, conferencePaper]
#   require: [abstract, year]
# ranking:
#   max_papers: 1000
# enrichment:
#   paperswithcode: false
"""


def profiles_dir() -> Path:
    """Directory holding saved profiles (override with ``SCILEX_PROFILES_DIR``)."""
    override = os.environ.get(PROFILES_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / ".config" / "scilex" / "profiles"


def list_templates() -> list[str]:
    """Names of the built-in domain templates."""
    return sorted(path.stem for path in TEMPLATES_DIR.glob("*.yml"))


def list_profiles() -> list[str]:
    """Names of the user's saved profiles."""
    directory = profiles_dir()
    return (
        sorted(path.stem for path in directory.glob("*.yml"))
        if directory.is_dir()
        else []
    )


def _validate_name(name: str) -> str:
    if not _PROFILE_NAME.match(name):
        raise ValueError(
            f"Invalid name '{name}': use letters, digits, '.', '_' or '-' only."
        )
    return name


def resolve_template(name: str) -> Path:
    """Locate a template by name: saved profiles first, then built-in templates.

    Raises:
        FileNotFoundError: If no template or profile has that name.
    """
    _validate_name(name)
    for candidate in (profiles_dir() / f"{name}.yml", TEMPLATES_DIR / f"{name}.yml"):
        if candidate.is_file():
            return candidate
    available = ", ".join(list_templates() + list_profiles())
    raise FileNotFoundError(
        f"Unknown template or profile '{name}'. Available: {available}"
    )


def _read_as_new_format(path: Path) -> tuple[dict, str]:
    """Read a template/profile; convert the legacy format. Returns (data, header)."""
    text = path.read_text()
    data = yaml.safe_load(text) or {}
    header = "".join(line for line in text.splitlines(True) if line.startswith("#"))
    if is_legacy_format(data):
        data = legacy_to_settings(data)
    return data, header


def _dump(data: dict, header: str = "") -> str:
    body = yaml.safe_dump(
        data, sort_keys=False, default_flow_style=None, allow_unicode=True
    )
    return header + body


def _check(data: dict) -> None:
    """Validate ``data`` against the schema.

    Raises:
        SettingsError: With a readable message when invalid.
    """
    try:
        ScilexSettings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(format_validation_error(exc, data)) from exc


def _write(text: str, output: Path, force: bool) -> Path:
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists (use --force to overwrite)")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output


def apply_template(name: str, output: Path, force: bool = False) -> Path:
    """Write a template or profile to ``output`` in the ``scilex.yml`` format.

    Raises:
        FileExistsError: If ``output`` exists and ``force`` is False.
        FileNotFoundError: If the template does not exist.
        SettingsError: If the template is not a valid configuration.
    """
    data, header = _read_as_new_format(resolve_template(name))
    _check(data)
    return _write(_dump(data, header), output, force)


def save_profile(name: str, config_path: Path, force: bool = False) -> Path:
    """Save ``config_path`` as profile ``name`` (new format).

    Raises:
        FileNotFoundError: If the current config does not exist.
        FileExistsError: If the profile exists and ``force`` is False.
    """
    _validate_name(name)
    if not config_path.is_file():
        raise FileNotFoundError(f"No configuration to save: {config_path}")
    data, header = _read_as_new_format(config_path)
    return _write(_dump(data, header), profiles_dir() / f"{name}.yml", force)


def skeleton_text(name: str = "my_review") -> str:
    """Return a commented, valid ``scilex.yml`` skeleton."""
    year = date.today().year
    return SKELETON.format(name=name, year_start=year - 2, year_end=year)


def _split_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def interactive_config(
    ask: Callable[[str], str] | None = None, default_name: str = "my_review"
) -> dict:
    """Ask a few questions and return a ``scilex.yml`` dictionary.

    Args:
        ask: Function showing a prompt and returning the answer (default ``input``).
        default_name: Review name proposed by default.
    """
    ask = ask or input
    year = date.today().year

    def question(prompt: str, default: str) -> str:
        return ask(f"{prompt} [{default}]: ").strip() or default

    name = question("Review name", default_name)
    keywords = [_split_list(question("Keywords, group 1 (comma separated)", ""))]
    second = _split_list(ask("Keywords, group 2 (optional, ANDed with group 1): "))
    if second:
        keywords.append(second)
    years = question("Years", f"{year - 2}-{year}")
    apis = _split_list(question("APIs", ",".join(DEFAULT_APIS)))
    preset = question(f"Preset ({'/'.join(PRESETS)}/none)", "none")
    data: dict = {"name": name}
    if preset != "none":
        data["preset"] = preset
    data["search"] = {"keywords": keywords, "years": years, "apis": apis}
    return data


def _keys_hint() -> str | None:
    """Tell the user where to create ``keys.yml`` when none is found."""
    if os.environ.get("SCILEX_KEYS") or USER_KEYS_PATH.expanduser().is_file():
        return None
    return (
        f"No keys file found. Create {USER_KEYS_PATH} from keys.yml.example "
        "(API keys are never copied into your project)."
    )


def run_init(args: argparse.Namespace) -> int:
    """Execute ``init`` for parsed arguments; returns the exit code."""
    output = Path(args.config) if args.config else Path.cwd() / CONFIG_FILENAME
    try:
        if args.list_templates:
            print("Built-in templates:")
            for name in list_templates():
                print(f"  {name}")
            profiles = list_profiles()
            print("Saved profiles:" if profiles else "Saved profiles: (none)")
            for name in profiles:
                print(f"  {name}")
        if args.save_profile:
            path = save_profile(args.save_profile, output, args.force)
            print(f"Profile saved: {path}")
        if args.template:
            path = apply_template(args.template, output, args.force)
        elif args.list_templates or args.save_profile:
            return 0
        elif sys.stdin.isatty():
            data = interactive_config(default_name=Path.cwd().name)
            _check(data)
            path = _write(_dump(data), output, args.force)
        else:
            path = _write(skeleton_text(Path.cwd().name), output, args.force)
        print(f"Configuration written: {path}")
        print(
            "Next: edit it, check it with `scilex config check`, then scilex-collect."
        )
        hint = _keys_hint()
        if hint:
            print(hint)
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def build_parser(prog: str = "scilex-init") -> argparse.ArgumentParser:
    """Build the argument parser shared by ``scilex-init`` and ``scilex init``."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Create scilex.yml in the current directory.",
    )
    parser.add_argument("--template", metavar="NAME", help="Template or profile name")
    parser.add_argument(
        "--list-templates", action="store_true", help="List templates and profiles"
    )
    parser.add_argument(
        "--save-profile",
        metavar="NAME",
        help="Save the current scilex.yml as ~/.config/scilex/profiles/NAME.yml",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config file to write or to read (--save-profile); default ./scilex.yml",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point of ``scilex-init``."""
    return run_init(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
