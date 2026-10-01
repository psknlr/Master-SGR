# -*- coding: utf-8 -*-
"""
图2 中和学术思想专题本体模型（模式层）。

节点位置按“上：思想与渊源 → 中：辨证论治链 → 下：方药与养生康复”的叙述顺序手工排定；
连线交给 Graphviz neato（固定坐标 + splines=true）绕开节点自动走线，
再由 matplotlib 统一出图，保证字号与印刷尺寸一致。所有计数取自图谱实例。
"""
import json
import math
import subprocess
from collections import Counter

import data as G
from drawkit import Canvas
from style import INK, INK2, INK3, SERIF, save

MM2PT = 72 / 25.4
H_NODE = 4.9

# 模块区域（x, y, w, h，毫米）与配色（浅底、描边）
TITLE_RIGHT = {"辨证论治层", "方药配伍层", "养生康复层"}
LABEL_T = {   # 个别关系标签沿线位置（0–1），避开交叉
    "METHOD_USES_FORMULA": 0.32, "HAS_FUNCTION": 0.62, "DIAGNOSED_AS": 0.30,
    "REALIZED_BY_TRIPLET": 0.62, "TREATS": 0.45, "HERB_SOURCE_TEXT": 0.30,
    "HAS_SOURCE_CITATION": 0.80, "PRACTICES_METHOD": 0.88, "PROPOSED_BY": 0.62,
    "CASE_ILLUSTRATES": 0.45, "TECHNIQUE_TREATS": 0.72, "BASED_ON_FORMULA": 0.62,
    "ESTABLISHES_METHOD|Syndrome": 0.62, "THOUGHT_HAS_PRINCIPLE|AcademicViewpoint": 0.45,
    "THOUGHT_HAS_PRINCIPLE|ZhongheThought": 0.55, "HAS_SYMPTOM": 0.62, "PRESENTS_TONGUE": 0.66,
    "PRESENTS_PULSE": 0.70, "SYNDROME_OF_DISEASE": 0.55, "EXPLAINED_BY": 0.5, "ATTRIBUTED_TO": 0.55,
    "CASE_OF_PATIENT": 0.78, "INDICATED_FOR_COSMETIC": 0.55, "TRIPLET_HAS_MEMBER": 0.55,
}
REGIONS = {
    "中和思想层": ((2.5, 2.5, 92.0, 32.0), "#FBEDEA", "#B8322A"),
    "传承溯源层": ((98.5, 2.5, 74.0, 32.0), "#F2F0EC", "#6E665A"),
    "医案诊次层": ((2.5, 46.0, 25.0, 74.0), "#ECF6F2", "#1E8C73"),
    "辨证论治层": ((31.0, 38.5, 141.5, 46.5), "#EEF3FA", "#2A6BB0"),
    "方药配伍层": ((31.0, 88.5, 105.0, 31.5), "#FBF3E4", "#A8720E"),
    "养生康复层": ((139.5, 88.5, 33.0, 31.5), "#F3EEF8", "#7B4AA5"),
}

POS = {   # 节点中心（毫米，y 向下）
    "ClinicalMaxim": (14, 13), "ZhongheThought": (50, 13), "AcademicViewpoint": (22, 27),
    "Maxim": (66, 22),
    "ClassicalText": (118, 13), "SourceCitation": (157, 27), "Physician": (118, 27), "School": (155, 13),
    "CaseRecord": (15, 58), "Visit": (15, 78), "Patient": (15, 101),
    "TreatmentPrinciple": (46, 52), "TreatmentMethod": (77, 52), "Pathomechanism": (104, 52),
    "Etiology": (133, 52), "Syndrome": (104, 74), "Disease": (140, 79),
    "Symptom": (157, 50), "TongueSign": (157, 60), "PulseSign": (157, 70),
    "Prescription": (43, 96), "HerbTriplet": (76, 96), "Formula": (104, 96),
    "ExternalPreparation": (126, 96), "NewFormula": (122, 106), "HerbPair": (52, 113),
    "Herb": (86, 113), "DietaryTherapy": (114, 115),
    "HealthPreservationMethod": (156, 98), "RehabilitationTechnique": (156, 106.5),
    "CosmeticIndication": (156, 115),
}

