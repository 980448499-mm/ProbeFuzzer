#!/usr/bin/env bash
# Print the newest Open5GS vX.Y.Z tag (optionally from a local clone).
set -euo pipefail
REPO="${1:-/corefuzzer_deps/open5gs}"
if [[ ! -d "$REPO/.git" ]]; then
  REPO="$(cd "$(dirname "$0")/../../open5gs" 2>/dev/null && pwd)" || true
fi
if [[ -d "${REPO:-}/.git" ]]; then
  git -C "$REPO" fetch --tags --prune origin >/dev/null 2>&1 || true
  git -C "$REPO" tag -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
  exit 0
fi
git ls-remote --tags https://github.com/open5gs/open5gs.git \
  | awk '{print $2}' | sed 's#refs/tags/##' | sed 's#\^{}##' \
  | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
