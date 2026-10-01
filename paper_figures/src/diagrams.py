# -*- coding: utf-8 -*-
"""框架类示意图：图1 技术路线、图2 本体模型、图9 可溯源 GraphRAG 框架。"""
from collections import Counter

from drawkit import Canvas
from style import INK, INK2, INK3, ACCENT, SEQ, ROLE_COLOR, ROLE_ORDER, ROLE_ZH, SANS, save
import data as G

BAND = ["#F6F1E7", "#FBF8F2"]          # 分层底色（宣纸色两阶交替）
EDGE = "#BDB4A5"


def fmt(n):
    """GB/T 15835：四位以上数字三位一节，节间留空（此处用窄空格）。"""
    s = f"{n:,}"
    return s.replace(",", " ")


# ======================================================================== 图1
def fig_framework():
    D = G.load()
    E, N = D["edges"], D["nodes"]
    rel_by_doc = Counter(e["d"] for e in E)
    chunks = len({e["c"] for e in E})
    flagged = sum(e["Q"] for e in E)
    au = D["meta"]["audit"]

    W, H = 175, 134
    c = Canvas(W, H)
    x0, x1 = 17.5, 173.5
    rows = [
        ("文献数据", 3, 26),
        ("本体建模", 31, 22),
        ("抽取融合", 57, 22),
        ("质控存储", 83, 22),
        ("溯源问答", 109, 23),
    ]
    for k, (name, y, h) in enumerate(rows):
        c.rect(1.5, y, W - 3, h, fc=BAND[k % 2], z=0)
        c.box(2.5, y + 1, 12.5, h - 2, "", fc="#FFFFFF", ec=EDGE, lw=0.5, r=1.0)
        c.text(8.75, y + h / 2, "\n".join(name), fs=8, weight="bold",
               color=INK, linespacing=1.15)

    # ---- ① 文献数据层 ----
    docs = list(G.DOC_SHORT.items())
    bw, gap = (x1 - x0 - 3 * 1.8) / 4, 1.8
    for i, (k, v) in enumerate(docs):
        r, col = divmod(i, 4)
        bx, by = x0 + col * (bw + gap), 4.6 + r * 7.2
        own = k in ("D1", "D2", "D3")
        c.box(bx, by, bw, 6.0, f"{k} {v}", fc="#FFFFFF", ec=ACCENT if own else EDGE,
              lw=0.8 if own else 0.5, fs=6.6)
    c.box(x0, 19.4, x1 - x0, 6.0,
          f"段落级文本切分与编号（Dx#cNNNN）：{fmt(chunks)} 个文本块，作为最小溯源单元（红框为中和学术思想核心文献）",
          fc="#FFFFFF", ec=INK3, fs=6.9)

    # ---- ② 本体建模层 ----
    y = 33
    items = [
        ("六层本体框架", "中和思想 · 辨证论治 · 方药配伍\n医案诊次 · 养生康复 · 传承溯源", 40),
        ("概念类型", f"31 类实体（30 类已实例化）\n中英双语命名 + 异名", 33),
        ("关系类型", "44 类关系\n含定义域 / 值域约束", 27),
        ("知识来源（溯源属性）", "孙光荣原创 · 孙光荣编纂 · 经典引文\n他人临床报道 · 中医通识", 47.6),
    ]
    bx = x0
    for t, s, w in items:
        c.box(bx, y, w, 18, "", fc="#FFFFFF", ec=EDGE, lw=0.5)
        c.text(bx + w / 2, y + 4.2, t, fs=7.2, weight="bold")
        c.text(bx + w / 2, y + 11.6, s, fs=6.5, color=INK2, linespacing=1.35)
        bx += w + 2.8
    # 知识来源五色点
    for k, rk in enumerate(ROLE_ORDER):
        pass

    # ---- ③ 知识抽取与融合层 ----
    y = 60
    steps = ["实体识别\n与类型判定", "关系抽取\n（本体约束）", "原文佐证绑定\n引文 q + 出处 c",
             "实体对齐\n异名归并", "知识来源\n角色标注"]
    sw = (x1 - x0 - 4 * 5.0) / 5
    for i, s in enumerate(steps):
        bx = x0 + i * (sw + 5.0)
        c.box(bx, y, sw, 16, s, fc="#FFFFFF", ec=EDGE, lw=0.5, fs=7.0)
        if i:
            c.arrow((bx - 4.4, y + 8), (bx - 0.5, y + 8), color=INK2, lw=0.7)
    c.text(x1, y + 18.6, f"异名 {fmt(sum(len(n['a']) for n in N))} 条 · 跨文献共现实体 {fmt(sum(1 for n in N if len(n['d']) > 1))} 个"
           f" · 带原文佐证关系 {fmt(sum(1 for e in E if e['q'].strip()))} 条（{sum(1 for e in E if e['q'].strip())/len(E):.2%}）",
           fs=6.0, color=INK3, ha="right")

    # ---- ④ 质量控制与存储层 ----
    y = 85.5
    q_items = [
        ("本体一致性校验", f"定义域/值域不符者标记“待审”\n{fmt(flagged)} 条（{flagged/len(E):.1%}）", 36),
        ("专家抽样审校", f"v1 严格精度 {au['v1_strict']:.1%}（n={au['v1_n']}）\nv2 严格精度 {au['v2_strict']:.1%}（n={au['v2_n']}）", 36),
        ("属性图存储", f"{fmt(len(N))} 个实体 · {fmt(len(E))} 条关系\nJSON 属性图 + CSR 邻接索引", 40),
        ("可视化发布", "ForceAtlas2 + Barnes-Hut 离线布局\n离线 Android 应用 · 桌面浏览器", 38.4),
    ]
    bx = x0
    for t, s, w in q_items:
        c.box(bx, y, w, 17, "", fc="#FFFFFF", ec=EDGE, lw=0.5)
        c.text(bx + w / 2, y + 4.0, t, fs=7.2, weight="bold")
        c.text(bx + w / 2, y + 11.0, s, fs=6.4, color=INK2, linespacing=1.35)
        bx += w + 2.0

    # ---- ⑤ 问答层 ----
    y = 112
    qa = ["用户问题", "双路 BM25 召回\n实体 / 佐证索引", "一跳图扩展\n证据加权打分", "关系类型\n轮转采样",
          "编号上下文\n[Rk] + 出处", "大模型生成\n逐条引用", "原文回溯\nDx#cNNNN"]
    ws = [14, 23.5, 22, 18.5, 21, 20, 19]
    gap = (x1 - x0 - sum(ws)) / (len(ws) - 1)
    bx = x0
    for i, (s, w) in enumerate(zip(qa, ws)):
        hi = i in (0, 6)
        c.box(bx, y, w, 13.5, s, fc="#FFFFFF", ec=ACCENT if hi else EDGE, lw=0.8 if hi else 0.5,
              fs=6.8, weight="bold" if hi else "normal")
        if i:
            c.arrow((bx - gap + 0.4, y + 6.75), (bx - 0.4, y + 6.75), color=INK2, lw=0.7)
        bx += w + gap
    c.text(x1, y + 16.6, "纯 numpy 实现 · 无需向量库与 GPU · 回答中的每条论断可回溯至原文文本块",
           fs=6.0, color=INK3, ha="right")

    # ---- 层间箭头 ----
    for ya, yb in ((26.6, 30.6), (52.6, 56.6), (78.6, 82.6), (104.6, 108.6)):
        c.arrow(((x0 + x1) / 2, ya), ((x0 + x1) / 2, yb), color=ACCENT, lw=1.1, ms=8)
    save(c.fig, "图1_研究技术路线")


if __name__ == "__main__":
    import style
    style.setup()
    fig_framework()
