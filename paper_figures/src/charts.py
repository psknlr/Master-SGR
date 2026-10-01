# -*- coding: utf-8 -*-
"""统计类图表：图3 实体/关系分布、图4 知识来源、图5 质量评估、图6 网络拓扑。"""
import math
from collections import Counter

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import data as G
from style import (INK, INK2, INK3, GRID, ACCENT, SEQ, MUTED, ROLE_ORDER, ROLE_ZH, ROLE_COLOR,
                   W_DOUBLE, CM, SANS, panel_label, save)


def thin(n):
    return f"{int(n):,}".replace(",", " ")


THOUSANDS = FuncFormatter(lambda v, _: thin(v))
ZH_CHAIN = {"THOUGHT_HAS_PRINCIPLE", "PRINCIPLE_GUIDES_METHOD", "REALIZED_BY_TRIPLET",
            "MAXIM_EXPRESSES", "DERIVED_FROM"}


def _hbar_axes(ax):
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.grid(axis="x", color=GRID, lw=0.5)
    ax.set_axisbelow(True)


# ======================================================================== 图3
def fig_type_distribution():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    tc = Counter(n["t"] for n in N)
    rc = Counter(e["y"] for e in E)
    type_zh = {k: v["zh"] for k, v in D["types"].items()}
    rel_zh = {k: v["zh"] for k, v in D["rels"].items()}

    fig = plt.figure(figsize=(W_DOUBLE, 13.2 * CM))
    axA = fig.add_axes([0.13, 0.06, 0.33, 0.90])
    axB = fig.add_axes([0.63, 0.06, 0.35, 0.90])

    # ---- A：按本体模块分组的实体类型 ----
    ys, labels, vals, groups = [], [], [], []
    y = 0
    for mod, types in G.MODULES:
        ts = sorted([t for t in types if tc.get(t, 0) > 0], key=lambda t: -tc[t])
        start = y
        for t in ts:
            ys.append(y); labels.append(type_zh[t]); vals.append(tc[t]); y += 1
        groups.append((mod, start, y - 1, sum(tc[t] for t in ts)))
        y += 0.9
    ys = np.array(ys)
    colors = [ACCENT if l in ("中和思想", "治则", "三联药组") else SEQ for l in labels]
    axA.barh(ys, vals, height=0.72, color=colors, edgecolor="white", linewidth=0.4)
    axA.set_yticks(ys, labels)
    axA.invert_yaxis()
    for yy, v in zip(ys, vals):
        axA.text(v + 40, yy, thin(v), va="center", fontsize=6.4, color=INK2)
    for mod, a, b, tot in groups:
        axA.annotate("", xy=(-0.30, a - 0.35), xytext=(-0.30, b + 0.35), xycoords=("axes fraction", "data"),
                     arrowprops=dict(arrowstyle="-", color=INK3, lw=0.6))
        axA.text(-0.33, (a + b) / 2, f"{mod}\n{thin(tot)}", transform=axA.get_yaxis_transform(),
                 ha="right", va="center", fontsize=6.6, color=INK, linespacing=1.15)
    axA.set_xlim(0, 2950)
    axA.set_xlabel("实体数 / 个")
    _hbar_axes(axA)
    panel_label(axA, "A", x=-0.42, y=1.0)

    # ---- B：44 类关系 ----
    rs = sorted(rc, key=lambda r: -rc[r])
    yb = np.arange(len(rs))
    colB = [ACCENT if r in ZH_CHAIN else SEQ for r in rs]
    axB.barh(yb, [rc[r] for r in rs], height=0.72, color=colB, edgecolor="white", linewidth=0.4)
    axB.set_yticks(yb, [rel_zh[r] for r in rs], fontsize=6.6)
    axB.invert_yaxis()
    for yy, r in zip(yb, rs):
        axB.text(rc[r] + 40, yy, thin(rc[r]), va="center", fontsize=6.0, color=INK2)
    axB.set_xlim(0, 3800)
    axB.set_xlabel("关系实例数 / 条")
    axB.set_ylim(len(rs) - 0.4, -0.6)
    _hbar_axes(axB)
    panel_label(axB, "B", x=-0.20, y=1.0)
    # 图例
    from matplotlib.patches import Patch
    axB.legend(handles=[Patch(fc=ACCENT, label="中和思想贯通链路相关"), Patch(fc=SEQ, label="其他类型")],
               loc="lower right", fontsize=6.6, handlelength=1.0, handleheight=0.8)
    save(fig, "图3_实体与关系类型分布")


