#!/usr/bin/env bash
# 20 iter smoke test：验证 Fuzzing enabled + Mongo 入库
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== AMF+SMF smoke test (20 iter) ==="
echo "  (请先 docker restart + prep_open5gs_stack.sh，本脚本不再重复 prep)"
export PREP_STACK=false
export RESET_RL_STATS=false
bash "$ROOT/scripts/run_amf_smf_campaign.sh" 20

LOG=$(ls -t "$ROOT"/logs/fuzzing_amf_smf_20_*.log 2>/dev/null | head -1)
echo ""
echo "=== smoke checks ==="
grep -c "Fuzzing enabled" "$LOG" 2>/dev/null || echo "Fuzzing enabled: 0"
grep "📊 进度报告" "$LOG" 2>/dev/null | tail -2 || true
python3 - <<PY
from dotenv import dotenv_values
from pymongo import MongoClient
import os, time
os.chdir("$ROOT")
c = dotenv_values(".env")
col = MongoClient(c["MONGO_URI"], serverSelectionTimeoutMS=3000)["CoreFuzzer"][c["DB_NAME"]]
print("messages_last_30min:", col.count_documents({"timestamp": {"$gte": time.time() - 1800}}))
PY
