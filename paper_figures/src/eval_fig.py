# -*- coding: utf-8 -*-
"""图12 检索实验结果（读取 retrieval_eval.json，先运行 retrieval_eval.py）。"""
import json
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from style import INK, INK2, INK3, GRID, W_DOUBLE, CM, OUT, panel_label, save
from retrieval_eval import REL_ZH_SHORT, TEMPLATES

MCOL = {"M1": "#1baf7a", "M2": "#7B4AA5", "M3": "#2a78d6", "M4": "#D9961A", "M5": "#B8322A"}
MMK = {"M1": "s", "M2": "D", "M3": "^", "M4": "v", "M5": "o"}
MNAME = {"M1": "M1 文本块BM25", "M2": "M2 佐证句BM25", "M3": "M3 实体+一跳",
         "M4": "M4 本文(无轮转)", "M5": "M5 本文(完整)"}


def fig_eval():
    R = json.load(open(os.path.join(OUT, "tables", "retrieval_eval.json"), encoding="utf-8"))
    T, O = R["template"], R["open"]
    fig = plt.figure(figsize=(W_DOUBLE, 13.0 * CM))
    axA = fig.add_axes([0.065, 0.585, 0.38, 0.37])
    axB = fig.add_axes([0.615, 0.585, 0.25, 0.37])
    axC = fig.add_axes([0.065, 0.085, 0.38, 0.36])
    axD = fig.add_axes([0.555, 0.085, 0.43, 0.36])

    # ---- A：Hit@k 曲线 ----
    ks = [1, 3, 5, 10, 20, 30, 50, 80, 120]
    same45 = all(abs(T["M4"][f"hit@{k}"] - T["M5"][f"hit@{k}"]) < 1e-9 for k in ks)
    for m in ("M1", "M2", "M3", "M4", "M5"):
        if m == "M4" and same45:
            continue
        ys = [T[m][f"hit@{k}"] for k in ks]
        axA.plot(ks, ys, color=MCOL[m], lw=1.6 if m == "M5" else 1.1, marker=MMK[m], ms=3.6,
                 mec="white", mew=0.5, zorder=4 if m == "M5" else 3)
        lab = MNAME[m] + ("/M4" if m == "M5" and same45 else "")
        axA.text(128, {"M1": ys[-1], "M2": 0.985, "M3": 0.93, "M5": 1.04}[m], lab.split(" ")[0] +
                 ("/M4" if m == "M5" and same45 else ""), fontsize=6.4, color=MCOL[m], va="center")
    axA.set_xscale("log")
    axA.set_xticks(ks, [str(k) for k in ks])
    axA.minorticks_off()
    axA.set_xlim(0.85, 170)
    axA.set_ylim(0, 1.04)
    axA.set_xlabel("k（前 k 条关系）")
    axA.set_ylabel("Hit@k")
    axA.grid(color=GRID, lw=0.5)
    axA.set_axisbelow(True)
    axA.text(0.98, 0.04, f"模板问答 n={R['n_template']}（12 类关系 × ≤20 问）", transform=axA.transAxes,
             ha="right", fontsize=6.2, color=INK3)
    panel_label(axA, "A", x=-0.08, y=1.02)

    # ---- B：分关系类型 Hit@10 热图 ----
    rels = list(TEMPLATES)
    ms = ["M1", "M2", "M3", "M5"]
    mat = np.array([[R["template_by_rel"][m][r] for m in ms] for r in rels])
    im = axB.imshow(mat, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(len(rels)):
        for j in range(len(ms)):
            v = mat[i, j]
            axB.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.8,
                     color="white" if v > 0.62 else INK)
    axB.set_xticks(range(len(ms)), [m if m != "M5" else "M5\n(=M4)" for m in ms], fontsize=6.4)
    axB.set_yticks(range(len(rels)), [REL_ZH_SHORT[r] for r in rels], fontsize=6.4)
    axB.tick_params(length=0)
    for s in axB.spines.values():
        s.set_visible(False)
    axB.xaxis.tick_top()
    cb = fig.colorbar(im, ax=axB, fraction=0.06, pad=0.03)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=6, length=2)
    cb.set_label("Hit@10", fontsize=6.6)
    panel_label(axB, "B", x=-0.42, y=1.10)

    # ---- C：开放问题——最大关系类型占比分布（越低越均衡） ----
    order = ["M1", "M2", "M3", "M4", "M5"]
    data = [O[m]["120"]["max_share_list"] for m in order]
    bp = axC.boxplot(data, positions=range(len(order)), widths=0.5, patch_artist=True, showfliers=False,
                     medianprops=dict(color=INK, lw=0.9), whiskerprops=dict(color=INK3, lw=0.6),
                     capprops=dict(color=INK3, lw=0.6), boxprops=dict(lw=0.6))
    for patch, m in zip(bp["boxes"], order):
        patch.set_facecolor(MCOL[m]); patch.set_alpha(0.28); patch.set_edgecolor(MCOL[m])
    rng = np.random.default_rng(3)
    for j, (m, d) in enumerate(zip(order, data)):
        axC.scatter(j + rng.uniform(-0.14, 0.14, len(d)), d, s=6, color=MCOL[m], edgecolor="white",
                    linewidth=0.3, zorder=3)
        axC.text(j, 0.98, f"均值 {np.mean(d):.2f}", ha="center", fontsize=6.0, color=INK2)
    axC.set_xticks(range(len(order)), [MNAME[m].replace(" ", "\n", 1) for m in order], fontsize=6.4)
    axC.set_ylim(0, 1.06)
    axC.set_ylabel("单一关系类型最大占比")
    axC.grid(axis="y", color=GRID, lw=0.5)
    axC.set_axisbelow(True)
    axC.text(1.0, 1.03, f"开放问题 n={R['n_open']}，K=120；越低表示关系侧面越均衡", fontsize=6.2,
             color=INK3, ha="right", transform=axC.transAxes)
    panel_label(axC, "C", x=-0.08, y=1.02)

    # ---- D：开放问题——证据与覆盖指标（均为 0–1） ----
    metrics = [("entropy", "关系类型\n归一化熵"), ("substantive", "实质佐证\n占比(≥10字)"),
               ("sun_original", "孙光荣原创\n占比")]
    w = 0.16
    x = np.arange(len(metrics))
    for j, m in enumerate(order):
        vals = [O[m]["120"][k] for k, _ in metrics]
        axD.bar(x + (j - 2) * w, vals, width=w * 0.92, color=MCOL[m], edgecolor="white", linewidth=0.4,
                label=MNAME[m])
        for xx, v in zip(x + (j - 2) * w, vals):
            axD.text(xx, v + 0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=5.5, color=INK2, rotation=90)
    axD.set_xticks(x, [n for _, n in metrics], fontsize=6.6)
    axD.set_ylim(0, 1.12)
    axD.set_ylabel("比例 / 归一化值")
    axD.grid(axis="y", color=GRID, lw=0.5)
    axD.set_axisbelow(True)
    axD.legend(loc="upper center", bbox_to_anchor=(0.5, 1.17), ncol=3, fontsize=6.0, handlelength=1.0,
               handleheight=0.8, columnspacing=0.8)
    types = " · ".join(f"{m} {O[m]['120']['types']:.1f}" for m in order)
    axD.text(0.0, -0.30, f"平均关系类型数（K=120）：{types}", transform=axD.transAxes, fontsize=6.0,
             color=INK3, ha="left")
    panel_label(axD, "D", x=-0.10, y=1.02)
    save(fig, "图12_检索实验结果")


if __name__ == "__main__":
    import style
    style.setup()
    fig_eval()