# ======================================================================== 图4
def fig_source_distribution():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    docs = list(G.DOC_SHORT)
    fig = plt.figure(figsize=(W_DOUBLE, 8.6 * CM))
    axA = fig.add_axes([0.20, 0.17, 0.33, 0.74])
    axB = fig.add_axes([0.70, 0.17, 0.28, 0.74])

    # ---- A：各文献关系实例按知识来源堆叠 ----
    cnt = Counter((e["d"], e["r"]) for e in E)
    tot = Counter(e["d"] for e in E)
    order = sorted(docs, key=lambda d: -tot[d])
    y = np.arange(len(order))
    left = np.zeros(len(order))
    for r in ROLE_ORDER:
        v = np.array([cnt[(d, r)] for d in order])
        axA.barh(y, v, left=left, height=0.66, color=ROLE_COLOR[r], edgecolor="white", linewidth=0.6,
                 label=ROLE_ZH[r])
        left += v
    for yy, d in zip(y, order):
        axA.text(tot[d] + 80, yy, thin(tot[d]), va="center", fontsize=6.4, color=INK2)
    axA.set_yticks(y, [f"{d} {G.DOC_SHORT[d]}" for d in order], fontsize=6.8)
    axA.invert_yaxis()
    axA.set_xlim(0, 9500)
    axA.set_xlabel("关系实例数 / 条")
    _hbar_axes(axA)
    panel_label(axA, "A", x=-0.62, y=1.02)

    # ---- B：各本体模块实体的知识来源构成（百分比） ----
    mods = [m for m, _ in G.MODULES]
    mc = Counter((G.TYPE_MODULE[n["t"]], n["r"]) for n in N)
    mt = Counter(G.TYPE_MODULE[n["t"]] for n in N)
    yb = np.arange(len(mods))
    left = np.zeros(len(mods))
    for r in ROLE_ORDER:
        v = np.array([mc[(m, r)] / mt[m] * 100 for m in mods])
        axB.barh(yb, v, left=left, height=0.66, color=ROLE_COLOR[r], edgecolor="white", linewidth=0.6)
        for yy, (l, vv) in enumerate(zip(left, v)):
            if vv >= 9:
                axB.text(l + vv / 2, yy, f"{vv:.0f}", ha="center", va="center", fontsize=6.0,
                         color="white" if r != "sun_compiled" else INK)
        left += v
    axB.set_yticks(yb, [f"{m}" for m in mods], fontsize=6.8)
    axB.invert_yaxis()
    axB.set_xlim(0, 100)
    axB.set_xlabel("实体占比 / %")
    _hbar_axes(axB)
    axB.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
    panel_label(axB, "B", x=-0.36, y=1.02)

    h, l = axA.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=5, bbox_to_anchor=(0.55, -0.01), fontsize=7,
               handlelength=1.0, handleheight=0.8, columnspacing=1.4)
    save(fig, "图4_知识来源与文献分布")


