# -*- coding: utf-8 -*-
"""图9 孙光荣三联药组与核心用药共现网络（基于医案处方，290 首）。"""
import itertools
import math
from collections import Counter

import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path

import data as G
from style import INK, INK2, INK3, GRID, ACCENT, SEQ, MUTED, W_DOUBLE, CM, panel_label, save

COMM_COLOR = ["#2a78d6", "#eb6834", "#1baf7a", "#7B4AA5"]   # 已通过全对色盲校验
TOP_HERBS = 32
CORE = ("生黄芪", "紫丹参")
SHEN = ("生晒参", "西洋参", "西党参", "太子参", "潞党参")


def herb_stats():
    P = G.prescription_herbs()
    n = len(P)
    hc = Counter(h for s in P.values() for h in s)
    top = [h for h, _ in hc.most_common(TOP_HERBS)]
    co = Counter()
    for s in P.values():
        for a, b in itertools.combinations(sorted(s & set(top)), 2):
            co[(a, b)] += 1
    return P, n, hc, top, co


def communities(n, hc, co, min_co=12, min_lift=1.2):
    Gx = nx.Graph()
    for (a, b), c in co.items():
        lift = c * n / (hc[a] * hc[b])
        if c >= min_co and lift > min_lift and a not in CORE and b not in CORE:
            Gx.add_edge(a, b, weight=c, lift=lift)
    com = nx.community.louvain_communities(Gx, weight="weight", seed=7)
    com = sorted(com, key=lambda c: -sum(hc[h] for h in c))
    return Gx, com


def fig_herbs():
    P, n, hc, top, co = herb_stats()
    Gx, com = communities(n, hc, co)
    T = G.prescription_triplets()
    tc = Counter(t for s in T.values() for t in s)

    fig = plt.figure(figsize=(W_DOUBLE, 10.4 * CM))
    axA = fig.add_axes([0.205, 0.10, 0.25, 0.80])
    axB = fig.add_axes([0.50, 0.0, 0.50, 1.0])

    # ---- A：高频三联药组 ----
    trip = tc.most_common(15)
    y = np.arange(len(trip))
    is_core = [all(c in t for c in CORE) for t, _ in trip]
    axA.barh(y, [v for _, v in trip], height=0.68, color=[ACCENT if k else SEQ for k in is_core],
             edgecolor="white", linewidth=0.4)
    axA.set_yticks(y, [t.replace("+", "·") for t, _ in trip], fontsize=6.5)
    axA.invert_yaxis()
    for yy, (_, v) in zip(y, trip):
        axA.text(v + 1.5, yy, f"{v}（{v/n:.0%}）", va="center", fontsize=6.0, color=INK2)
    axA.set_xlim(0, 140)
    axA.set_xlabel(f"含该药组的处方数 / 首（N={n}）")
    axA.spines["left"].set_visible(False)
    axA.tick_params(axis="y", length=0)
    axA.grid(axis="x", color=GRID, lw=0.5)
    axA.set_axisbelow(True)
    from matplotlib.patches import Patch
    axA.legend(handles=[Patch(fc=ACCENT, label="参·芪·丹 益气活血基础药组"), Patch(fc=SEQ, label="其他三联药组")],
               loc="lower right", fontsize=6.4, handlelength=1.0, handleheight=0.8)
    panel_label(axA, "A", x=-0.80, y=1.01)

    # ---- B：环形共现网络 ----
    ax = axB
    ax.set_xlim(-1.62, 1.62); ax.set_ylim(-1.98, 1.50); ax.set_aspect("equal"); ax.axis("off")
    order, gaps = [], []
    for ci, c in enumerate(com):
        for h in sorted(c, key=lambda h: -hc[h]):
            order.append((h, ci))
        gaps.append(len(order))
    m = len(order)
    gap = 0.9                         # 社团之间留空（以节点间距为单位）
    slots = m + gap * len(com)
    ang, k = {}, 0.0
    for idx, (h, ci) in enumerate(order):
        ang[h] = math.pi / 2 - 2 * math.pi * (k / slots)
        k += 1
        if idx + 1 in gaps:
            k += gap
    R = 1.0
    pos = {h: (R * math.cos(a), R * math.sin(a)) for h, a in ang.items()}
    comm_of = {h: ci for h, ci in order}

    wmax = max(d["weight"] for _, _, d in Gx.edges(data=True))
    for a, b, d in sorted(Gx.edges(data=True), key=lambda e: e[2]["weight"]):
        p0, p2 = np.array(pos[a]), np.array(pos[b])
        mid = (p0 + p2) / 2
        p1 = mid * 0.25                                   # 向圆心弯曲
        same = comm_of[a] == comm_of[b]
        col = COMM_COLOR[comm_of[a]] if same else "#9A9488"
        ax.add_patch(PathPatch(Path([p0, p1, p2], [Path.MOVETO, Path.CURVE3, Path.CURVE3]), fc="none",
                               ec=col, lw=0.3 + 1.8 * d["weight"] / wmax, alpha=0.55 if same else 0.35, zorder=1))
    fmax = max(hc[h] for h, _ in order)
    for h, ci in order:
        x, y0 = pos[h]
        r = 0.028 + 0.055 * math.sqrt(hc[h] / fmax)
        ax.add_patch(Circle((x, y0), r, fc=COMM_COLOR[ci], ec="white", lw=0.8, zorder=3))
        a = ang[h]
        lx, ly = (R + r + 0.05) * math.cos(a), (R + r + 0.05) * math.sin(a)
        deg = math.degrees(a)
        left = math.cos(a) < 0
        ax.text(lx, ly, f"{h} {hc[h]}", fontsize=6.4, color=INK, ha="right" if left else "left", va="center",
                rotation=deg + 180 if left else deg, rotation_mode="anchor", zorder=4)
    # 核心药对置于圆心
    ax.add_patch(Circle((0, 0), 0.34, fc="#FBEDEA", ec=ACCENT, lw=0.8, zorder=2))
    ax.text(0, 0.11, "核心药对", ha="center", va="center", fontsize=6.2, color=INK2, zorder=4)
    ax.text(0, -0.01, "生黄芪·紫丹参", ha="center", va="center", fontsize=6.6, color=INK, weight="bold", zorder=4)
    ax.text(0, -0.13, f"{hc[CORE[0]]/n:.0%} / {hc[CORE[1]]/n:.0%} 处方", ha="center", va="center",
            fontsize=6.0, color=INK2, zorder=4)
    # 社团图例
    names = []
    for ci, c in enumerate(com):
        tops = "·".join(sorted(c, key=lambda h: -hc[h])[:3])
        names.append((ci, f"社团{'ⅠⅡⅢⅣⅤ'[ci]}  {tops} 等 {len(c)} 味"))
    for j, (ci, s) in enumerate(names):
        yy = -1.30 - 0.0 * j
        xx = -1.55 + (j % 2) * 1.62
        yy = -1.74 - (j // 2) * 0.15
        ax.add_patch(Circle((xx, yy), 0.035, fc=COMM_COLOR[ci], ec="none"))
        ax.text(xx + 0.07, yy, s, fontsize=6.2, color=INK2, va="center")
    ax.text(-1.58, 1.50, "B", fontsize=10, fontweight="bold", ha="left", va="top", family=["Liberation Sans"])
    save(fig, "图9_三联药组与核心用药网络")
    return com


if __name__ == "__main__":
    import style
    style.setup()
    print(fig_herbs())
