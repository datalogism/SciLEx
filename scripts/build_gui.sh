#!/usr/bin/env bash
# Build the SciLEx desktop app with PyInstaller, then run its self-test.
# Usage: scripts/build_gui.sh [DIST_DIR]   (default: dist)
# The post-commit hook builds into a staging folder, then swaps it into dist/,
# so dist/ always holds a complete app.
set -euo pipefail
cd "$(dirname "$0")/.."
dist_dir="${1:-dist}"

uv run --extra gui --extra build pyinstaller packaging/scilex-gui.spec \
  --noconfirm --clean --distpath "$dist_dir"

case "$(uname -s)" in
  Darwin) executable="$dist_dir/SciLEx.app/Contents/MacOS/SciLEx" ;;
  MINGW*|MSYS*|CYGWIN*) executable="$dist_dir/SciLEx/SciLEx.exe" ;;
  *) executable="$dist_dir/SciLEx/SciLEx" ;;
esac

"$executable" --self-test
