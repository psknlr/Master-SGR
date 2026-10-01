# -*- coding: utf-8 -*-
"""图10 可溯源 GraphRAG 问答框架；图11 证据链示例（真实检索结果）。参数均取自 rag/ 源码。"""
import os
import sys

from drawkit import Canvas
from style import INK, INK2, INK3, ACCENT, SEQ, ROLE_COLOR, ROLE_ORDER, ROLE_ZH, save
import data as G

sys.path.insert(0, os.path.join(G.REPO, "rag"))
EDGE = "#BDB4A5"


def thin(n):
    return f"{n:,}".replace(",", " ")


# ======================================================================== 图10
def fig_rag_framework():
    from kg_rag import ROLE_WEIGHT, DEFAULT_TOP_SEEDS, DEFAULT_MAX_EDGES, DEFAULT_MAX_CHARS
    D = G.load()
    nq = sum(1 for e in D["edges"] if e["q"].strip())
    c = Canvas(175, 104)
    cols = [
        ("① 查询解析", ["中文字符二元组", "≤6 字短词整串", "西文按词切分", "多轮对话：并入", "上一轮核心实体", "（指代消解）"]),
        ("② 双路召回", None),
        ("③ 种子融合", ["实体 BM25 得分", "+ 佐证命中回流", "  两端实体 0.55w", "+ 实体名整串命中", "  4 + 0.9·|s|", f"同名去重 → Top-{DEFAULT_TOP_SEEDS}"]),
        ("④ 图扩展打分", ["一跳邻域（CSR）", "证据质量 +0.50/+0.16", "来源权重 0.55·ρ(r)", "对端相关 +0.30·ŝ", "枢纽惩罚 −0.12", "待审惩罚 −0.25"]),
        ("⑤ 轮转采样", ["按关系类型分桶", "轮转取样", "单类占比 ≤25%", f"≤{DEFAULT_MAX_EDGES} 条关系", f"≤{thin(DEFAULT_MAX_CHARS)} 字上下文", "[R1]…[Rk] 编号"]),
        ("⑥ 生成与溯源", ["大模型流式生成", "只依据图谱证据", "逐条引用 [Rk]", "区分原创/编纂", "待审信息须注明", "回溯 Dx#cNNNN"]),
    ]
    x0, x1 = 3.0, 172.0
    gap = 3.4
    w = (x1 - x0 - gap * (len(cols) - 1)) / len(cols)
    yh, hh = 14.0, 8.0
    yb, hb = 25.0, 40.0
    for i, (title, lines) in enumerate(cols):
        x = x0 + i * (w + gap)
        hot = i in (3, 4)
        c.box(x, yh, w, hh, title, fc="#FBEDEA" if hot else "#F6F1E7", ec=ACCENT if hot else EDGE,
              lw=0.8 if hot else 0.5, fs=7.6, weight="bold")
        if i:
            c.arrow((x - gap + 0.3, yh + hh / 2), (x - 0.3, yh + hh / 2), color=INK2, lw=0.8, ms=6)
        if lines:
            c.box(x, yb, w, hb, "", fc="white", ec=EDGE, lw=0.5)
            for j, s in enumerate(lines):
                c.text(x + 1.8, yb + 4.2 + j * 6.0, s, fs=6.5, ha="left", color=INK2)
        else:   # 双路索引两个子框
            c.box(x, yb, w, hb / 2 - 1.2, "", fc="white", ec=SEQ, lw=0.6)
            c.text(x + w / 2, yb + 4.0, "实体索引", fs=6.9, weight="bold", color=SEQ)
            c.text(x + w / 2, yb + 9.6, f"{thin(len(D['nodes']))} 实体\n名称·异名·英文·类型", fs=6.2, color=INK2,
                   linespacing=1.25)
            y2 = yb + hb / 2 + 1.2
            c.box(x, y2, w, hb / 2 - 1.2, "", fc="white", ec=ACCENT, lw=0.6)
            c.text(x + w / 2, y2 + 4.0, "佐证索引", fs=6.9, weight="bold", color=ACCENT)
            c.text(x + w / 2, y2 + 9.6, f"{thin(nq)} 条原文引文\n引文+关系+两端实体", fs=6.2, color=INK2, linespacing=1.25)
            c.text(x + w / 2, yb + hb + 2.6, "BM25（k₁=1.5, b=0.75）", fs=6.0, color=INK3)
        if 0 < i:
            c.arrow((x - gap + 0.3, yb + hb / 2), (x - 0.3, yb + hb / 2), color=EDGE, lw=0.6, ms=5)

    # 多轮反馈弧
    xa = x0 + 5 * (w + gap) + w / 2
    xb = x0 + w / 2
    c.poly([(xa, yh - 0.4), (xa, 7.0), (xb, 7.0), (xb, yh - 0.4)], color=INK3, lw=0.6, ms=5, ls=(0, (2, 1.5)))
    c.text((xa + xb) / 2, 5.0, "多轮对话：本轮前 3 个种子实体作为下一轮的焦点实体", fs=6.2, color=INK3,
           bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

    # 打分公式
    yf = 75.0
    c.box(x0, yf, x1 - x0, 11.5, "", fc="#FBF8F2", ec=EDGE, lw=0.5)
    c.text(x0 + 2, yf + 3.6, "关系打分（④）：", fs=6.8, ha="left", weight="bold")
    c.text(x0 + 2, yf + 8.2,
           r"$s(e)=\hat{s}_{seed}+q(e)+0.55\,\rho(r_e)+0.30\,\min(\hat{s}_{o},1)"
           r"-0.12\,\min(\ln(1+d_o)/6,\ 1)-0.25\,\mathbb{1}[\mathrm{flag}]$",
           fs=7.6, ha="left")
    c.text(x1 - 2, yf + 3.6, "q(e)：引文≥10 字 +0.50，4–9 字 +0.16；与实体名重复者 −0.40；d_o：对端实体度",
           fs=6.0, ha="right", color=INK3)

    # 知识来源权重
    yr = 91.0
    c.text(x0 + 2, yr + 3.0, "知识来源权重 ρ(r)：", fs=6.8, ha="left", weight="bold")
    xx = x0 + 30
    for r in ROLE_ORDER:
        c.box(xx, yr + 0.8, 4.2, 4.4, "", fc=ROLE_COLOR[r], ec="none", r=0.6)
        s = f"{ROLE_ZH[r]} {ROLE_WEIGHT[r]:.2f}"
        c.text(xx + 5.4, yr + 3.0, s, fs=6.6, ha="left", color=INK2)
        xx += 5.4 + len(s) * 2.0 + 4.5
    c.text(x1 - 2, yr + 9.5, f"实测：索引构建约 2 s，单次检索中位 3.1 ms（纯 numpy，无向量库 / GPU）",
           fs=6.0, ha="right", color=INK3)
    save(c.fig, "图10_可溯源GraphRAG问答框架")


# ======================================================================== 图11
def fig_evidence_chain():
    from kg_rag import KGRag
    kg = KGRag(G.GRAPH, verbose=False)
    q = "孙光荣“中和组方”的基本原则是什么？"
    r = kg.retrieve(q)
    rows = r.triple_rows()
    focus = "中和组方"
    sel = [row for row in rows if focus in (row[1], row[3])][:8]
    seeds = [(kg.nodes[i]["l"], s) for i, s in r.seeds[:6]]

    H = 16 + len(sel) * 10.6 + 12
    c = Canvas(175, H)
    # 列标题
    heads = [(3, 31, "问题与种子实体"), (34, 106, "检索到的三元组（编号即实际排序）"),
             (109, 152, "原文佐证"), (155, 172, "出处")]
    for xa, xb, t in heads:
        c.text((xa + xb) / 2, 5.0, t, fs=7.4, weight="bold")
        c.ax.plot([xa, xb], [8.2, 8.2], color=INK3, lw=0.5)

    # 问题与种子
    c.box(3, 12, 28, 15, "", fc="#FBEDEA", ec=ACCENT, lw=0.8)
    c.text(17, 19.5, "孙光荣“中和组方”\n的基本原则是什么？", fs=6.9, weight="bold", linespacing=1.3)
    c.text(3.5, 32, "种子实体（得分）", fs=6.4, ha="left", color=INK3)
    for j, (lab, s_) in enumerate(seeds):
        lab2 = lab if len(lab) <= 9 else lab[:8] + "…"
        star = "★" if lab == focus else "·"
        c.text(4, 37 + j * 5.0, f"{star} {lab2}  {s_:.0f}", fs=6.3, ha="left",
               color=ACCENT if lab == focus else INK2, weight="bold" if lab == focus else "normal")

    rel_col = {"思想含治则": ACCENT, "要诀所述": "#7B4AA5", "倡自": INK2}
    cut = lambda x, n: x if len(x) <= n else x[:n - 1] + "…"
    y0 = 13.0
    chunks = []
    X2 = 34.0
    for j, row in enumerate(sel):
        y = y0 + j * 10.6
        rid, s_, rel, t, quote, cid, role = row[:7]
        col = rel_col.get(rel, INK2)
        c.box(X2, y, 72, 8.2, "", fc="white", ec=EDGE, lw=0.5)
        c.text(X2 + 1.6, y + 4.1, f"[{rid}]", fs=6.6, ha="left", weight="bold", color=SEQ)
        c.text(X2 + 10.0, y + 4.1, cut(s_, 10), fs=6.5, ha="left")
        c.text(X2 + 40.0, y + 2.4, rel, fs=5.8, color=col)
        c.arrow((X2 + 34.0, y + 4.9), (X2 + 46.0, y + 4.9), color=col, lw=0.7, ms=4.5, z=6)
        c.text(X2 + 47.5, y + 4.1, cut(t, 10), fs=6.5, ha="left")
        qq = cut(quote, 36)
        lines = [qq[:18], qq[18:]] if len(qq) > 18 else [qq]
        c.box(109, y, 43, 8.2, "", fc="#FBF8F2", ec=EDGE, lw=0.5)
        c.text(110.2, y + 4.1, "「" + "\n".join(lines) + "」", fs=6.1, ha="left", color=INK2, linespacing=1.2)
        c.arrow((106.3, y + 4.1), (108.7, y + 4.1), color=INK3, lw=0.5, ms=4, z=6)
        chunks.append((y + 4.1, cid))
    # 出处汇聚
    cids = sorted({cid for _, cid in chunks})
    ymid = {}
    for k, cid in enumerate(cids):
        ys = [y for y, cc in chunks if cc == cid]
        ymid[cid] = sum(ys) / len(ys)
    for cid in cids:
        yy = ymid[cid]
        c.box(155.5, yy - 10, 16.5, 20, "", fc="#FBEDEA", ec=ACCENT, lw=0.8)
        c.text(163.75, yy - 5.2, cid, fs=6.6, weight="bold", color=ACCENT)
        c.text(163.75, yy + 2.6, "《国医大师\n孙光荣中和思想\n与临证经验\n集萃》", fs=5.5, color=INK2, linespacing=1.15)
    for y, cid in chunks:
        c.arrow((152.3, y), (155.3, ymid[cid] + (y - ymid[cid]) * 0.15), color=ACCENT, lw=0.5, ms=4,
                rad=0.0)
    yb = y0 + len(sel) * 10.6 + 2.0
    c.text(3, yb + 3.0,
           f"本例：{len(r.seeds)} 个种子实体、{len(r.edges)} 条关系进入上下文；其中与种子“{focus}”直接相连的 {len(sel)} 条"
           f"全部出自同一文本块 {'、'.join(cids)}，答案中的引用可逐条回溯至原文。",
           fs=6.3, ha="left", color=INK2)
    c.text(3, yb + 8.0,
           "生成约束（rag/app.py 系统提示）：只依据图谱证据作答，引用标注 [Rk] 并给出出处编号，区分孙老原创与编纂，"
           "未见记载须明确说明。", fs=6.3, ha="left", color=INK2)
    save(c.fig, "图11_可溯源证据链示例")
    return sel


if __name__ == "__main__":
    import style
    style.setup()
    fig_rag_framework()
    fig_evidence_chain()
