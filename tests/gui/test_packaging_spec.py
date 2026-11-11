"""Guards on the PyInstaller spec of the desktop app."""

import ast
from pathlib import Path

from scilex.gui.self_test import REQUIRED_DATA

SPEC_PATH = Path(__file__).parents[2] / "packaging" / "scilex-gui.spec"
FORBIDDEN_FRAGMENTS = ("config.yml", "api.config", "keys.yml", "advanced.yml")


def bundled_scilex_data() -> list[tuple[str, str]]:
    """Read the SCILEX_DATA allowlist from the spec without running it."""
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCILEX_DATA"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("SCILEX_DATA not found in the spec")


def test_spec_never_bundles_local_configs_or_keys():
    for directory, pattern in bundled_scilex_data():
        entry = f"{directory}/{pattern}"
        assert not any(fragment in entry for fragment in FORBIDDEN_FRAGMENTS), entry
        assert directory and pattern not in ("*", "**"), f"too broad: {entry}"


def test_spec_matches_self_test_data_list():
    assert dict(bundled_scilex_data()) == REQUIRED_DATA


def test_bundled_patterns_do_not_match_local_config_files():
    package_dir = Path(__file__).parents[2] / "scilex"
    for directory, pattern in bundled_scilex_data():
        for path in (package_dir / directory).glob(pattern):
            assert not any(fragment in path.name for fragment in FORBIDDEN_FRAGMENTS), (
                path
            )