CORE = {"ZhongheThought", "TreatmentPrinciple", "HerbTriplet"}
HOT = {"THOUGHT_HAS_PRINCIPLE", "PRINCIPLE_GUIDES_METHOD", "REALIZED_BY_TRIPLET",
       "MAXIM_EXPRESSES", "DERIVED_FROM"}
LONG = {"HERB_SOURCE_TEXT", "HAS_SOURCE_CITATION", "PRACTICES_METHOD", "TECHNIQUE_TREATS",
        "INDICATED_FOR_COSMETIC", "CASE_ILLUSTRATES", "PROPOSED_BY", "QUOTES_FROM"}

# (关系, 定义域, 值域[, 显示名])
SCHEMA = [
    ("MAXIM_EXPRESSES", "ClinicalMaxim", "ZhongheThought"),
    ("THOUGHT_HAS_PRINCIPLE", "ZhongheThought", "TreatmentPrinciple"),
    ("THOUGHT_HAS_PRINCIPLE", "AcademicViewpoint", "TreatmentPrinciple"),
    ("COMMENTS_ON", "AcademicViewpoint", "Maxim"),
    ("DERIVED_FROM", "ZhongheThought", "ClassicalText", "渊源·引经据典"),
    ("PROPOSED_BY", "AcademicViewpoint", "Physician"),
    ("QUOTES_FROM", "Maxim", "ClassicalText"),
    ("STUDIED_UNDER", "Physician", "Physician"),
    ("BELONGS_TO_SCHOOL", "Physician", "School"),
    ("PRINCIPLE_GUIDES_METHOD", "TreatmentPrinciple", "TreatmentMethod"),
    ("ESTABLISHES_METHOD", "Pathomechanism", "TreatmentMethod"),
    ("ESTABLISHES_METHOD", "Syndrome", "TreatmentMethod"),
    ("EXPLAINED_BY", "Syndrome", "Pathomechanism"),
    ("ATTRIBUTED_TO", "Syndrome", "Etiology"),
    ("MECHANISM_LEADS_TO", "Pathomechanism", "Pathomechanism"),
    ("SYNDROME_OF_DISEASE", "Syndrome", "Disease"),
    ("HAS_SYMPTOM", "Syndrome", "Symptom"),
    ("PRESENTS_TONGUE", "Syndrome", "TongueSign"),
    ("PRESENTS_PULSE", "Syndrome", "PulseSign"),
    ("HAS_VISIT", "CaseRecord", "Visit"),
    ("CASE_OF_PATIENT", "CaseRecord", "Patient"),
    ("CASE_ILLUSTRATES", "CaseRecord", "AcademicViewpoint"),
    ("DIAGNOSED_AS", "Visit", "Syndrome"),
    ("PRESCRIBED", "Visit", "Prescription"),
    ("METHOD_USES_FORMULA", "TreatmentMethod", "Formula"),
    ("TREATS", "Formula", "Syndrome"),
    ("REALIZED_BY_TRIPLET", "TreatmentPrinciple", "HerbTriplet"),
    ("HAS_FUNCTION", "HerbTriplet", "TreatmentMethod"),
    ("CONTAINS_TRIPLET", "Prescription", "HerbTriplet"),
    ("BASED_ON_FORMULA", "Prescription", "Formula"),
    ("TRIPLET_HAS_MEMBER", "HerbTriplet", "Herb"),
    ("TRIPLET_EXTENDS_PAIR", "HerbTriplet", "HerbPair"),
    ("PAIR_HAS_MEMBER", "HerbPair", "Herb"),
    ("MODIFIES_PRESCRIPTION", "Formula", "Herb"),
    ("CONTAINS_HERB", "NewFormula", "Herb"),
    ("CONTAINS_HERB", "ExternalPreparation", "Herb"),
    ("HERB_SOURCE_TEXT", "Herb", "ClassicalText"),
    ("HAS_SOURCE_CITATION", "NewFormula", "SourceCitation"),
    ("INDICATED_FOR_COSMETIC", "Herb", "CosmeticIndication"),
    ("TECHNIQUE_TREATS", "RehabilitationTechnique", "Disease"),
    ("PRACTICES_METHOD", "AcademicViewpoint", "HealthPreservationMethod"),
]


