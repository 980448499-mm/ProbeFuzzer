#!/usr/bin/env bash
# AMF+SMF 联合 wire-Φ 实验：prep → fuzz → 双栈一致性对照
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ITER="${1:-200}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

export ITERATION_LIMIT="$ITER"
export FSM_LOAD_MODE="${FSM_LOAD_MODE:-latest}"
export RESET_RL_STATS="${RESET_RL_STATS:-false}"
export PREP_STACK="${PREP_STACK:-true}"
export SKIP_INITIAL_RESET="${SKIP_INITIAL_RESET:-true}"
export PARTIAL_RESET_UE_ONLY="${PARTIAL_RESET_UE_ONLY:-true}"
export LIGHT_RESET="${LIGHT_RESET:-true}"
export FORCE_REGISTERED_SM="${FORCE_REGISTERED_SM:-true}"
export RUN_BYPASS_SEEDS="${RUN_BYPASS_SEEDS:-true}"

TS="$(date +%Y%m%d_%H%M%S)"
FUZZ_LOG="$LOG_DIR/fuzzing_amf_smf_${ITER}_${TS}.log"

echo "=== prep stack (PREP_STACK=$PREP_STACK) ==="
if [[ "$PREP_STACK" == "true" ]]; then
  bash "$ROOT/scripts/prep_open5gs_stack.sh"
else
  echo "  (skip prep)"
fi
echo "Open5GS $(git -C /corefuzzer_deps/open5gs describe --tags --exact-match 2>/dev/null || echo unknown)"

echo "=== AMF+SMF wire-Φ campaign: ${ITER} iterations ==="
echo "  FSM_LOAD_MODE=$FSM_LOAD_MODE LIGHT_RESET=$LIGHT_RESET PARTIAL_RESET_UE_ONLY=$PARTIAL_RESET_UE_ONLY"
echo "  FORCE_REGISTERED_SM=$FORCE_REGISTERED_SM RUN_BYPASS_SEEDS=$RUN_BYPASS_SEEDS"
echo "log: $FUZZ_LOG"

# 清空本轮 hit / typed 文件（保留历史请自行备份）并写入表头
python3 -B <<'PY'
from objects.l1_policy import HIT_CSV_FIELDS, TYPED_CSV_FIELDS
import csv
from pathlib import Path
for name in ("wire_phi_hits_amf.csv", "wire_phi_hits_smf.csv", "wire_phi_hits.csv"):
    with Path(name).open("w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=HIT_CSV_FIELDS).writeheader()
with Path("typed_responses.csv").open("w", encoding="utf-8-sig", newline="") as f:
    csv.DictWriter(f, fieldnames=TYPED_CSV_FIELDS).writeheader()
PY

PYTHONUNBUFFERED=1 python3 -B core_fuzzer_dueling.py 2>&1 | tee "$FUZZ_LOG"

echo ""
echo "=== wire-Φ hits ==="
for f in wire_phi_hits_amf.csv wire_phi_hits_smf.csv wire_phi_hits.csv; do
  if [[ -f "$f" ]]; then
    n=$(($(wc -l < "$f") - 1))
    echo "  $f: $n hits"
  fi
done

echo "=== typed responses ==="
if [[ -f typed_responses.csv ]]; then
  echo "  typed_responses.csv: $(($(wc -l < typed_responses.csv) - 1)) rows"
fi
echo ""
echo "=== dual-stack consistency compare ==="
python3 -B scripts/consistency_compare.py 2>&1 | tee "$LOG_DIR/consistency_amf_smf_${TS}.log"

echo ""
echo "=== summary (L1–L4) ==="
python3 -B <<'PY'
import json
from pathlib import Path
p = Path("consistency_compare_results.json")
if not p.exists():
    print("no consistency_compare_results.json")
    raise SystemExit(0)
rows = json.loads(p.read_text())
amf = [r for r in rows if r.get("component") == "amf"]
smf = [r for r in rows if r.get("component") == "smf"]
print(f"L1 oracle_hit: {len(rows)} (amf={len(amf)}, smf={len(smf)})")
print(f"L2 replay_ok: {sum(1 for r in rows if r.get('replay_ok'))}")
print(f"L3 confirmed_inconsistency: {sum(1 for r in rows if r.get('confirmed_inconsistency'))}")
print(f"L3b semantic_divergence: {sum(1 for r in rows if r.get('semantic_divergence'))}")
print(f"L4 confirmed_pv: {sum(1 for r in rows if r.get('confirmed_pv'))}")
PY

echo "done."
