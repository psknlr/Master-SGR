# -*- coding: utf-8 -*-
"""图7 “症—证—因—机—法—方—药”辨证论治链流图（类型层 Sankey，流量 = 关系实例数）。"""
from collections import Counter, defaultdict

import numpy as np
from matplotlib.patches import Polygon, Rectangle

import data as G
from drawkit import Canvas
from style import INK, INK2, INK3, ACCENT, SEQ, save

COLS = [
    ("四诊信息", ["Symptom", "TongueSign", "PulseSign"]),
    ("病证", ["Syndrome", "Disease"]),
    ("病因病机", ["Pathomechanism", "Etiology"]),
    ("治则治法", ["TreatmentMethod", "TreatmentPrinciple"]),
    ("方剂", ["Formula", "Prescription", "NewFormula"]),
    ("药组", ["HerbTriplet", "HerbPair"]),
    ("中药", ["Herb"]),
]
CHAIN_RELS = {"HAS_SYMPTOM", "PRESENTS_TONGUE", "PRESENTS_PULSE", "DIAGNOSED_AS", "ATTRIBUTED_TO",
              "EXPLAINED_BY", "ESTABLISHES_METHOD", "METHOD_USES_FORMULA", "PRINCIPLE_GUIDES_METHOD",
              "HAS_FUNCTION", "REALIZED_BY_TRIPLET", "CONTAINS_TRIPLET", "CONTAINS_HERB",
              "MODIFIES_PRESCRIPTION", "TRIPLET_HAS_MEMBER", "PAIR_HAS_MEMBER"}
MIN_FLOW = 20
LABEL_AT = {("Prescription", "HerbTriplet"): 0.35, ("Formula", "Herb"): 0.62, ("Prescription", "Herb"): 0.70,
            ("NewFormula", "Herb"): 0.70, ("TreatmentMethod", "HerbTriplet"): 0.18,
            ("TreatmentPrinciple", "Formula"): 0.80, ("Syndrome", "TreatmentPrinciple"): 0.62,
            ("Symptom", "Disease"): 0.35, ("TongueSign", "Syndrome"): 0.30, ("PulseSign", "Syndrome"): 0.25}
# 每列自上而下的摆放顺序；数字为留空（毫米），用作跨列流带的通道
STACK = {
    0: ["Symptom", 4, "TongueSign", 3, "PulseSign"],
    1: ["Syndrome", 6, "Disease"],
    2: ["Pathomechanism", 3, "Etiology"],
    3: [24, "TreatmentMethod", 4.5, "TreatmentPrinciple"],
    4: ["Formula", 14, "Prescription", 3, "NewFormula"],
    5: ["HerbTriplet", 3, "HerbPair"],
    6: ["Herb"],
}
EXCLUDE = {("Symptom", "Pathomechanism"), ("Symptom", "Etiology"), ("TreatmentMethod", "Herb")}
LANE = {   # 跨列流带的中途点：(列号, 中心 y 相对该列最后一个节点底部的偏移，毫米)
    ("Syndrome", "TreatmentMethod"): [(2, 9.6)], ("Syndrome", "TreatmentPrinciple"): [(2, 22.5)],
    ("Disease", "TreatmentMethod"): [(2, 29.0)], ("Disease", "TreatmentPrinciple"): [(2, 32.2)],
    ("TreatmentMethod", "HerbTriplet"): [(4, None)],
    ("Formula", "Herb"): [(5, 9.5)], ("Prescription", "Herb"): [(5, 23.5)], ("NewFormula", "Herb"): [(5, 41.5)],
}


