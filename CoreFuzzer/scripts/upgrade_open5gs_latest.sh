#!/usr/bin/env bash
# Checkout, build, and install the latest Open5GS release tag.
# Intended to run inside corefuzzer-wirephi (or any host with the same layout).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${OPEN5GS_SRC:-/corefuzzer_deps/open5gs}"
FORCE="${OPEN5GS_FORCE:-false}"
PREFIX="${OPEN5GS_PREFIX:-/}"

latest_tag() {
  git -C "$SRC" fetch --tags --prune origin >/dev/null 2>&1 || true
  git -C "$SRC" tag -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
}

current_tag() {
  git -C "$SRC" describe --tags --exact-match 2>/dev/null || true
}

if [[ ! -d "$SRC/.git" ]]; then
  echo "ERROR: Open5GS git clone not found at $SRC" >&2
  exit 1
fi

TAG="$(latest_tag)"
CUR="$(current_tag)"
echo "Open5GS latest=$TAG current=${CUR:-unknown}"
if [[ "$FORCE" != "true" && "$CUR" == "$TAG" && -x "$SRC/build/src/smf/open5gs-smfd" ]]; then
  echo "$TAG" > "$SRC/.corefuzzer_tag"
  echo "already on $TAG, skip build (OPEN5GS_FORCE=true to rebuild)"
  exit 0
fi

echo "stopping NFs..."
pkill -9 -x 5gc 2>/dev/null || true
for name in nr-ue nr-gnb open5gs-amfd open5gs-smfd open5gs-upfd open5gs-nrfd \
            open5gs-udmd open5gs-pcfd open5gs-ausfd open5gs-udrd open5gs-scpd \
            open5gs-nssfd open5gs-bsfd open5gs-seppd; do
  pkill -9 -x "$name" 2>/dev/null || true
done

git -C "$SRC" checkout --force "$TAG"
rm -rf "$SRC/build"
meson "$SRC/build" --prefix="$PREFIX" -Db_coverage=true
ninja -C "$SRC/build" -j"$(nproc)"
ninja -C "$SRC/build" install
cp -f "$SRC/build/tests/app/5gc" /usr/bin/5gc
ldconfig 2>/dev/null || true

python3 "$ROOT/scripts/patch_open5gs_lab_sample.py" "$SRC/build/configs/sample.yaml"
if [[ -d "$ROOT" ]]; then
  cp -f "$SRC/build/configs/sample.yaml" "$ROOT/sample.yaml"
fi
echo "$TAG" > "$SRC/.corefuzzer_tag"
echo "installed Open5GS $TAG"
