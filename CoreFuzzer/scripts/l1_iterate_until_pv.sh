#!/usr/bin/env bash
# Tighten L1 → rescore/replay → fuzz loop until L4 confirmed_pv > 0 (or max rounds).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MAX_ROUNDS="${MAX_ROUNDS:-3}"
ITER="${ITER:-200}"
FUZZ_LOG="${FUZZ_LOG:-}"
PREP_STACK="${PREP_STACK:-false}"

echo "=== L1 iterate until L4 (max_rounds=$MAX_ROUNDS iter=$ITER) ==="

python3 -B <<'PY'
from objects.l1_policy import HIT_CSV_FIELDS
import csv
from pathlib import Path
for name in ("wire_phi_hits_amf.csv", "wire_phi_hits_smf.csv", "wire_phi_hits.csv"):
    with Path(name).open("w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=HIT_CSV_FIELDS).writeheader()
PY

if [[ -n "$FUZZ_LOG" && -f "$FUZZ_LOG" ]]; then
  echo "=== rescore from log: $FUZZ_LOG ==="
  python3 -B scripts/rescore_hits.py --log "$FUZZ_LOG" || true
  python3 -B scripts/consistency_compare.py || true
fi

for round in $(seq 1 "$MAX_ROUNDS"); do
  echo ""
  echo "=== round $round/$MAX_ROUNDS ==="

  L4=0
  if [[ -f consistency_compare_results.json ]]; then
    L4=$(python3 -B -c "import json; r=json.load(open('consistency_compare_results.json')); print(sum(1 for x in r if x.get('confirmed_pv')))")
  fi
  HITS=$(python3 -B -c "import csv; from pathlib import Path; p=Path('wire_phi_hits.csv'); print(0 if not p.exists() or p.stat().st_size==0 else sum(1 for _ in csv.DictReader(p.open(encoding='utf-8-sig'))))")

  echo "  L1 hits=$HITS L4 confirmed_pv=$L4"
  if [[ "$L4" -gt 0 ]]; then
    echo "=== L4 confirmed PV found — done ==="
    exit 0
  fi

  if [[ "$HITS" -gt 0 ]]; then
    echo "=== replay (consistency_compare) ==="
    python3 -B scripts/consistency_compare.py || true
    L4=$(python3 -B -c "import json; r=json.load(open('consistency_compare_results.json')); print(sum(1 for x in r if x.get('confirmed_pv')))" 2>/dev/null || echo 0)
    if [[ "$L4" -gt 0 ]]; then
      echo "=== L4 confirmed PV after replay — done ==="
      exit 0
    fi
  fi

  echo "=== fuzz campaign ($ITER iter) ==="
  PREP_STACK="$PREP_STACK" bash "$ROOT/scripts/run_amf_smf_campaign.sh" "$ITER"
  PREP_STACK=false

  L4=$(python3 -B -c "import json; r=json.load(open('consistency_compare_results.json')); print(sum(1 for x in r if x.get('confirmed_pv')))" 2>/dev/null || echo 0)
  if [[ "$L4" -gt 0 ]]; then
    echo "=== L4 confirmed PV after fuzz — done ==="
    exit 0
  fi
done

echo "=== max rounds reached without L4 confirmed PV ==="
exit 1