def fmt(n):
    return f"{n:,}".replace(",", " ")


def text_w(s, fs):
    mm = fs * 0.3528
    return sum(mm if ord(ch) > 0x2E7F else mm * 0.5 for ch in s)


def point_at(P, t):
    """沿三次贝塞尔折线按弧长取点。P 为 [p0, c1, c2, p1, c1, c2, p2, ...]。"""
    import numpy as np
    pts = []
    for i in range(0, len(P) - 3, 3):
        p0, p1, p2, p3 = map(np.array, P[i:i + 4])
        for u in np.linspace(0, 1, 24, endpoint=False):
            pts.append((1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u ** 2 * p2 + u ** 3 * p3)
    pts.append(np.array(P[-1]))
    pts = np.array(pts)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    target = t * cum[-1]
    j = min(np.searchsorted(cum, target), len(pts) - 1)
    return tuple(pts[j])


def fig_ontology():
    D = G.load()
    N, E = D["nodes"], D["edges"]
    tcount = Counter(n["t"] for n in N)
    pc = Counter((e["y"], N[e["s"]]["t"], N[e["t"]]["t"]) for e in E)
    rel_zh = {k: v["zh"] for k, v in D["rels"].items()}
    type_zh = {k: v["zh"] for k, v in D["types"].items()}

    size = {}
    for t, (x, y) in POS.items():
        w = text_w(type_zh[t], 7.2) + text_w(" " + fmt(tcount.get(t, 0)), 6.2) + 3.2
        size[t] = (w, H_NODE)

    # ---------- Graphviz 仅负责走线 ----------
    Hc = 125.0
    L = ['digraph O { graph [splines=true, outputorder=edgesfirst, sep="+3", esep="+2"];',
         'node [shape=box, fixedsize=true, label=""];',
         'edge [arrowsize=0.5, fontname="Noto Serif CJK SC", fontsize=6];']
    for t, (x, y) in POS.items():
        w, h = size[t]
        L.append(f'"{t}" [pos="{x*MM2PT:.1f},{(Hc-y)*MM2PT:.1f}!", width={w/25.4:.3f}, height={h/25.4:.3f}];')
    for k, item in enumerate(SCHEMA):
        rel, s, t = item[:3]
        name = item[3] if len(item) > 3 else rel_zh[rel]
        L.append(f'"{s}" -> "{t}" [label="{name}", id="e{k}"];')
    L.append("}")
    res = subprocess.run(["neato", "-n2", "-Tjson"], input="\n".join(L), capture_output=True,
                         text=True, check=True)
    gj = json.loads(res.stdout)
    # neato 会把整体平移到原点附近，用任一节点的输出坐标反推平移量
    o = next(ob for ob in gj["objects"] if ob.get("name") in POS)
    ox, oy = map(float, o["pos"].split(","))
    x_in, y_in = POS[o["name"]][0] * MM2PT, (Hc - POS[o["name"]][1]) * MM2PT
    dx, dy = ox - x_in, oy - y_in
    routes = {}
    for ed in gj.get("edges", []):
        k = int(ed["id"][1:])
        pts = [op["points"] for op in ed.get("_draw_", []) if op["op"] == "b"]
        head = [op["points"] for op in ed.get("_hdraw_", []) if op["op"] in ("P", "p")]
        lp = ed.get("lp")
        routes[k] = (pts[0] if pts else None, head[0] if head else None,
                     tuple(map(float, lp.split(","))) if lp else None)

    def to_mm(p):
        return ((p[0] - dx) / MM2PT, Hc - (p[1] - dy) / MM2PT)

    # ---------- 出图 ----------
    c = Canvas(175, 127)
    ax = c.ax
    for name, ((x, y, w, h), fill, line) in REGIONS.items():
        c.box(x, y, w, h, fc=fill, ec=line, lw=0.6, r=1.6, ls=(0, (3, 2)), z=0)
        if name in TITLE_RIGHT:
            c.text(x + w - 1.6, y + 2.6, name, fs=7.2, color=line, ha="right", weight="bold", z=1)
        else:
            c.text(x + 1.6, y + 2.6, name, fs=7.2, color=line, ha="left", weight="bold", z=1)

    import numpy as np
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch, Polygon

    for k, item in enumerate(SCHEMA):
        rel, s, t = item[:3]
        n = pc.get((rel, s, t), 0)
        pts, head, lp = routes[k]
        if pts is None:
            continue
        P = [to_mm(p) for p in pts]
        codes = [Path.MOVETO] + [Path.CURVE4] * (len(P) - 1)
        hot = rel in HOT
        col = "#B8322A" if hot else ("#A39C90" if rel in LONG else "#7C7468")
        lw = 0.35 + 0.30 * math.log10(max(n, 1))
        ax.add_patch(PathPatch(Path(P, codes), fc="none", ec=col, lw=lw, zorder=1,
                               ls=(0, (2.2, 1.4)) if rel in LONG else "-", capstyle="butt"))
        if head:
            ax.add_patch(Polygon([to_mm(p) for p in head], closed=True, fc=col, ec=col, lw=0.3, zorder=1))
        name = item[3] if len(item) > 3 else rel_zh[rel]
        lab = f"{name} {fmt(n)}"
        if s == t:      # 自环：标签放在节点右上方
            nx, ny = POS[s]
            x, y, ha = nx + size[s][0] / 2 + 1.0, ny - H_NODE / 2 - 1.6, "left"
        else:
            tt = LABEL_T.get(f"{rel}|{s}", LABEL_T.get(rel, 0.5))
            x, y = point_at(P, tt)
            ha = "center"
        c.text(x, y, lab, fs=5.6, color="#8E2A22" if hot else INK2, z=3, ha=ha,
               bbox=dict(boxstyle="round,pad=0.10", fc="white", ec="none", alpha=0.92))

    region_of = {t: m for m, ts in G.MODULES for t in ts}
    for t, (x, y) in POS.items():
        w, h = size[t]
        line = REGIONS[region_of[t]][2]
        n = tcount.get(t, 0)
        core = t in CORE
        c.box(x - w / 2, y - h / 2, w, h, fc="white", ec=line, lw=1.3 if core else 0.6, r=1.0, z=4,
              ls=(0, (2, 1.2)) if n == 0 else "-")
        nm, cnt = type_zh[t], " " + fmt(n)
        tw = text_w(nm, 7.2) + text_w(cnt, 6.2)
        x0 = x - tw / 2
        c.text(x0, y + 0.15, nm, fs=7.2, ha="left", weight="bold" if core else "normal", z=5)
        c.text(x0 + text_w(nm, 7.2), y + 0.25, cnt, fs=6.2, ha="left", color=INK3, z=5)

    # 图例
    ly = 124.2
    c.ax.plot([4, 11], [ly, ly], color="#B8322A", lw=1.0)
    c.text(12, ly, "中和思想贯通链路（思想—治则—治法—药组）", fs=6.2, ha="left", color=INK2)
    c.ax.plot([62, 69], [ly, ly], color="#7C7468", lw=1.0)
    c.text(70, ly, "层内/相邻层关系", fs=6.2, ha="left", color=INK2)
    c.ax.plot([92, 99], [ly, ly], color="#A39C90", lw=0.9, ls=(0, (2.2, 1.4)))
    c.text(100, ly, "跨层溯源与关联关系", fs=6.2, ha="left", color=INK2)
    c.text(171.5, ly, "数字为实例数；线宽∝lg(实例数)", fs=6.2, ha="right", color=INK3)
    save(c.fig, "图2_中和学术思想专题本体模型")


if __name__ == "__main__":
    import style
    style.setup()
    fig_ontology()
