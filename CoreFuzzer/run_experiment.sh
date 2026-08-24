#!/bin/bash
# 一键跑实验：启动 MongoDB → 停系统 Open5GS → 跑本地 fuzzer（含故障注入）。
# 需要 root（启动 mongod、停系统 Open5GS、nr-ue 需要特权）。
set -e
cd "$(dirname "$0")"

echo "=== [1/4] 启动 MongoDB（Docker 容器）==="
if docker ps --format '{{.Names}}' | grep -q '^probe-fuzzer-mongo$'; then
  echo "  MongoDB 容器已在运行"
elif docker ps -a --format '{{.Names}}' | grep -q '^probe-fuzzer-mongo$'; then
  docker start probe-fuzzer-mongo >/dev/null && echo "  MongoDB 容器已启动"
else
  docker run -d --name probe-fuzzer-mongo -p 27017:27017 mongo:6.0 >/dev/null && echo "  MongoDB 容器已创建并启动"
fi
sleep 3

echo "=== [2/4] 停掉系统 Open5GS（避免和本地 /tmp/ogs 版本端口冲突）==="
sudo pkill -2 -f "/usr/bin/open5gs-amfd" 2>/dev/null || true
sudo pkill -2 -f "/usr/bin/open5gs-smfd" 2>/dev/null || true
sudo pkill -2 -x "5gc" 2>/dev/null || true
sleep 2
if pgrep -f "/usr/bin/open5gs-amfd" >/dev/null; then
  echo "  ⚠️ 系统 open5gs-amfd 仍在运行，请手动确认"
else
  echo "  系统 Open5GS 已停"
fi

echo "=== [3/4] 初始化 UE 数据库（注册 IMSI 到 MongoDB）==="
python3 scripts/init_db.py "$(cd .. && pwd)/open5gs" 2>/dev/null || \
  echo "  ⚠️ init_db 失败或已初始化（可忽略）"

echo "=== [4/4] 跑 fuzzer（CORE 和故障注入从环境变量读取）==="
exec ./run_local.sh "$@"