def smooth(points, n=40):
    """经过各点、各点处切线水平的三次贝塞尔中心线。"""
    out = []
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        dx = (x1 - x0) / 2
        p0, p1, p2, p3 = map(np.array, [(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)])
        u = np.linspace(0, 1, n)[:, None]
        out.append((1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u ** 2 * p2 + u ** 3 * p3)
    return np.vstack(out)


def fig_sankey():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    type_zh = {k: v["zh"] for k, v in D["types"].items()}
    col_of = {t: i for i, (_, ts) in enumerate(COLS) for t in ts}

    flow = Counter()
    for e in E:
        a, b = N[e["s"]]["t"], N[e["t"]]["t"]
        if e["y"] not in CHAIN_RELS or a not in col_of or b not in col_of or col_of[a] == col_of[b]:
            continue
        if col_of[a] > col_of[b]:
            a, b = b, a
        flow[(a, b)] += 1
    flow = {k: v for k, v in flow.items() if v >= MIN_FLOW and k not in EXCLUDE}
    tot_in, tot_out = Counter(), Counter()
    for (a, b), v in flow.items():
        tot_out[a] += v
        tot_in[b] += v
    ntot = Counter(n["t"] for n in N)

    S = 0.0245                   # 毫米 / 条
    NW = 3.0
    X0, X1 = 9.0, 166.0
    colx = np.linspace(X0, X1 - NW, len(COLS))
    c = Canvas(175, 121)
    ax = c.ax

    geo, col_bottom, gap_mid = {}, {}, {}
    for i, seq in STACK.items():
        y = 12.0
        prev = None
        for item in seq:
            if isinstance(item, (int, float)):
                if prev is not None:
                    gap_mid[(i, prev)] = (y, item)
                y += item
                continue
            h = max(tot_in[item], tot_out[item]) * S
            geo[item] = [colx[i], y, h]
            y += h
            prev = item
        col_bottom[i] = y

    def lane_y(a, b):
        out = []
        for ci, off in LANE.get((a, b), []):
            if off is None:             # 走该列前两个节点之间的空隙
                first = STACK[ci][0]
                y0, gap = gap_mid[(ci, first)]
                out.append((ci, y0 + gap / 2))
            else:
                out.append((ci, col_bottom[ci] + off))
        return out
    WAY = {k: lane_y(*k) for k in LANE}

    # 槽位：按对端中心 y 排序，减少交叉
    def center(t):
        x, y, h = geo[t]
        return y + h / 2

    out_slots, in_slots = defaultdict(list), defaultdict(list)
    for (a, b), v in flow.items():
        out_slots[a].append((b, v))
        in_slots[b].append((a, v))
    pos_out, pos_in = {}, {}
    for t, lst in out_slots.items():
        lst.sort(key=lambda bv: (center(bv[0]) if not WAY.get((t, bv[0])) else WAY[(t, bv[0])][0][1]))
        y = geo[t][1]
        for b, v in lst:
            pos_out[(t, b)] = y; y += v * S
    for t, lst in in_slots.items():
        lst.sort(key=lambda av: (center(av[0]) if not WAY.get((av[0], t)) else WAY[(av[0], t)][-1][1]))
        y = geo[t][1]
        for a, v in lst:
            pos_in[(a, t)] = y; y += v * S

    # 流带
    for (a, b), v in sorted(flow.items(), key=lambda kv: -kv[1]):
        w = v * S
        xa = geo[a][0] + NW
        xb = geo[b][0]
        ya = pos_out[(a, b)] + w / 2
        yb = pos_in[(a, b)] + w / 2
        pts = [(xa, ya)] + [(colx[ci] + NW / 2, yy) for ci, yy in WAY.get((a, b), [])] + [(xb, yb)]
        cl = smooth(pts)
        poly = np.vstack([cl + [0, -w / 2], (cl + [0, w / 2])[::-1]])
        hot = "HerbTriplet" in (a, b) or "TreatmentPrinciple" in (a, b)
        ax.add_patch(Polygon(poly, closed=True, fc=ACCENT if hot else SEQ, alpha=0.30 if hot else 0.22,
                             ec="none", zorder=1))
        # 流量标注（较大的流带）
        if v >= 150:
            m = cl[len(cl) // 2] if not WAY.get((a, b)) else cl[len(cl) // 4]
            if (a, b) in LABEL_AT:
                m = cl[int(len(cl) * LABEL_AT[(a, b)])]
            c.text(m[0], m[1], f"{v:,}".replace(",", " "), fs=5.6, color=INK2, z=6,
                   bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="none", alpha=0.75))

    # 节点与标签
    for i, (title, ts) in enumerate(COLS):
        c.text(colx[i] + NW / 2, 6.0, title, fs=7.6, weight="bold", color=INK)
        for t in ts:
            x, y, h = geo[t]
            ax.add_patch(Rectangle((x, y), NW, h, fc=INK, ec="none", zorder=4))
            lab = f"{type_zh[t]}\n{ntot[t]:,}".replace(",", " ")
            if i == len(COLS) - 1:
                c.text(x - 0.8, y + h / 2, lab, fs=6.6, ha="right", z=7, linespacing=1.1,
                       bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85))
            else:
                c.text(x + NW + 0.8, y + min(h / 2, 4.2), lab, fs=6.6, ha="left", z=7, linespacing=1.1,
                       bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85))
    # 图例
    ly = 118.0
    ax.add_patch(Rectangle((9, ly - 1.2), 6, 2.4, fc=SEQ, alpha=0.30, ec="none"))
    c.text(16, ly, "辨证论治主链流量", fs=6.4, ha="left", color=INK2)
    ax.add_patch(Rectangle((50, ly - 1.2), 6, 2.4, fc=ACCENT, alpha=0.38, ec="none"))
    c.text(57, ly, "经“治则”或“三联药组”的中和特色链路", fs=6.4, ha="left", color=INK2)
    c.text(166, ly, f"带宽∝关系实例数；仅示≥{MIN_FLOW} 条的类型间流量；节点旁数字为实体数",
           fs=6.2, ha="right", color=INK3)
    save(c.fig, "图7_辨证论治链路流图")
    return flow


if __name__ == "__main__":
    import style
    style.setup()
    f = fig_sankey()
    for k, v in sorted(f.items(), key=lambda kv: -kv[1]):
        print(k, v)
