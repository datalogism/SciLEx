# PyInstaller spec for the SciLEx desktop app.
# Build: scripts/build_gui.sh   (or: uv run --extra gui --extra build pyinstaller packaging/scilex-gui.spec --noconfirm)
# Output: dist/SciLEx/ (Windows, Linux) and dist/SciLEx.app (macOS).
# SCILEX_ONEFILE=1 builds one self-extracting dist/SciLEx.exe instead
# (Windows only; see scripts/build_exe_desktop.ps1).
import os
import sys
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is defined by PyInstaller)
SCILEX = ROOT / "scilex"

# Explicit allowlist of runtime data files (same list as scilex/gui/self_test.py).
# Never add scilex/*.config.yml, scilex/api.config*, keys.yml: local files that
# may hold API keys (tests/gui/test_packaging_spec.py guards this).
SCILEX_DATA = [
    ("templates", "*.yml"),
    ("rdf/queries", "*.rq"),
    ("data/venue_rankings", "*.csv"),
    ("tagging", "*.csv"),
    ("gui/assets", "*.png"),
    # Pinned scilex-lpwc-ap profile, mapped by Export (knowledge graph).
    ("kg/ap", "VERSION.json"),
    ("kg/ap/ontology", "*.ttl"),
    ("kg/ap/shapes", "*.ttl"),
    ("kg/ap/mappings/rml", "*.ttl"),
    ("kg/ap/mappings/functions", "*.py"),
    ("kg/ap/mappings/sparql", "*.ru"),
]
ASSETS = SCILEX / "gui" / "assets"

datas = [
    (str(SCILEX / directory / pattern), f"scilex/{directory}")
    for directory, pattern in SCILEX_DATA
]
# NiceGUI serves its static files (JS, CSS, fonts) from its package directory.
datas.append((str(Path(nicegui.__file__).parent), "nicegui"))
# pyshacl reads its SHACL/DASH vocabularies from package files.
datas += collect_data_files("pyshacl")

# Every SciLEx module, since the app exposes all pipeline commands, even those
# no GUI page imports yet.
hiddenimports = collect_submodules("scilex")
# rdflib loads its parsers and serializers as plugins, by name.
hiddenimports += collect_submodules("rdflib.plugins")
# Knowledge graph: morph-kgc (RML engine, imports its readers by name), SHACL.
hiddenimports += collect_submodules("morph_kgc")
hiddenimports += collect_submodules("pyshacl")
hiddenimports += collect_submodules("owlrl")
if sys.platform.startswith("linux"):
    # pywebview imports its Qt backend lazily; Linux ships Qt WebEngine
    # (see scilex/gui/native_window.py).
    hiddenimports += [
        "webview.platforms.qt",
        "qtpy",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebChannel",
    ]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

ONEFILE = os.environ.get("SCILEX_ONEFILE") == "1" and sys.platform == "win32"

if ONEFILE:
    # One self-extracting SciLEx.exe (unpacks to %TEMP% on each launch).
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="SciLEx",
        icon=str(ASSETS / "icon.ico"),
        console=False,
        disable_windowed_traceback=False,
        upx=False,
    )
else:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="SciLEx",
        icon=str(ASSETS / "icon.ico"),
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="SciLEx",
    )

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="SciLEx.app",
        icon=str(ASSETS / "icon.icns"),
        bundle_identifier="fr.univ-cotedazur.scilex",
        info_plist={"NSHighResolutionCapable": True},
    )
