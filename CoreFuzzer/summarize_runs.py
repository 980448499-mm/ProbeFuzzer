#!/usr/bin/env python3
"""汇总 N 次主 campaign run 的最终指标，算 mean ± std / 95% CI。

用法:
    python3 summarize_runs.py <runs_dir>

<runs_dir> 下每个子目录（seed1/, seed2/, ...）是一次 run 的输出，包含:
    savedFSM_rl_dueling.json    —— FSM（状态/路径/执行次数）
    crash_reports/              —— confirmed/false_positives 的崩溃 JSON
    fuzzing.log                 —— 进度报告（状态覆盖/转换/崩溃/违规）

对每个指标提取 N 个最终值，输出 mean ± std 与 95% t 置信区间。
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import math
from typing import Dict, List, Optional


# t 分布 95% 双侧临界值（N-1 自由度），N>30 用 1.96
T_TABLE = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def t_critical(df: int) -> float:
    return T_TABLE.get(df, 1.96)


def mean_std_ci(vals: List[float]) -> Dict:
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci_low": None, "ci_high": None}
    mean = sum(vals) / n
    if n < 2:
        return {"n": n, "mean": mean, "std": 0.0, "ci_low": mean, "ci_high": mean}
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    std = math.sqrt(var)
    t = t_critical(n - 1)
    half = t * std / math.sqrt(n)
    return {"n": n, "mean": mean, "std": std,
            "ci_low": mean - half, "ci_high": mean + half}


def extract_fsm(rundir: str) -> Dict:
    """从 savedFSM_rl_dueling.json 提取 唯一状态/唯一边/执行次数。"""
    out = {"unique_states": None, "unique_edges": None, "executions": None}
    p = os.path.join(rundir, "savedFSM_rl_dueling.json")
    if not os.path.exists(p):
        return out
    try:
        d = json.load(open(p))
    except Exception:
        return out
    states = d.get("states", [])
    out["unique_states"] = len(states)
    edges = {}
    for st in states:
        for path in st.get("paths", []):
            ps = path.get("path_states", [])
            ins = path.get("input_symbols", [])
            sc = path.get("success_count", 0) or 0
            for i in range(len(ins)):
                e = (ps[i], ins[i], ps[i + 1])
                edges[e] = edges.get(e, 0) + sc
    out["unique_edges"] = sum(1 for c in edges.values() if c > 0)
    out["executions"] = sum(edges.values())
    return out


def extract_crashes(rundir: str) -> Dict:
    """从 crash_reports/confirmed 提取 timeout 数与 HANG 簇数。"""
    out = {"timeouts": None, "hang_clusters": None, "real_crashes": None}
    cdir = os.path.join(rundir, "crash_reports", "confirmed")
    if not os.path.isdir(cdir):
        return out
    timeouts = 0
    real = 0
    send_types = set()
    for fn in os.listdir(cdir):
        if not fn.endswith(".json"):
            continue
        try:
            cr = json.load(open(os.path.join(cdir, fn)))
        except Exception:
            continue
        ctype = cr.get("crash_type")
        if ctype == "timeout":
            timeouts += 1
            inp = cr.get("input_data") or {}
            st = inp.get("send_type") or inp.get("send_type_inferred") or "?"
            send_types.add(st)
        elif ctype == "real_crash":
            real += 1
    out["timeouts"] = timeouts
    out["hang_clusters"] = len(send_types)
    out["real_crashes"] = real
    return out


def _last_match(log_text: str, pattern: str) -> Optional[float]:
    ms = re.findall(pattern, log_text)
    if not ms:
        return None
    try:
        return float(ms[-1])
    except ValueError:
        return None


def extract_log(rundir: str) -> Dict:
    """从 fuzzing.log 末次进度提取 状态覆盖/转换/崩溃/无反馈。"""
    out = {"state_coverage": None, "transitions": None,
           "crashes": None, "no_feedback": None}
    p = os.path.join(rundir, "fuzzing.log")
    if not os.path.exists(p):
        return out
    try:
        txt = open(p, encoding="utf-8", errors="ignore").read()
    except Exception:
        return out
    cov = _last_match(txt, r"状态覆盖:\s*(\d+)/\d+")
    if cov is not None:
        total = _last_match(txt, r"状态覆盖:\s*\d+/(\d+)")
        out["state_coverage"] = (cov / total * 100.0) if total else None
    out["transitions"] = _last_match(txt, r"转换探索:\s*(\d+)条")
    out["crashes"] = _last_match(txt, r"系统崩溃:\s*(\d+)")
    out["no_feedback"] = _last_match(txt, r"无反馈:\s*(\d+)")
    return out


def extract_pv_phi(rundir: str) -> Dict:
    """统计 wire-faithful Φ 命中数（wire_phi_hits.csv 的数据行数，不含表头）。

    只读汇总文件 wire_phi_hits.csv：append_wire_phi_hit 会把同一次命中同时写进
    wire_phi_hits_{component}.csv 和 wire_phi_hits.csv，若全部统计会重复计数。
    """
    pv = 0
    p = os.path.join(rundir, "wire_phi_hits.csv")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                pv = sum(1 for _ in csv.DictReader(f))
        except Exception:
            pass
    return {"pv_phi": pv}


def extract_run(rundir: str) -> Dict:
    m = {}
    m.update(extract_fsm(rundir))
    m.update(extract_crashes(rundir))
    m.update(extract_log(rundir))
    m.update(extract_pv_phi(rundir))

    crashes = m.get("crashes")          # O₁ 判为崩溃（REAL_CRASH + TIMEOUT）
    real = m.get("real_crashes")        # 真崩溃（TC）
    nofb = m.get("no_feedback")         # 无响应事件总数（O₀ 的崩溃候选）

    # 标准混淆矩阵指标（对 O₁ 分类器，ground truth = 是否真崩溃）
    #   FP = crashes - real          （非崩溃被判成崩溃）
    #   TN = nofb - crashes          （非崩溃被判成非崩溃）
    #   TP = real                    （真崩溃被判成崩溃）
    m["fp"] = (crashes - real) if (crashes is not None and real is not None) else None
    m["tn"] = (nofb - crashes) if (nofb is not None and crashes is not None) else None

    # FDR（假发现率）= FP / (FP + TP) = (crashes - real) / crashes
    if crashes is not None and real is not None and crashes > 0:
        m["fdr"] = (crashes - real) / crashes
    else:
        m["fdr"] = None

    # 标准 FPR = FP / (FP + TN) = (crashes - real) / (nofb - real)
    if (crashes is not None and real is not None and nofb is not None
            and nofb - real > 0):
        m["fpr"] = (crashes - real) / (nofb - real)
    else:
        m["fpr"] = None
    return m


def main() -> None:
    runs_dir = sys.argv[1] if len(sys.argv) > 1 else "campaign_runs"
    subdirs = sorted(
        d for d in os.listdir(runs_dir)
        if os.path.isdir(os.path.join(runs_dir, d)) and d.startswith("seed")
    )
    if not subdirs:
        print(f"未找到 seed 子目录于 {runs_dir}")
        sys.exit(1)

    print(f"读取 {len(subdirs)} 次 run ...")
    rows: List[Dict] = []
    for d in subdirs:
        m = extract_run(os.path.join(runs_dir, d))
        m["run"] = d
        rows.append(m)

    # 打印每 run 明细
    print("\n每 run 明细:")
    cols = ["run", "unique_states", "unique_edges", "executions",
            "timeouts", "hang_clusters", "real_crashes", "pv_phi",
            "state_coverage", "transitions", "crashes",
            "no_feedback", "fp", "tn", "fdr", "fpr"]
    hdr = "  ".join(f"{c:>14}" for c in cols)
    print(hdr)
    for m in rows:
        line = "  ".join(
            f"{str(m.get(c)):>14}" if m.get(c) is not None else f"{'-':>14}"
            for c in cols
        )
        print(line)

    # 汇总每个数值指标
    print("\n" + "=" * 72)
    print("mean ± std / 95% CI (t 分布)")
    print("=" * 72)
    numeric_cols = ["unique_states", "unique_edges", "executions",
                    "timeouts", "hang_clusters", "real_crashes", "pv_phi",
                    "state_coverage", "transitions", "crashes",
                    "no_feedback", "fp", "tn", "fdr", "fpr"]
    for c in numeric_cols:
        vals = [m[c] for m in rows if m.get(c) is not None]
        if not vals:
            continue
        s = mean_std_ci(vals)
        if s["std"] == 0.0:
            print(f"  {c:16s} = {s['mean']:.2f} (确定性, std=0, n={s['n']})")
        else:
            print(f"  {c:16s} = {s['mean']:.2f} ± {s['std']:.2f}  "
                  f"95% CI [{s['ci_low']:.2f}, {s['ci_high']:.2f}]  (n={s['n']})")

    # 输出 JSON 供后续使用
    out_json = os.path.join(runs_dir, "summary.json")
    summary = {}
    for c in numeric_cols:
        vals = [m[c] for m in rows if m.get(c) is not None]
        if vals:
            summary[c] = mean_std_ci(vals)
    summary["runs"] = [m["run"] for m in rows]
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n汇总已保存到 {out_json}")


if __name__ == "__main__":
    main()
