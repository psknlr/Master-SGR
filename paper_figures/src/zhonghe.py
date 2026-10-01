# -*- coding: utf-8 -*-
"""图8 孙光荣中和学术思想专题子图：渊源 → 中和思想 → 内涵与治则 → 临证落实。"""
from collections import Counter, defaultdict

import data as G
from drawkit import Canvas
from gvrender import layout, draw_edge, text_w, wrap
from style import INK, INK2, INK3, ACCENT, SEQ, save

FS = 6.4
TIER = {   # 类型 → 层（心法要诀、名言、医案等表述/例证类节点见表 4，图中从略以保证可读）
    "ClassicalText": 0, "Physician": 0,
    "ZhongheThought": 1,
    "TreatmentPrinciple": 2,
    "TreatmentMethod": 3, "HerbTriplet": 3, "Prescription": 3,
}
TIER_NAME = ["学术渊源", "中和思想", "治则", "治法 · 药组"]
STYLE = {   # 类型 → (描边, 底色)
    "ZhongheThought": ("#B8322A", "#FBEDEA"),
    "TreatmentPrinciple": ("#2A6BB0", "#EEF3FA"),
    "TreatmentMethod": ("#2A6BB0", "#FFFFFF"),
    "HerbTriplet": ("#A8720E", "#FBF3E4"), "Prescription": ("#A8720E", "#FFFFFF"),
    "ClinicalMaxim": ("#7B4AA5", "#F6F1FA"), "Maxim": ("#7B4AA5", "#FFFFFF"),
    "AcademicViewpoint": ("#7B4AA5", "#FFFFFF"), "CaseRecord": ("#1E8C73", "#FFFFFF"),
    "Disease": ("#1E8C73", "#FFFFFF"),
    "ClassicalText": ("#6E665A", "#F2F0EC"), "Physician": ("#6E665A", "#FFFFFF"),
}


def build():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    adj = G.adjacency()
    Z = [n["i"] for n in N if n["t"] == "ZhongheThought"]
    keep = set(Z)
    sun = next(n["i"] for n in N if n["l"] == "孙光荣" and n["t"] == "Physician")
    for z in Z:
        for k in adj[z]:
            e = E[k]
            o = e["t"] if e["s"] == z else e["s"]
            if o != sun and N[o]["t"] in TIER:
                keep.add(o)
    P = [i for i in keep if N[i]["t"] == "TreatmentPrinciple"]
    for p in P:
        for k in adj[p]:
            e = E[k]
            o = e["t"] if e["s"] == p else e["s"]
            if e["y"] in ("PRINCIPLE_GUIDES_METHOD", "REALIZED_BY_TRIPLET") and N[o]["t"] in TIER:
                keep.add(o)
    edges = {}
    for k, e in enumerate(E):
        if e["s"] in keep and e["t"] in keep and e["s"] != e["t"]:
            a, b = e["s"], e["t"]
            if TIER[N[a]["t"]] > TIER[N[b]["t"]]:
                a, b = b, a                       # 布局方向统一自左向右
            if TIER[N[a]["t"]] == TIER[N[b]["t"]]:
                continue
            key = (a, b)
            edges.setdefault(key, set()).add(e["y"])
    return keep, edges, sun


