#!/bin/bash
# 本地运行 ProbeFuzzer（不走 Docker），使用本地重编译的 Open5GS（含故障注入改动）。
# 前置：已执行 open5gs 的 ninja 构建 + 安装到 /tmp/ogs（见 MULTI_CORE_SETUP.md）。
set -e
cd "$(dirname "$0")"

ROOT="$(cd .. && pwd)"
OGS="$ROOT/open5gs"
UERANSIM="$ROOT/UERANSIM_CoreTesting"
OGS_INSTALL="/tmp/ogs"

# 1. 把 5gc 启动器 + NF 二进制 + UERANSIM 加入 PATH
export PATH="$OGS_INSTALL/bin:$OGS/build/tests/app:$UERANSIM/build:$PATH"

# 2. 环境变量（覆盖 .env 里的 Docker 路径 /corefuzzer_deps/*）
export OPEN5GS_PATH="$OGS"
export UERANSIM_PATH="$UERANSIM"
export CORE="${CORE:-open5gs}"

# 3. 故障注入（按需取消注释，用于 Φ 触发 / O1 崩溃实验）
# export OGS_FAULT_ACCEPT_PLAINTEXT_SERVICE_REQUEST=1
# export OGS_FAULT_ACCEPT_PLAINTEXT_REGISTRATION=1
# export OGS_FAULT_CRASH_TMSI=0xDEADBEEF

echo "本地运行 ProbeFuzzer：core=$CORE"
echo "  OPEN5GS_PATH=$OPEN5GS_PATH"
echo "  UERANSIM_PATH=$UERANSIM_PATH"
echo "  OGS_INSTALL=$OGS_INSTALL"

# 4. 跑 fuzzer
exec python3 core_fuzzer_dueling.py "$@"
