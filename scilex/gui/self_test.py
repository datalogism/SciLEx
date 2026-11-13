"""``scilex-gui --self-test``: check an installation without opening a window.

Run by the packaging CI on every built executable: a PyInstaller build that
succeeds can still miss modules or data files, which only shows at runtime.
"""

import importlib
import os
import sys
import tempfile
import traceback
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import scilex

PACKAGE_DIR = Path(scilex.__file__).parent

# Data files the app needs at runtime (also the PyInstaller ``datas`` list).
# (directory, pattern) pairs: a directory may have several patterns.
REQUIRED_DATA = [
    ("templates", "*.yml"),
    ("rdf/queries", "*.rq"),
    ("data/venue_rankings", "*.csv"),
    ("tagging", "*.csv"),
    ("gui/assets", "*.png"),
    ("gui/assets/dashboard", "dashboard.*"),
    ("gui/assets/dashboard/vendor", "*.js"),
    # Pinned scilex-lpwc-ap profile, mapped by ⑧ Export (knowledge graph).
    ("kg/ap", "VERSION.json"),
    ("kg/ap/ontology", "*.ttl"),
    ("kg/ap/shapes", "*.ttl"),
    ("kg/ap/mappings/rml", "*.ttl"),
    ("kg/ap/mappings/functions", "*.py"),
    ("kg/ap/mappings/sparql", "*.ru"),
    # Mapping interface (loaded by path), reference profiles, tables, JSON Schemas.
    ("kg/ap/mappings", "*.py"),
    ("kg/ap/mappings", "*.json"),
    ("kg/ap/mappings/collections", "*.json"),
    ("kg/ap/mappings/alignments", "*.json"),
]

REQUIRED_MODULES = (
    "nicegui",
    "webview",
    "platformdirs",
    "rdflib",
    "pandas",
    "morph_kgc",
    "pyoxigraph",
    "pyshacl",
    "scilex.pipeline.orchestrator",
    "scilex.crawlers.aggregate_parallel",
    "scilex.crawlers.collector_collection",
    "scilex.export_to_bibtex",
    "scilex.gui.app",
)
# The Linux build ships Qt WebEngine for the native window.
if sys.platform.startswith("linux"):
    # PyQt6 first: qtpy hides the reason why the bindings fail to load.
    REQUIRED_MODULES += ("PyQt6.QtWebEngineWidgets", "qtpy", "webview.platforms.qt")


def _square(value: int) -> int:
    return value * value


def check_imports() -> str:
    """Import every module the app relies on."""
    for name in REQUIRED_MODULES:
        importlib.import_module(name)
    return f"{len(REQUIRED_MODULES)} modules"


def check_step_pages() -> str:
    """Check that every sidebar step has a page module (loaded dynamically, so
    PyInstaller would not notice a missing one)."""
    from scilex.gui.components.stepper import STEPS
    from scilex.gui.pages.review import step_module

    missing = [key for key in STEPS if step_module(key) is None]
    if missing:
        raise ModuleNotFoundError(f"no page module for steps: {', '.join(missing)}")
    return f"{len(STEPS)} pages"


def check_data_files() -> str:
    """Check that each data directory exists and is not empty."""
    counts = []
    for directory, pattern in REQUIRED_DATA:
        files = list((PACKAGE_DIR / directory).glob(pattern))
        if not files:
            raise FileNotFoundError(f"no {pattern} in {PACKAGE_DIR / directory}")
        counts.append(f"{directory}: {len(files)}")
    return ", ".join(counts)


def check_multiprocessing() -> str:
    """Run a trivial function in worker processes (needs freeze_support when frozen)."""
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_square, range(4)))
    if results != [0, 1, 4, 9]:
        raise RuntimeError(f"unexpected results {results}")
    return "2 workers"


def check_review_roundtrip() -> str:
    """Create a review in a temporary folder and load its pipeline config."""
    from scilex.gui.services.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        keys_path = tmp_path / "keys.yml"
        keys_path.write_text("{}\n", encoding="utf-8")
        os.environ["SCILEX_KEYS"] = str(keys_path)
        try:
            workspace = Workspace(registry_path=tmp_path / "registry.yml")
            review = workspace.create_review(
                tmp_path / "review", name="self_test", template="computer-science"
            )
            config = Workspace.load_config(review, keys_path=keys_path)
        finally:
            os.environ.pop("SCILEX_KEYS", None)
        if config.main["collect_name"] != "self_test":
            raise RuntimeError("config not loaded from the new review")
    return "create + load ok"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("imports", check_imports),
    ("step pages", check_step_pages),
    ("data files", check_data_files),
    ("multiprocessing", check_multiprocessing),
    ("review round-trip", check_review_roundtrip),
)


def run_self_test() -> int:
    """Run every check, print a report and return the process exit code."""
    failures = 0
    print(f"SciLEx self-test (frozen={getattr(sys, 'frozen', False)})")
    for name, check in CHECKS:
        try:
            detail = check()
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            print(f"ok   {name}: {detail}")
    print("self-test passed" if not failures else f"self-test FAILED ({failures})")
    return 1 if failures else 0
