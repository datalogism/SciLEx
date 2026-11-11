#!/usr/bin/env bash
# Install the post-commit hook that rebuilds the desktop app.
set -euo pipefail
cd "$(dirname "$0")/../.."
hooks_dir="$(git rev-parse --git-common-dir)/hooks"
ln -sf "$PWD/scripts/git-hooks/post-commit" "$hooks_dir/post-commit"
echo "Installed $hooks_dir/post-commit -> scripts/git-hooks/post-commit"