# ======================================================================== 图5
def wilson(p, n, z=1.96):
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def fig_quality():
    D = G.load()
    E = D["edges"]
    au = D["meta"]["audit"]
    rel_zh = {k: v["zh"] for k, v in D["rels"].items()}

    fig = plt.figure(figsize=(W_DOUBLE, 7.4 * CM))
    axA = fig.add_axes([0.07, 0.17, 0.24, 0.72])
    axB = fig.add_axes([0.47, 0.17, 0.51, 0.72])

    # ---- A：抽样审校严格精度 + Wilson 95% CI ----
    rows = [("v1", au["v1_strict"], au["v1_n"]), ("v2", au["v2_strict"], au["v2_n"])]
    for i, (name, p, n) in enumerate(rows):
        lo, hi = wilson(p, n)
        axA.bar(i, p * 100, width=0.55, color=SEQ if name == "v2" else MUTED, edgecolor="white")
        axA.errorbar(i, p * 100, yerr=[[p * 100 - lo * 100], [hi * 100 - p * 100]], fmt="none",
                     ecolor=INK, elinewidth=0.7, capsize=2.5, capthick=0.7)
        axA.text(i, hi * 100 + 1.5, f"{p*100:.1f}%", ha="center", fontsize=7, color=INK)
        axA.text(i, 4, f"n={n}", ha="center", fontsize=6.4, color="white" if name == "v2" else INK)
    axA.set_xticks([0, 1], ["v1 图谱", "v2 图谱"])
    axA.set_ylim(0, 100)
    axA.set_ylabel("严格精度 / %")
    axA.grid(axis="y", color=GRID, lw=0.5)
    axA.set_axisbelow(True)
    panel_label(axA, "A", x=-0.18, y=1.03)

    # ---- B：本体一致性校验“待审”率（按关系类型，取实例数≥100 中的前 14 位） ----
    rc = Counter(e["y"] for e in E)
    qc = Counter(e["y"] for e in E if e["Q"])
    cand = [r for r in rc if rc[r] >= 100]
    top = sorted(cand, key=lambda r: -(qc[r] / rc[r]))[:14]
    x = np.arange(len(top))
    rate = [qc[r] / rc[r] * 100 for r in top]
    axB.bar(x, rate, width=0.62, color=SEQ, edgecolor="white")
    for xx, r, v in zip(x, top, rate):
        axB.text(xx, v + 0.4, f"{v:.1f}", ha="center", fontsize=6.0, color=INK2)
    axB.set_xticks(x, [rel_zh[r] for r in top], rotation=40, ha="right", rotation_mode="anchor", fontsize=6.6)
    overall = sum(qc.values()) / len(E) * 100
    axB.axhline(overall, color=ACCENT, lw=0.8, ls=(0, (3, 2)))
    axB.plot([0.70, 0.76], [0.86, 0.86], transform=axB.transAxes, color=ACCENT, lw=0.8, ls=(0, (3, 2)))
    axB.text(0.775, 0.86, f"全图平均 {overall:.1f}%（{sum(qc.values())}/{thin(len(E))}）",
             transform=axB.transAxes, ha="left", va="center", fontsize=6.4, color=ACCENT)
    axB.set_ylabel("“待审”关系占比 / %")
    axB.grid(axis="y", color=GRID, lw=0.5)
    axB.set_axisbelow(True)
    axB.set_xlim(-0.6, len(top) - 0.4)
    panel_label(axB, "B", x=-0.07, y=1.03)
    save(fig, "图5_知识质量评估")


# ======================================================================== 图6
def powerlaw_fit(deg):
    """离散幂律 MLE（Clauset 2009 近似），x_min 取使 KS 距离最小者。"""
    x = np.sort(np.asarray(deg, dtype=float))
    best = None
    for xmin in range(2, 30):
        tail = x[x >= xmin]
        if len(tail) < 50:
            break
        a = 1 + len(tail) / np.sum(np.log(tail / (xmin - 0.5)))
        emp = np.arange(len(tail), 0, -1) / len(tail)
        theo = (tail / xmin) ** (1 - a)
        ks = np.max(np.abs(emp - theo))
        if best is None or ks < best[2]:
            best = (xmin, a, ks, len(tail))
    return best


