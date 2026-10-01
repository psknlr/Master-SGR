# -*- coding: utf-8 -*-
"""论文表格：三线表 Word（.docx）+ CSV。全部数值由图谱数据与检索评测结果计算。"""
import csv
import itertools
import json
import math
import os
from collections import Counter, defaultdict

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

import data as G
import herbs
from style import OUT

TDIR = os.path.join(OUT, "tables")


def thin(n):
    return f"{int(n):,}".replace(",", " ")


# ------------------------------------------------------------------ 三线表排版
def _set_border(cell, **kw):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    for edge in ("top", "left", "bottom", "right"):      # OOXML 规定的子元素顺序
        if edge not in kw:
            continue
        sz, val = kw[edge]
        el = borders.find(qn(f"w:{edge}"))
        if el is None:
            el = OxmlElement(f"w:{edge}")
            borders.append(el)
        el.set(qn("w:val"), val)
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")


def _font(run, size=9, bold=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Times New Roman"
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "宋体")
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")


def add_table(doc, title, header, rows, note=None, widths=None, align=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(title)
    _font(r, 9, bold=True)
    rpr = r._element.get_or_add_rPr()
    rpr.find(qn("w:rFonts")).set(qn("w:eastAsia"), "黑体")
    t = doc.add_table(rows=1 + len(rows), cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, row in enumerate([header] + rows):
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            cell.text = ""
            para = cell.paragraphs[0]
            a = (align or {}).get(j, "center")
            para.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER, "left": WD_ALIGN_PARAGRAPH.LEFT,
                              "right": WD_ALIGN_PARAGRAPH.RIGHT}[a]
            para.paragraph_format.space_before = Pt(1)
            para.paragraph_format.space_after = Pt(1)
            run = para.add_run(str(val))
            _font(run, 7.5 if i else 7.5, bold=(i == 0))
            if widths:
                cell.width = Cm(widths[j])
            nil = (0, "nil")
            top = (12, "single") if i == 0 else nil
            bottom = (6, "single") if i == 0 else ((12, "single") if i == len(rows) else nil)
            _set_border(cell, top=top, bottom=bottom, left=nil, right=nil)
    if note:
        p = doc.add_paragraph()
        r = p.add_run(note)
        _font(r, 7.5)
    doc.add_paragraph()
    # CSV
    fn = title.split(" ")[0]
    with open(os.path.join(TDIR, f"{fn}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([title]); w.writerow(header); w.writerows(rows)
        if note:
            w.writerow([note])


# ------------------------------------------------------------------ 各表
def table1(doc):
    D = G.load()
    N = D["nodes"]
    tc = Counter(n["t"] for n in N)
    rc = defaultdict(Counter)
    for n in N:
        rc[n["t"]][n["r"]] += 1
    from style import ROLE_ZH
    rows = []
    for mod, types in G.MODULES:
        first = True
        for t in types:
            k = tc.get(t, 0)
            main = rc[t].most_common(1)
            main_s = f"{ROLE_ZH[main[0][0]]}（{main[0][1]/k:.0%}）" if main else "—"
            rows.append([mod if first else "", D["types"][t]["zh"], D["types"][t]["en"], thin(k),
                         f"{k/len(N)*100:.2f}", main_s])
            first = False
    rows.append(["合计", "31 类", "", thin(len(N)), "100.00", ""])
    add_table(doc, "表1 孙光荣中和学术思想专题知识图谱本体概念类型及实例数",
              ["本体层", "概念类型", "英文名", "实体数/个", "占比/%", "主要知识来源（占比）"], rows,
              note="注：“食疗方”类型已在本体中定义，当前版本图谱暂无实例。",
              widths=[2.0, 2.2, 4.2, 1.8, 1.5, 4.0], align={2: "left", 5: "left"})


def table2(doc):
    D = G.load()
    N, E = D["nodes"], D["edges"]
    rc = Counter(e["y"] for e in E)
    qc = Counter(e["y"] for e in E if e["Q"])
    dr = defaultdict(Counter)
    for e in E:
        dr[e["y"]][(N[e["s"]]["t"], N[e["t"]]["t"])] += 1
    tz = {k: v["zh"] for k, v in D["types"].items()}
    rows = []
    for y in sorted(rc, key=lambda y: -rc[y]):
        (s, t), c = dr[y].most_common(1)[0]
        rows.append([D["rels"][y]["zh"], D["rels"][y]["en"], f"{tz[s]}→{tz[t]}（{c/rc[y]:.0%}）",
                     thin(rc[y]), f"{qc[y]/rc[y]*100:.1f}"])
    rows.append(["合计", "44 类", "", thin(len(E)), f"{sum(qc.values())/len(E)*100:.1f}"])
    add_table(doc, "表2 知识图谱关系类型、典型定义域/值域及实例数",
              ["关系", "英文名", "典型定义域→值域（占比）", "实例数/条", "待审率/%"], rows,
              note="注：待审率指未通过本体定义域/值域一致性校验、在图谱中标记为“待审”的关系比例。",
              widths=[2.4, 3.8, 5.6, 1.8, 1.6], align={1: "left", 2: "left"})


def table3(doc):
    D = G.load()
    N, E = D["nodes"], D["edges"]
    from style import ROLE_ORDER, ROLE_ZH
    ne = Counter(d for n in N for d in n["d"])
    rel = Counter(e["d"] for e in E)
    ch = defaultdict(set)
    for e in E:
        ch[e["d"]].add(e["c"])
    rr = defaultdict(Counter)
    for e in E:
        rr[e["d"]][e["r"]] += 1
    rows = []
    for d, name in D["docs"].items():
        tot = rel[d]
        rows.append([d, name, thin(len(ch[d])), thin(ne[d]), thin(tot)] +
                    [f"{rr[d][r]/tot*100:.1f}" for r in ROLE_ORDER])
    rows.append(["合计", "", thin(len({e['c'] for e in E})), thin(len(N)), thin(len(E))] +
                [f"{sum(rr[d][r] for d in rr)/len(E)*100:.1f}" for r in ROLE_ORDER])
    add_table(doc, "表3 文献来源、文本块与关系知识来源构成",
              ["编号", "文献", "文本块/个", "实体数/个", "关系数/条"] + [ROLE_ZH[r] + "/%" for r in ROLE_ORDER],
              rows, note="注：同一实体可出现于多部文献，故各文献实体数之和大于实体总数；知识来源比例按关系实例计算。",
              widths=[1.0, 4.4, 1.4, 1.4, 1.4, 1.3, 1.3, 1.3, 1.5, 1.3], align={1: "left"})


def table4(doc):
    D = G.load()
    N, E = D["nodes"], D["edges"]
    adj = G.adjacency()
    rows = []
    Z = sorted((n for n in N if n["t"] == "ZhongheThought"), key=lambda n: -len(adj[n["i"]]))
    for z in Z:
        pri, src, mx, cid = [], [], [], set()
        for k in adj[z["i"]]:
            e = E[k]
            o = e["t"] if e["s"] == z["i"] else e["s"]
            cid.add(e["c"])
            if e["y"] == "THOUGHT_HAS_PRINCIPLE":
                pri.append(N[o]["l"])
            elif e["y"] in ("DERIVED_FROM", "CITES") and N[o]["t"] in ("ClassicalText", "Physician"):
                if N[o]["l"] not in src:
                    src.append(N[o]["l"])
            elif e["y"] in ("MAXIM_EXPRESSES", "COMMENTS_ON"):
                mx.append(N[o]["l"])
        rows.append([z["l"], "；".join(pri) or "—", "、".join(src) or "—", "；".join(mx) or "—",
                     "、".join(sorted(cid))])
    add_table(doc, "表5 孙光荣中和学术思想核心概念及其治则、渊源与出处",
              ["中和思想概念", "所含治则", "学术渊源（经典/医家）", "相关心法要诀/名言", "出处编号"], rows,
              note="注：按关联度降序排列；出处编号格式为“文献编号#文本块编号”，可在图谱中直接回溯原文。",
              widths=[3.0, 4.6, 3.6, 3.0, 2.2], align={0: "left", 1: "left", 2: "left", 3: "left", 4: "left"})


def table5(doc):
    P, n, hc, top, co = herbs.herb_stats()
    sets = list(P.values())
    items = [h for h, _ in hc.most_common(40)]
    core = set(herbs.CORE)
    rules = []
    for k in (1, 2):
        for ante in itertools.combinations(items, k):
            if core & set(ante):
                continue
            sa = sum(1 for s in sets if set(ante) <= s)
            if sa == 0:
                continue
            for c in items:
                if c in ante or c in core:
                    continue
                sac = sum(1 for s in sets if set(ante) <= s and c in s)
                sup, conf = sac / n, sac / sa
                lift = conf / (hc[c] / n)
                if sup >= 0.08 and conf >= 0.8 and lift >= 1.3:
                    rules.append((ante, c, sac, sup, conf, lift))
    # 去掉被更短前件覆盖的冗余规则
    keep = []
    for r in sorted(rules, key=lambda r: (-r[3], -r[5])):
        if len(r[0]) == 2 and any(set(q[0]) < set(r[0]) and q[1] == r[1] for q in rules):
            continue
        keep.append(r)
    keep = keep[:16]
    rows = [[i + 1, "+".join(a), c, sac, f"{sup:.3f}", f"{conf:.3f}", f"{lift:.2f}"]
            for i, (a, c, sac, sup, conf, lift) in enumerate(keep)]
    add_table(doc, "表6 孙光荣医案处方高频药物关联规则（前 16 条）",
              ["序号", "前项", "后项", "频数/首", "支持度", "置信度", "提升度"], rows,
              note=f"注：N={n} 首医案处方；阈值：支持度≥0.08、置信度≥0.80、提升度≥1.30；"
                   f"生黄芪（{hc['生黄芪']/n:.1%}）、紫丹参（{hc['紫丹参']/n:.1%}）几乎见于全部处方，"
                   "作为核心药对单列，不参与规则挖掘；已剔除被更短前项覆盖的冗余规则。",
              widths=[1.0, 4.4, 2.2, 1.6, 1.6, 1.6, 1.6], align={1: "left"})
    return keep


def table6(doc):
    R = json.load(open(os.path.join(TDIR, "retrieval_eval.json"), encoding="utf-8"))
    from retrieval_eval import METHODS
    rows = []
    for code, name, _ in METHODS:
        T, O, L = R["template"][code], R["open"][code]["120"], R["latency_ms"][code]
        rows.append([f"{code} {name}", f"{T['hit@1']:.3f}", f"{T['hit@5']:.3f}", f"{T['hit@10']:.3f}",
                     f"{T['hit@20']:.3f}", f"{T['recall@20']:.3f}", f"{T['mrr']:.3f}",
                     f"{O['types']:.1f}", f"{O['entropy']:.3f}", f"{O['max_share']:.3f}",
                     f"{O['substantive']:.3f}", f"{L['median']:.1f}"])
    add_table(doc, "表7 不同检索方案的检索效果比较",
              ["方案", "Hit@1", "Hit@5", "Hit@10", "Hit@20", "Recall@20", "MRR",
               "类型数", "类型熵", "最大类型占比", "实质佐证占比", "时延/ms"], rows,
              note=f"注：Hit@k、Recall@20、MRR 基于模板问答集（n={R['n_template']}）；类型数、类型熵、最大类型占比、"
                   f"实质佐证占比基于开放问题集（n={R['n_open']}，取前 120 条关系）；时延为单次检索中位数"
                   "（云端容器 CPU，不含大模型生成）。M4、M5 在模板问答集上排序结果一致。",
              widths=[2.8] + [1.25] * 11, align={0: "left"})


def table7(doc, topo):
    D = G.load()
    N, E = D["nodes"], D["edges"]
    deg = G.degree()
    rows = [
        ["实体数 / 关系数", f"{thin(len(N))} / {thin(len(E))}"],
        ["本体概念类型 / 关系类型", "31 / 44"],
        ["文献 / 文本块", f"{len(D['docs'])} / {thin(len({e['c'] for e in E}))}"],
        ["带原文佐证的关系", f"{thin(sum(1 for e in E if e['q'].strip()))}（{sum(1 for e in E if e['q'].strip())/len(E):.2%}）"],
        ["实体异名", f"{thin(sum(len(n['a']) for n in N))} 条（{thin(sum(1 for n in N if n['a']))} 个实体）"],
        ["平均度 / 中位度 / 最大度", f"{topo['mean_deg']:.2f} / 1 / {max(deg.values())}（孙光荣）"],
        ["度为 1 的叶节点占比", f"{topo['leaf']:.1%}"],
        ["连通分量数 / 最大连通分量", f"{thin(topo['comps'])} / {thin(topo['giant'])}（{topo['giant']/len(N):.1%}）"],
        ["度分布幂律拟合 α（x_min, KS）", f"{topo['alpha']:.2f}（{topo['xmin']}, {topo['ks']:.3f}）"],
        ["“待审”关系", f"{sum(e['Q'] for e in E)}（{sum(e['Q'] for e in E)/len(E):.1%}）"],
        ["抽样审校严格精度", f"v1 {D['meta']['audit']['v1_strict']:.1%}（n={D['meta']['audit']['v1_n']}）；"
                            f"v2 {D['meta']['audit']['v2_strict']:.1%}（n={D['meta']['audit']['v2_n']}）"],
    ]
    add_table(doc, "表4 知识图谱规模、拓扑与质量指标", ["指标", "数值"], rows,
              widths=[6.0, 8.0], align={0: "left", 1: "left"})


def build_all(topo):
    os.makedirs(TDIR, exist_ok=True)
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    st.font.size = Pt(9)
    table1(doc)
    table2(doc)
    table3(doc)
    table7(doc, topo)      # 表4 规模·拓扑·质量
    table4(doc)            # 表5 中和思想核心概念
    table5(doc)            # 表6 关联规则
    table6(doc)            # 表7 检索实验
    fn = os.path.join(TDIR, "论文表格_三线表.docx")
    doc.save(fn)
    print("  ✔", fn)


if __name__ == "__main__":
    import style, charts
    style.setup()
    build_all(charts.fig_topology())
