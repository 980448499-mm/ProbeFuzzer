#!/bin/bash
# 跑 N 次主 campaign（Dueling DQN，不同随机种子），每次输出到独立目录，最后汇总 mean ± std / CI。
#
# 用法（在容器 /corefuzzer 内执行）:
#   ./run_multi_seed.sh [N=5] [ITERATION_LIMIT=500]
#
# 关键环境变量（每次 run 相同）:
#   USE_RL=true  USE_DUELING=true   —— 复现论文的 Dueling DQN 配置
#   FSM_LOAD_MODE=fresh             —— 每次独立起跑，不加载上次 FSM
#   SEED=$seed                      —— 可复现的随机种子
set -o pipefail
cd "$(dirname "$0")"

N="${1:-5}"
ITER="${2:-500}"
OUTDIR="campaign_runs"
mkdir -p "$OUTDIR"

echo "多 seed 跑批: N=$N ITERATION_LIMIT=$ITER OUTDIR=$OUTDIR"

for seed in $(seq 1 "$N"); do
    echo ""
    echo "=============================================="
    echo "  Run $seed/$N  (SEED=$seed, ITER=$ITER)"
    echo "=============================================="
    rundir="$OUTDIR/seed$seed"
    rm -rf "$rundir"
    mkdir -p "$rundir"

    # 清理本次 run 会重新生成的产物（不删 savedFSM*，FSM_LOAD_MODE=fresh 本就忽略它）
    rm -f phi_violations_*.csv wire_phi_hits*.csv typed_responses.csv
    rm -rf crash_reports

    if USE_RL=true USE_DUELING=true \
       SEED="$seed" ITERATION_LIMIT="$ITER" FSM_LOAD_MODE=fresh \
       python3 -u core_fuzzer_dueling.py 2>&1 | tee "$rundir/fuzzing.log"; then
        echo "  ✅ run $seed 完成"
    else
        echo "  ❌ run $seed 失败（见 $rundir/fuzzing.log），继续下一个"
    fi

    # 把产物搬进本 run 目录（无论成功失败都搬，失败也能看到部分产物）
    for f in savedFSM*.json rl_stats_dueling.json rl_model_dueling.pth; do
        [ -f "$f" ] && mv "$f" "$rundir/"
    done
    if [ -d crash_reports ]; then
        mv crash_reports "$rundir/crash_reports"
    fi
    for f in phi_violations_*.csv wire_phi_hits*.csv typed_responses.csv; do
        [ -f "$f" ] && mv "$f" "$rundir/"
    done
done

echo ""
echo "=============================================="
echo "  汇总 mean ± std / 95% CI"
echo "=============================================="
python3 summarize_runs.py "$OUTDIR"