def fig_topology():
    import networkx as nx
    D = G.load()
    N, E = D["nodes"], D["edges"]
    deg = G.degree()
    dv = np.array([deg.get(i, 0) for i in range(len(N))])
    dv = dv[dv > 0]
    xmin, alpha, ks, ntail = powerlaw_fit(dv)

    Gx = nx.Graph()
    Gx.add_nodes_from(range(len(N)))
    Gx.add_edges_from((e["s"], e["t"]) for e in E)
    comps = sorted((len(c) for c in nx.connected_components(Gx)), reverse=True)

    fig = plt.figure(figsize=(W_DOUBLE, 7.8 * CM))
    axA = fig.add_axes([0.075, 0.16, 0.31, 0.76])
    axB = fig.add_axes([0.645, 0.16, 0.335, 0.76])

    # ---- A：度分布 CCDF（双对数） ----
    vals, counts = np.unique(dv, return_counts=True)
    ccdf = 1 - np.concatenate([[0], np.cumsum(counts)[:-1]]) / counts.sum()
    axA.scatter(vals, ccdf, s=7, color=SEQ, edgecolor="white", linewidth=0.3, zorder=3, label="观测值")
    xs = np.logspace(np.log10(xmin), np.log10(vals.max()), 50)
    p_tail = ntail / len(dv)
    axA.plot(xs, p_tail * (xs / xmin) ** (1 - alpha), color=ACCENT, lw=1.0, zorder=4,
             label=f"幂律拟合 α={alpha:.2f}")
    axA.set_xscale("log"); axA.set_yscale("log")
    axA.set_xlabel("度 k"); axA.set_ylabel("P(K ≥ k)")
    axA.grid(color=GRID, lw=0.4, which="major")
    axA.set_axisbelow(True)
    axA.legend(loc="upper right", fontsize=6.6, handlelength=1.4)
    stats = (f"实体 {thin(len(dv))} 个 · 关系 {thin(len(E))} 条\n"
             f"平均度 {dv.mean():.2f} · 中位度 {np.median(dv):.0f}\n"
             f"度为 1 的叶节点 {np.mean(dv == 1):.1%}\n"
             f"连通分量 {thin(len(comps))} 个，最大分量 {thin(comps[0])}（{comps[0]/len(N):.1%}）\n"
             f"x_min={xmin}，KS={ks:.3f}")
    axA.text(0.03, 0.03, stats, transform=axA.transAxes, ha="left", va="bottom", fontsize=6.0,
             color=INK2, linespacing=1.35)
    panel_label(axA, "A", x=-0.13, y=1.02)

    # ---- B：度中心性前 20 的枢纽实体（按知识来源着色） ----
    top = deg.most_common(20)
    y = np.arange(len(top))
    type_zh = {k: v["zh"] for k, v in D["types"].items()}
    axB.barh(y, [c for _, c in top], height=0.7, color=[ROLE_COLOR[N[i]["r"]] for i, _ in top],
             edgecolor="white", linewidth=0.4)
    axB.set_yticks(y, [f"{N[i]['l']}（{type_zh[N[i]['t']]}）" for i, _ in top], fontsize=6.4)
    axB.invert_yaxis()
    for yy, (_, c) in zip(y, top):
        axB.text(c + 4, yy, str(c), va="center", fontsize=6.0, color=INK2)
    axB.set_xlabel("度")
    axB.set_xlim(0, 510)
    _hbar_axes(axB)
    from matplotlib.patches import Patch
    used = [r for r in ROLE_ORDER if any(N[i]["r"] == r for i, _ in top)]
    axB.legend(handles=[Patch(fc=ROLE_COLOR[r], label=ROLE_ZH[r]) for r in used], loc="lower right",
               fontsize=6.4, handlelength=1.0, handleheight=0.8)
    panel_label(axB, "B", x=-0.62, y=1.02)
    save(fig, "图6_网络拓扑特征")
    return dict(alpha=alpha, xmin=xmin, ks=ks, ntail=ntail, comps=len(comps), giant=comps[0],
                mean_deg=float(dv.mean()), leaf=float(np.mean(dv == 1)))


if __name__ == "__main__":
    import style
    style.setup()
    fig_type_distribution()
    fig_source_distribution()
    fig_quality()
    print(fig_topology())
