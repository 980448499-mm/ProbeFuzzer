#!/usr/bin/env bash
# Switch fuzzing from UE NAS to N11/SBI, PFCP, and malicious-gNB NGAP.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

export IFACE_ITERS="${1:-60}"
export PREP_STACK="${PREP_STACK:-true}"
export PREP_FORCE="${PREP_FORCE:-true}"
export PREP_SKIP_UE="${PREP_SKIP_UE:-true}"

TS="$(date +%Y%m%d_%H%M%S)"
LOG="$ROOT/logs/iface_campaign_${IFACE_ITERS}_${TS}.log"

echo "=== prep stack (skip UE) ==="
if [[ "$PREP_STACK" == "true" ]]; then
  bash "$ROOT/scripts/prep_open5gs_stack.sh"
fi
if [[ -x "$ROOT/scripts/open5gs_latest_tag.sh" ]]; then
  echo "Open5GS running=$(git -C /corefuzzer_deps/open5gs describe --tags --exact-match 2>/dev/null || echo unknown) latest=$("$ROOT/scripts/open5gs_latest_tag.sh" || true)"
fi

echo "=== interface campaign iters=$IFACE_ITERS ==="
echo "log: $LOG"
PYTHONUNBUFFERED=1 python3 -B scripts/run_iface_campaign.py 2>&1 | tee "$LOG"
echo "done."
