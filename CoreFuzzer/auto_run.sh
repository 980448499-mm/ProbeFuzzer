#!/bin/bash
# 在 CoreFuzzer 目录下执行（本机或 Docker 内 /corefuzzer 均可）
# 用法: ./auto_run.sh [迭代次数] [占位符可忽略] [latest|fresh]
# 示例: ./auto_run.sh 1000 "" fresh
set -e
cd "$(dirname "$0")"
# Docker 挂载本机代码时，镜像里的 pip 依赖可能缺失或与当前 requirements 不一致
if ! python3 -c "import numpy, torch" 2>/dev/null; then
  echo "[auto_run] 缺少 Python 依赖，正在: pip3 install -r requirements.txt"
  pip3 install -r requirements.txt
fi
export ITERATION_LIMIT="${1:-500}"
export FSM_LOAD_MODE="${3:-latest}"
if [[ -d /corefuzzer_deps/open5gs/.git ]]; then
  echo "[auto_run] Open5GS $(git -C /corefuzzer_deps/open5gs describe --tags --exact-match 2>/dev/null || echo unknown)"
fi
exec python3 core_fuzzer_dueling.py
