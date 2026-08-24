#!/usr/bin/env bash
# 后台监控 AMF+SMF 实验，写入 logs/campaign_status.log
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/logs/campaign_status.log"
mkdir -p "$ROOT/logs"

while pgrep -f "python3 -B core_fuzzer_dueling.py" >/dev/null 2>&1; do
  TS="$(date '+%F %T')"
  LOG="$(ls -t "$ROOT"/logs/fuzzing_amf_smf_200_*.log 2>/dev/null | head -1)"
  PROG="$(grep -c '📊 进度报告:' "$LOG" 2>/dev/null || echo 0)"
  LAST="$(grep '📊 进度报告:' "$LOG" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')"
  AMF="$(wc -l < "$ROOT/wire_phi_hits_amf.csv" 2>/dev/null || echo 0)"
  SMF="$(wc -l < "$ROOT/wire_phi_hits_smf.csv" 2>/dev/null || echo 0)"
  MSGS="$(python3 - <<PY
from dotenv import dotenv_values
from pymongo import MongoClient
import os, time
os.chdir("$ROOT")
c=dotenv_values(".env")
col=MongoClient(c["MONGO_URI"], serverSelectionTimeoutMS=2000)["CoreFuzzer"][c["DB_NAME"]]
print(col.count_documents({"timestamp": {"\$gte": time.time()-3600}}))
PY
  )"
  echo "$TS | $LAST | amf_hits=$((AMF>0?AMF-1:0)) smf_hits=$((SMF>0?SMF-1:0)) msgs_1h=$MSGS" >> "$OUT"
  sleep 60
done

echo "$(date '+%F %T') | CAMPAIGN_FINISHED" >> "$OUT"
cd "$ROOT" && python3 -B scripts/consistency_compare.py >> "$OUT" 2>&1 || true
python3 - <<PY >> "$OUT"
import json
from pathlib import Path
p = Path("$ROOT/consistency_compare_results.json")
if p.exists():
    rows = json.loads(p.read_text())
    print("SUMMARY total=", len(rows),
          "inconsistency=", sum(1 for r in rows if r.get("confirmed_inconsistency")),
          "confirmed_pv=", sum(1 for r in rows if r.get("confirmed_pv")))
PY