def fig_zhonghe():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    rel_zh = {k: v["zh"] for k, v in D["rels"].items()}
    keep, edges, sun = build()

    # 同名经典（如“中藏经”在多部文献各有一个实体）在图中合并显示
    canon = {}
    by_label = {}
    for i in sorted(keep):
        k = (N[i]["t"], N[i]["l"])
        by_label.setdefault(k, i)
        canon[i] = by_label[k]
    linked = set()
    for (a, b) in edges:
        linked.add(canon[a]); linked.add(canon[b])
    nodes = {}
    for i in keep:
        if canon[i] not in linked:
            continue
        c = canon[i]
        if c in nodes:
            continue
        t = N[c]["t"]
        lab = N[c]["l"].replace(",", "，")
        lab = wrap(lab, 15 if t == "ZhongheThought" else (18 if t == "TreatmentPrinciple" else (10 if t == "ClassicalText" else 11)))
        lines = lab.split("\n")
        w = max(text_w(s, FS) for s in lines) + 2.6
        h = 1.2 + len(lines) * FS * 0.3528 * 1.22 + 0.4
        nodes[c] = (w, h, f'group="t{TIER[t]}"', lab)
    E2 = {}
    for (a, b), rels in edges.items():
        a, b = canon[a], canon[b]
        if a != b:
            E2.setdefault((a, b), set()).update(rels)

    # 层约束：同层 rank=same
    tiers = defaultdict(list)
    for c in nodes:
        tiers[TIER[N[c]["t"]]].append(c)
    gattrs = 'rankdir=LR, nodesep=0.045, ranksep=0.36, splines=true, newrank=true'
    lay_nodes = {c: (w, h, extra) for c, (w, h, extra, _) in nodes.items()}
    lay_edges = [(a, b, "") for (a, b) in E2]
    ranks = [list(v) for _, v in sorted(tiers.items())]
    pos, routes, (W, H) = layout(lay_nodes, lay_edges, "dot", gattrs, same_rank=ranks)

    top = 9.0
    c = Canvas(max(W, 168) + 4, H + top + 8)
    ax = c.ax
    ox = (c.w - W) / 2
    for k, ((a, b), rels) in enumerate(E2.items()):
        pts, hd = routes[k]
        if pts is None:
            continue
        pts = [(x + ox, y + top) for x, y in pts]
        hd = [(x + ox, y + top) for x, y in hd] if hd else None
        hot = rels & {"THOUGHT_HAS_PRINCIPLE", "PRINCIPLE_GUIDES_METHOD", "REALIZED_BY_TRIPLET"}
        col = "#C9726A" if hot else "#A8A196"
        draw_edge(ax, (pts, hd), col, 0.55 if hot else 0.45, z=1, alpha=0.95)

    for cid, (w, h, _, lab) in nodes.items():
        x, y = pos[cid]
        x += ox; y += top
        t = N[cid]["t"]
        ec, fc = STYLE[t]
        core = t == "ZhongheThought"
        c.box(x - w / 2, y - h / 2, w, h, fc=fc, ec=ec, lw=0.9 if core else 0.5, r=0.8, z=3)
        c.text(x, y + 0.1, lab, fs=FS, color=INK, z=4, weight="bold" if core and N[cid]["l"] in ("中和学术思想", "中和") else "normal",
               linespacing=1.12)

    # 层标题
    xs = defaultdict(list)
    for cid in nodes:
        xs[TIER[N[cid]["t"]]].append(pos[cid][0] + ox)
    for t, name in enumerate(TIER_NAME):
        if xs[t]:
            c.text(sum(xs[t]) / len(xs[t]), 4.0, name, fs=7.4, weight="bold", color=INK)
    # 图例
    from matplotlib.patches import FancyBboxPatch
    items = [("ClassicalText", "经典文献 / 医家"), ("ZhongheThought", "中和思想"), ("TreatmentPrinciple", "治则"),
             ("TreatmentMethod", "治法"), ("HerbTriplet", "三联药组 / 处方")]
    lx, ly = 6, c.h - 3.2
    for t, name in items:
        ec, fc = STYLE[t]
        c.box(lx, ly - 1.3, 4.2, 2.6, fc=fc, ec=ec, lw=0.6, r=0.5)
        c.text(lx + 5.0, ly, name, fs=6.2, ha="left", color=INK2)
        lx += 5.0 + text_w(name, 6.2) + 5
    ax.plot([lx + 1, lx + 7], [ly, ly], color="#C9726A", lw=0.7)
    c.text(lx + 8, ly, "含治则 / 指导治法 / 见于药组", fs=6.2, ha="left", color=INK2)
    lx += 8 + text_w("含治则 / 指导治法 / 见于药组", 6.2) + 5
    ax.plot([lx + 1, lx + 7], [ly, ly], color="#A8A196", lw=0.6)
    c.text(lx + 8, ly, "渊源 / 引经据典", fs=6.2, ha="left", color=INK2)
    save(c.fig, "图8_中和学术思想专题子图")
    return len(nodes), len(E2), (W, H)


if __name__ == "__main__":
    import style
    style.setup()
    print(fig_zhonghe())
