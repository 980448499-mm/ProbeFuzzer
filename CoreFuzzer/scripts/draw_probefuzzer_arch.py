#!/usr/bin/env python3
"""Draw revised ProbeFuzzer architecture (§5 / §7.5). Outputs SVG + PNG."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = Path(__file__).resolve().parent.parent / "figures"


def box(ax, xy, wh, text, fc, fontsize=8):
    x, y = xy
    w, h = wh
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.03,rounding_size=0.12",
        facecolor=fc,
        edgecolor="#333333",
        linewidth=1.0,
    )
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize)


def arrow(ax, p1, p2, text=None, color="#555555"):
    a = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.0,
        color=color,
        connectionstyle="arc3,rad=0",
    )
    ax.add_patch(a)
    if text:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my + 0.15, text, ha="center", fontsize=7, color="#c62828")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 9), dpi=150)
    ax.set_xlim(-0.5, 12.5)
    ax.set_ylim(-3.2, 10.8)
    ax.axis("off")
    ax.set_title("ProbeFuzzer 总体架构（修订：O₁/Ψ 与 Φ 分支）", fontsize=12, pad=12)

    # --- Left: FSM (blue tone) ---
    box(ax, (0.2, 8.0), (2.3, 0.7), "3GPP 参考\n或规则", "#b3d9ff")
    box(ax, (0.2, 6.9), (2.3, 0.7), "5G 信息流\n学习", "#b3d9ff")
    box(ax, (0.15, 5.6), (2.4, 0.85), "FSM 构建\n/ 加载", "#7ec8e3")
    arrow(ax, (1.35, 8.0), (1.35, 7.6))
    arrow(ax, (1.35, 6.9), (1.35, 6.45))

    # Pool
    box(ax, (3.5, 6.5), (2.8, 1.2), "FSM 状态与\n持久化 (MongoDB)", "#a5d6a7")

    arrow(ax, (2.55, 6.0), (3.5, 7.1))
    arrow(ax, (6.3, 7.1), (7.0, 8.3))

    # Scheduler + pipeline (yellow tone)
    box(ax, (7.0, 8.2), (2.2, 0.65), "调度器", "#fff59d")
    box(ax, (6.65, 7.25), (1.05, 0.55), "Dueling\nDQN(可选)", "#ffe082")
    box(ax, (8.5, 7.25), (1.05, 0.55), "PowerSchedule\n基线", "#ffe082")
    arrow(ax, (8.1, 8.2), (7.35, 7.8))
    arrow(ax, (8.1, 8.2), (8.85, 7.8))

    box(ax, (7.0, 6.35), (2.2, 0.55), "下一抽象状态", "#fff9c4")
    arrow(ax, (7.35, 7.25), (7.8, 6.9))
    arrow(ax, (8.85, 7.25), (8.4, 6.9))

    box(ax, (7.0, 5.55), (2.2, 0.5), "序列生成", "#fff59d")
    box(ax, (7.0, 4.75), (2.2, 0.6), "NAS 变异\n(UERANSIM §5.4)", "#ffecb3")
    box(ax, (7.0, 3.95), (2.2, 0.5), "发送与测试执行", "#fff59d")
    box(ax, (7.0, 2.95), (2.2, 0.75), "5G 核心网\n(Open5GS)", "#b3e5fc")

    for y0, y1 in [(6.35, 6.05), (5.55, 5.25), (4.75, 4.45), (3.95, 3.7)]:
        arrow(ax, (8.1, y0), (8.1, y1))

    # Feedback
    box(ax, (4.0, 2.05), (2.4, 0.55), "反馈解析", "#f8bbd9")
    arrow(ax, (7.0, 3.2), (5.2, 2.35))

    # Branch
    box(ax, (4.35, 1.0), (1.7, 0.65), "合法 NAS\n响应?", "#f48fb1")
    arrow(ax, (5.2, 2.05), (5.2, 1.65))

    # O1 vs Phi (red tone)
    box(ax, (0.8, 0.05), (2.0, 0.75), "O1 + Psi\n(沉默·表1)", "#ef9a9a")
    box(ax, (7.5, 0.05), (2.0, 0.75), "Oracle Φ\n(§5.2)", "#ef9a9a")

    arrow(ax, (4.35, 1.15), (2.3, 0.55), "否/超时")
    arrow(ax, (6.05, 1.15), (8.0, 0.55), "是")

    box(ax, (0.5, -0.95), (2.6, 0.55), "REAL_CRASH 等", "#ffccbc")
    box(ax, (7.2, -0.95), (2.6, 0.55), "PROTOCOL_\nVIOLATION", "#ffccbc")
    arrow(ax, (1.8, 0.05), (1.8, -0.4))
    arrow(ax, (8.5, 0.05), (8.5, -0.4))

    box(ax, (2.8, -1.85), (5.4, 0.55), "持久化 (test_result 等)", "#e0e0e0")
    arrow(ax, (1.8, -0.95), (4.2, -1.3))
    arrow(ax, (8.5, -0.95), (6.8, -1.3))

    box(ax, (3.5, -2.75), (4.0, 0.55), "标签对齐\n分层奖励 (§5.3)", "#d1c4e9")
    arrow(ax, (5.5, -1.85), (5.5, -2.2))

    # Reward -> Pool (curved)
    a = FancyArrowPatch(
        (5.5, -2.45),
        (4.2, 7.0),
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.0,
        color="#6a1b9a",
        connectionstyle="arc3,rad=0.25",
    )
    ax.add_patch(a)
    ax.text(1.2, 2.5, "闭环更新", fontsize=8, color="#6a1b9a")

    plt.tight_layout()
    svg = OUT_DIR / "ProbeFuzzer_architecture_revised.svg"
    png = OUT_DIR / "ProbeFuzzer_architecture_revised.png"
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    plt.close()
    print(svg)
    print(png)


if __name__ == "__main__":
    main()
