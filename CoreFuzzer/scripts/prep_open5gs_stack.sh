#!/usr/bin/env bash
# 清理并启动 Open5GS + UERANSIM 单实例栈（供 AMF+SMF fuzz 使用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs /data/db 2>/dev/null || true

echo "=== prep Open5GS stack ==="
O5GS_SRC="${OPEN5GS_SRC:-/corefuzzer_deps/open5gs}"
if [[ -d "$O5GS_SRC/.git" ]]; then
  O5GS_VER="$(git -C "$O5GS_SRC" describe --tags --exact-match 2>/dev/null || git -C "$O5GS_SRC" describe --tags --always 2>/dev/null || echo unknown)"
  echo "Open5GS $O5GS_VER"
fi

# Default: keep the SUT on the newest vX.Y.Z tag. Set OPEN5GS_ENSURE_LATEST=false to skip.
if [[ "${OPEN5GS_ENSURE_LATEST:-true}" == "true" ]]; then
  echo "OPEN5GS_ENSURE_LATEST=true, upgrading if needed"
  bash "$ROOT/scripts/upgrade_open5gs_latest.sh"
fi

if [[ "${PREP_FORCE:-false}" != "true" ]]; then
  amf_c=$(pgrep -c -x open5gs-amfd 2>/dev/null || echo 0)
  gnb_c=$(pgrep -c -x nr-gnb 2>/dev/null || echo 0)
  ue_c=$(pgrep -c -x nr-ue 2>/dev/null || echo 0)
  if [[ "$amf_c" == "1" && "$gnb_c" == "1" && "$ue_c" == "1" ]]; then
    echo "stack already healthy (amf/gnb/ue=1), skip prep (PREP_FORCE=true to redo)"
    exit 0
  fi
fi

kill_all() {
  for name in nr-ue nr-gnb; do
    pkill -9 -x "$name" 2>/dev/null || true
  done
  # 停止全部 Open5GS 网元，避免 PFCP/SBI 端口冲突（用 -x，避免误杀 docker exec）
  pkill -9 -x 5gc 2>/dev/null || true
  for name in open5gs-amfd open5gs-smfd open5gs-upfd open5gs-nrfd open5gs-udmd open5gs-pcfd open5gs-ausfd open5gs-udrd open5gs-scpd open5gs-nssfd open5gs-bsfd open5gs-seppd; do
    pkill -9 -x "$name" 2>/dev/null || true
  done
  sleep 2
  for _ in $(seq 1 10); do
    amf_c=$(pgrep -c -x open5gs-amfd 2>/dev/null || echo 0)
    [[ "$amf_c" == "0" ]] && break
    pkill -9 -x open5gs-amfd 2>/dev/null || true
    sleep 0.5
  done
}

kill_all
# 二次清理残留，直到为 0
for _ in $(seq 1 8); do
  pgrep -x nr-ue | xargs -r kill -9 2>/dev/null || true
  pgrep -x nr-gnb | xargs -r kill -9 2>/dev/null || true
  sleep 0.4
  ue=$(pgrep -c -x nr-ue 2>/dev/null || echo 0)
  gnb=$(pgrep -c -x nr-gnb 2>/dev/null || echo 0)
  [[ "$ue" == "0" && "$gnb" == "0" ]] && break
done

echo "after cleanup: ue=$(pgrep -c -x nr-ue || echo 0) gnb=$(pgrep -c -x nr-gnb || echo 0)"

# MongoDB
if ! pgrep -x mongod >/dev/null 2>&1; then
  echo "starting mongod..."
  nohup mongod --dbpath /data/db --bind_ip 127.0.0.1 >> logs/mongod.log 2>&1 &
  sleep 3
fi

# Open5GS Core（kill_all 后始终重启）
echo "starting 5gc..."
CFG="/corefuzzer_deps/open5gs/build/configs/sample.yaml"
nohup 5gc -c "$CFG" >> logs/core.log 2>&1 &
sleep 15

if ! pgrep -x open5gs-amfd >/dev/null 2>&1; then
  echo "ERROR: open5gs-amfd not running" >&2
  tail -20 logs/core.log >&2 || true
  exit 1
fi

GNB_CFG="/corefuzzer_deps/ueransim/config/open5gs-gnb.yaml"
UE_CFG="/corefuzzer_deps/ueransim/config/open5gs-ue.yaml"
IMSI="${OPEN5GS_IMSI:-imsi-999700000000001}"

echo "starting nr-gnb..."
# 确保无残留 gNB
pgrep -x nr-gnb | xargs -r kill -9 2>/dev/null || true
sleep 1
nohup nr-gnb -c "$GNB_CFG" >> logs/gnb.log 2>&1 &
sleep 5

if [[ "${PREP_SKIP_UE:-false}" == "true" ]]; then
  echo "PREP_SKIP_UE=true, not starting nr-ue (SBI/PFCP/NGAP campaign)"
  pgrep -x nr-ue | xargs -r kill -9 2>/dev/null || true
else
  echo "starting nr-ue ($IMSI)..."
  nohup nr-ue -c "$UE_CFG" -i "$IMSI" >> logs/ue.log 2>&1 &
  sleep 8

  # 用 ss 检测端口，避免 connect 后 disconnect 导致 UE statelearner 崩溃
  for i in $(seq 1 40); do
    if ss -ltn 2>/dev/null | grep -q ':45678 '; then
      if pgrep -x nr-ue >/dev/null 2>&1; then
        echo "UE control port 45678 OK (nr-ue running)"
        break
      fi
    fi
    sleep 1
    if [[ "$i" == "40" ]]; then
      echo "UE control port NOT ready" >&2
      tail -10 logs/ue.log >&2 || true
      exit 1
    fi
  done
fi

echo "stack ready: amf=$(pgrep -c -x open5gs-amfd) gnb=$(pgrep -c -x nr-gnb) ue=$(pgrep -c -x nr-ue) mongo=$(pgrep -c -x mongod)"

count_live() {
  local name="$1"
  ps -eo state,comm | awk -v n="$name" '$1 !~ /Z/ && $2 == n {c++} END {print c+0}'
}

need=(open5gs-amfd nr-gnb)
if [[ "${PREP_SKIP_UE:-false}" != "true" ]]; then
  need+=(nr-ue)
fi
for svc in "${need[@]}"; do
  c=$(count_live "$svc")
  if [[ "$c" != "1" ]]; then
    echo "ERROR: expected exactly 1 live $svc, got $c (zombies ignored)" >&2
    ps -eo pid,state,cmd | grep -E "$svc|defunct" | grep -v grep >&2 || true
    exit 1
  fi
done
echo "single-instance check OK"
