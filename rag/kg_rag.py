# -*- coding: utf-8 -*-
"""
国医大师孙光荣中医知识图谱 · 检索增强（GraphRAG）引擎
Sun Guangrong TCM Knowledge Graph — retrieval engine for RAG

研发：孙光荣大师弟子田建辉团队 联合 医哲未来人工智能研究院（IMPF-AI Institute）

设计要点
--------
1. 双路召回：实体索引（名称/异名/英文/类型）+ 原文佐证索引（边上的 q 字段）。
   中医术语高度专名化，佐证原文往往就是答案本身，两路互补。
2. 中文用字符二元组做 BM25，不依赖分词器；再叠加「实体名整串命中」的强加权。
3. 图扩展：以命中实体为种子取 1 跳邻域，按「有无原文佐证 / 知识来源 / 种子得分」排序，
   得到一个可解释的子图，而不是一堆散落的文本块。
4. 组装上下文时给每条关系编号 [R1][R2]…，并保留出处编号（如 D3#c0037），
   让模型可以逐条引用、可溯源。
"""

from __future__ import annotations

import html
import json
import math
import os
import re
from collections import defaultdict

import numpy as np

# ---------------------------------------------------------------- 配色（与 App 一致）
ROLE_COLOR = {
    "sun_original":       "#B03A30",   # 朱砂 · 孙光荣原创
    "sun_compiled":       "#B5802C",   # 藤黄 · 孙光荣编纂
    "classical_source":   "#2E5C86",   # 靛青 · 经典引文
    "third_party_clinical": "#4A7A46",  # 竹青 · 他人临床报道
    "general_tcm":        "#7E6F5C",   # 墨灰 · 中医通识
}
ROLE_WEIGHT = {           # 检索排序时的知识来源优先级
    "sun_original": 1.00, "sun_compiled": 0.72, "classical_source": 0.60,
    "third_party_clinical": 0.50, "general_tcm": 0.42,
}

_TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z][A-Za-z0-9\-'.]*|\d+")

# 检索默认档位（界面与笔记本的滑杆初值都取这里）
DEFAULT_TOP_SEEDS = 35
DEFAULT_MAX_EDGES = 120
DEFAULT_MAX_NODES = 140
DEFAULT_MAX_CHARS = 9900


def tokenize(text: str):
    """中文切字符二元组，西文按词。二元组对中医专名的召回明显好过单字。"""
    out = []
    for m in _TOKEN_RE.finditer(text or ""):
        s = m.group(0)
        if "一" <= s[0] <= "鿿":
            if len(s) == 1:
                out.append(s)
            else:
                out.extend(s[i:i + 2] for i in range(len(s) - 1))
                if len(s) <= 6:          # 短词整串也作为一个 token，提升精确度
                    out.append(s)
        else:
            out.append(s.lower())
    return out


class BM25:
    """稀疏倒排 + BM25，纯 numpy，无第三方依赖。"""

    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.N = len(docs)
        self.doc_len = np.zeros(self.N, dtype=np.float32)
        post = defaultdict(lambda: ([], []))
        for i, toks in enumerate(docs):
            self.doc_len[i] = len(toks)
            tf = defaultdict(int)
            for t in toks:
                tf[t] += 1
            for t, c in tf.items():
                ids, cnts = post[t]
                ids.append(i)
                cnts.append(c)
        self.avgdl = float(self.doc_len.mean()) if self.N else 1.0
        self.post = {}
        self.idf = {}
        for t, (ids, cnts) in post.items():
            self.post[t] = (np.asarray(ids, dtype=np.int32), np.asarray(cnts, dtype=np.float32))
            df = len(ids)
            self.idf[t] = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def score(self, q_tokens):
        acc = np.zeros(self.N, dtype=np.float32)
        seen = set()
        for t in q_tokens:
            if t in seen or t not in self.post:
                continue
            seen.add(t)
            ids, tf = self.post[t]
            denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[ids] / self.avgdl)
            acc[ids] += self.idf[t] * (tf * (self.k1 + 1) / denom)
        return acc


# ---------------------------------------------------------------- 数据装载
def load_graph(path: str) -> dict:
    """支持两种输入：烘焙好的 graph.json，或原始的 *_explorer.html（自动抽取）。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if path.lower().endswith((".html", ".htm")):
        src = open(path, encoding="utf-8").read()
        i = src.index("const DATA = ")
        j = src.index("\nconst RC =")
        return json.loads(src[i + len("const DATA = "):j].rstrip().rstrip(";"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Retrieval:
    """一次检索的结果：种子实体、子图实体、关系列表，以及组装好的上下文。"""

    def __init__(self, query, seeds, nodes, edges, kg):
        self.query = query
        self.seeds = seeds          # [(node_id, score)]
        self.nodes = nodes          # [node_id]  已按得分排序
        self.edges = edges          # [(edge_idx, score)]
        self.kg = kg

    def __len__(self):
        return len(self.edges)

    # -------- 表格（供 Gradio / notebook 展示） --------
    def entity_rows(self):
        kg = self.kg
        rows = []
        seed_ids = {i for i, _ in self.seeds}
        for nid in self.nodes:
            n = kg.nodes[nid]
            rows.append([
                "★" if nid in seed_ids else "",
                n["l"],
                kg.type_zh.get(n["t"], n["t"]),
                kg.role_zh.get(n["r"], n["r"]),
                "、".join(n.get("d") or []) or "—",
                int(n.get("g", kg.degree[nid])),
                (n.get("e") or "")[:70],
            ])
        return rows

    ENTITY_HEADERS = ["种子", "实体", "类型", "知识来源", "出处", "关联度", "英文"]

    def triple_rows(self):
        kg = self.kg
        rows = []
        for k, (ei, _) in enumerate(self.edges, 1):
            e = kg.edges[ei]
            rows.append([
                f"R{k}",
                kg.nodes[e["s"]]["l"],
                kg.rel_zh.get(e["y"], e["y"]),
                kg.nodes[e["t"]]["l"],
                (e.get("q") or "").strip() or "—",
                (e.get("c") or e.get("d") or "—"),
                kg.role_zh.get(e.get("r"), e.get("r") or "—"),
                "待审" if e.get("Q") else "",
            ])
        return rows

    TRIPLE_HEADERS = ["编号", "主语", "关系", "宾语", "原文佐证", "出处编号", "知识来源", "标记"]

    # -------- 送入模型的上下文 --------
    def context(self, max_chars=DEFAULT_MAX_CHARS):
        kg = self.kg
        if not self.nodes:
            return "（图谱中未检索到与该问题直接相关的实体。）"

        # 实体与关系分账，防止实体清单把关系挤掉（种子放大到 35 后尤其重要）
        ent_budget = int(max_chars * 0.34)
        buf = ["以下是从《国医大师孙光荣中医知识图谱》检索到的知识片段，"
               f"共 {len(self.nodes)} 个实体、{len(self.edges)} 条关系。\n"]

        buf.append("〖实体〗")
        seed_ids = {i for i, _ in self.seeds}
        used = 0
        for nid in self.nodes:
            n = kg.nodes[nid]
            mark = "★" if nid in seed_ids else "·"
            line = (f"{mark} {n['l']}"
                    f"（{kg.type_zh.get(n['t'], n['t'])}；{kg.role_zh.get(n['r'], n['r'])}）")
            if n.get("e"):
                line += f" [{n['e'][:80]}]"
            docs = n.get("d") or []
            if docs:
                line += "；出处 " + "、".join(f"{d}《{kg.docs.get(d, '')}》" for d in docs[:3])
            if n.get("a"):
                line += "；异名 " + "、".join(n["a"][:4])
            buf.append(line)
            used += len(line)
            if used > ent_budget:
                remain = len(self.nodes) - len(buf) + 2
                if remain > 0:
                    buf.append(f"…（另有 {remain} 个相关实体见下方关系）")
                break

        buf.append("\n〖关系与原文佐证〗")
        # "\n".join 每段还会多一个换行，末尾省略说明也要预留，一并算进来
        used = sum(len(x) for x in buf) + len(buf)
        TAIL = 40
        for k, (ei, _) in enumerate(self.edges, 1):
            e = kg.edges[ei]
            s, t = kg.nodes[e["s"]]["l"], kg.nodes[e["t"]]["l"]
            rel = kg.rel_zh.get(e["y"], e["y"])
            seg = f"[R{k}] {s} —（{rel}）→ {t}"
            q = (e.get("q") or "").strip()
            if q:
                seg += f"\n      佐证：「{q[:220]}」"
            src = e.get("c") or e.get("d")
            if src:
                seg += f"\n      出处：{src}"
                if e.get("d") and kg.docs.get(e["d"]):
                    seg += f"《{kg.docs[e['d']]}》"
                seg += f"（{kg.role_zh.get(e.get('r'), e.get('r') or '')}）"
            if e.get("Q"):
                seg += "  ⚑ 该关系未通过本体校验，仅供参考"
            # 先算再放，保证总字数不越过上限（越界的那条整条不要）
            if used + len(seg) + 1 + TAIL > max_chars and k > 1:
                buf.append(f"…（其余 {len(self.edges) - k + 1} 条关系因篇幅省略）")
                break
            buf.append(seg)
            used += len(seg) + 1

        return "\n".join(buf)

    # -------- 子图 SVG（国风配色，无外部依赖） --------
    #
    # 标签重叠是这类图最伤可读性的问题。这里的做法是：把「圆点 + 标签」当成一个
    # 矩形来布局，力导向收敛后再跑一遍矩形去重叠松弛（PRISM 思路），
    # 于是标签天然不会互相压住。画布尺寸按所有矩形的总面积反推，节点多就自动变大。
    def svg(self, width=None, height=None, theme="paper",
            max_nodes=140, max_labels=44, scroll=True):
        kg = self.kg
        ids = self.nodes[:max_nodes]
        if not ids:
            return ("<div style='padding:28px;text-align:center;color:#7C6C58'>"
                    "暂无检索结果</div>")

        idx = {nid: i for i, nid in enumerate(ids)}
        n = len(ids)
        pairs = []
        for ei, _ in self.edges:
            e = kg.edges[ei]
            a, b = idx.get(e["s"]), idx.get(e["t"])
            if a is not None and b is not None and a != b:
                pairs.append((a, b, kg.rel_zh.get(e["y"], e["y"])))

        bg, fg, sub = (("#F1E6D1", "#241C15", "#7C6C58") if theme == "paper"
                       else ("#131009", "#EDE3D0", "#93866F"))
        seed_ids = {i for i, _ in self.seeds}

        # ---- 1. 谁配标签：种子优先，其余按关联度，给定预算 ----
        order = sorted(range(n), key=lambda i: (ids[i] not in seed_ids,
                                                -int(kg.degree[ids[i]])))
        labeled = set(order[:max_labels])

        # ---- 2. 每个节点的矩形（圆点 + 其下方的标签）----
        def text_w(s, fs):
            return sum(fs if ch > "\u2e7f" else fs * 0.56 for ch in s)

        maxchars = 12 if n <= 40 else (10 if n <= 90 else 8)
        radius = np.empty(n, dtype=np.float64)
        halfw = np.empty(n, dtype=np.float64)
        halfh = np.empty(n, dtype=np.float64)
        labels, fontsz = [], np.zeros(n)
        for i, nid in enumerate(ids):
            is_seed = nid in seed_ids
            deg = int(kg.degree[nid])
            radius[i] = (7.5 if is_seed else 3.6) + min(deg ** 0.35, 3.4)
            if i in labeled:
                raw = kg.nodes[nid]["l"]
                lab = raw[:maxchars] + ("…" if len(raw) > maxchars else "")
                fs = 11.5 if is_seed else 10.0
                labels.append(lab)
                fontsz[i] = fs
                halfw[i] = max(radius[i], text_w(lab, fs) / 2) + 3.5
                halfh[i] = radius[i] + fs + 4.5
            else:
                labels.append("")
                halfw[i] = radius[i] + 2.5
                halfh[i] = radius[i] + 2.5

        # ---- 3. 力导向（Fruchterman-Reingold）----
        box_area = float((4 * halfw * halfh).sum())
        canvas = box_area / 0.20                          # 0.20 ≈ 带标签时实际可达的填充率
        est_w = math.sqrt(canvas * 1.35)                  # 先给力导向一个大致的场地尺度
        rng = np.random.default_rng(11)
        ang = np.arange(n) * 2.399963                      # 黄金角螺旋，起始分布更均匀
        rad = np.sqrt(np.arange(n) + 0.5) * (est_w / (3.2 * math.sqrt(n)))
        pos = np.stack([np.cos(ang) * rad, np.sin(ang) * rad], 1)
        pos += rng.normal(0, 1.5, (n, 2))

        E = (np.array([[a, b] for a, b, _ in pairs], dtype=np.int32)
             if pairs else np.zeros((0, 2), np.int32))
        k = math.sqrt(canvas / max(n, 1)) * 0.62
        temp = est_w * 0.08
        ITERS = 260
        for it in range(ITERS):
            d = pos[:, None, :] - pos[None, :, :]
            dist2 = d[..., 0] ** 2 + d[..., 1] ** 2 + 1e-3
            coef = (k * k) / dist2                          # 斥力 ~ k²/d，方向 d/|d|
            np.fill_diagonal(coef, 0.0)
            disp = np.einsum("ij,ijk->ik", coef, d)
            if len(E):
                dv = pos[E[:, 1]] - pos[E[:, 0]]
                dd = np.hypot(dv[:, 0], dv[:, 1])[:, None] + 1e-6
                att = dv * (dd / k)                         # 引力 ~ d²/k
                np.add.at(disp, E[:, 0], att)
                np.add.at(disp, E[:, 1], -att)
            disp -= pos * 0.035 * (1 + 2 * it / ITERS)       # 重力，后期收紧防飘散
            norm = np.hypot(disp[:, 0], disp[:, 1])[:, None] + 1e-9
            pos += disp / norm * np.minimum(norm, temp)
            temp *= 0.985

        # ---- 4. 定画布：让长宽比贴合版面实际形状，避免一侧大片留白 ----
        pad = 10.0
        legend_h = 46                            # 底部图例条，单独占用不与节点争位
        lo = (pos - np.stack([halfw, halfh], 1)).min(0)
        hi = (pos + np.stack([halfw, halfh], 1)).max(0)
        span = np.maximum(hi - lo, 1e-6)
        if width is None:
            ar = float(np.clip(span[0] / span[1], 0.85, 2.0))
            width = int(np.clip(math.sqrt(canvas * ar), 520, 1380))
        if height is None:
            height = int(np.clip(canvas / max(width, 1), 340, 1100)) + legend_h
        plot_h = height - legend_h

        # ---- 5. 归一到画布并居中 ----
        scale = min((width - 2 * pad) / span[0], (plot_h - 2 * pad) / span[1])
        pos = (pos - lo) * scale
        pos[:, 0] += (width - span[0] * scale) / 2
        pos[:, 1] += (plot_h - span[1] * scale) / 2
        # 盒子不随位置缩放（字号是固定的），所以缩小后要靠松弛重新腾地方

        # ---- 6. 矩形去重叠松弛：标签不再互相压住的关键 ----
        for it in range(180):
            dx = pos[:, 0][:, None] - pos[:, 0][None, :]
            dy = pos[:, 1][:, None] - pos[:, 1][None, :]
            ox = (halfw[:, None] + halfw[None, :]) - np.abs(dx)
            oy = (halfh[:, None] + halfh[None, :]) - np.abs(dy)
            hit = (ox > 0) & (oy > 0)
            np.fill_diagonal(hit, False)
            if not hit.any():
                break
            sx = np.where(dx >= 0, 1.0, -1.0)
            sy = np.where(dy >= 0, 1.0, -1.0)
            along_x = hit & (ox <= oy)                       # 沿穿透较浅的轴推开
            along_y = hit & (ox > oy)
            push = np.stack([
                np.where(along_x, sx * ox * 0.5, 0.0).sum(1),
                np.where(along_y, sy * oy * 0.5, 0.0).sum(1),
            ], 1)
            pos += push * 0.55
            np.clip(pos[:, 0], halfw + pad * 0.4, width - halfw - pad * 0.4, out=pos[:, 0])
            np.clip(pos[:, 1], halfh + pad * 0.4, plot_h - halfh - pad * 0.4, out=pos[:, 1])
        # 提前收敛跳出循环时也要保证在界内
        np.clip(pos[:, 0], halfw + pad * 0.4, width - halfw - pad * 0.4, out=pos[:, 0])
        np.clip(pos[:, 1], halfh + pad * 0.4, plot_h - halfh - pad * 0.4, out=pos[:, 1])

        # ---- 7. 出图 ----
        out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
               'viewBox="0 0 %d %d" style="background:%s;border-radius:4px;display:block">'
               % (width, height, width, height, bg)]

        out.append('<g stroke="%s" stroke-opacity="0.34" stroke-width="1" fill="none">' % sub)
        for a, b, rel in pairs:
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"><title>%s</title></line>'
                       % (pos[a, 0], pos[a, 1], pos[b, 0], pos[b, 1], html.escape(rel)))
        out.append("</g>")

        for i, nid in enumerate(ids):
            nd = kg.nodes[nid]
            is_seed = nid in seed_ids
            col = ROLE_COLOR.get(nd["r"], "#7E6F5C")
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"%s><title>%s</title></circle>'
                       % (pos[i, 0], pos[i, 1], radius[i], col,
                          ' stroke="%s" stroke-width="2.2"' % bg if is_seed else "",
                          html.escape("%s（%s · %s）" % (
                              nd["l"], kg.type_zh.get(nd["t"], nd["t"]),
                              kg.role_zh.get(nd["r"], nd["r"])))))

        # 标签统一画在圆点正下方，配同背景色描边做「光晕」，压住穿过的连线
        for i in range(n):
            if not labels[i]:
                continue
            fs = fontsz[i]
            out.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="%s" text-anchor="middle" '
                       'stroke="%s" stroke-width="2.6" paint-order="stroke" stroke-linejoin="round" '
                       'font-family="Noto Serif CJK SC,Songti SC,serif"%s>%s</text>'
                       % (pos[i, 0], pos[i, 1] + radius[i] + fs + 0.5, fs, fg, bg,
                          ' font-weight="600"' if ids[i] in seed_ids else "",
                          html.escape(labels[i])))

        # 图例
        legend = [("sun_original", "孙光荣原创"), ("sun_compiled", "孙光荣编纂"),
                  ("classical_source", "经典引文"), ("third_party_clinical", "他人临床报道"),
                  ("general_tcm", "中医通识")]
        lx, ly = 10, plot_h + 20
        out.append('<g font-size="10" font-family="Noto Sans CJK SC,sans-serif" fill="%s" '
                   'opacity="0.88">' % sub)
        cx = lx + 4
        for rk, zh in legend:
            out.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (cx, ly, ROLE_COLOR[rk]))
            out.append('<text x="%.1f" y="%.1f">%s</text>' % (cx + 9, ly + 3.5, zh))
            cx += 9 + len(zh) * 10 + 20
        out.append('<text x="%d" y="%.1f" font-style="italic">● 描边者为检索种子　共 %d 实体 / %d 关系</text>'
                   % (lx, plot_h + 12, n, len(pairs)))
        out.append("</g></svg>")

        svg = "".join(out)
        if scroll:
            svg = ("<div style='overflow:auto;max-width:100%;max-height:560px;"
                   "border:1px solid rgba(36,28,21,.15);border-radius:4px'>" + svg + "</div>")
        return svg



class KGRag:
    """图谱索引 + 检索。构建一次，反复查询。"""

    def __init__(self, graph_or_path, verbose=True):
        D = load_graph(graph_or_path) if isinstance(graph_or_path, str) else graph_or_path
        self.data = D
        self.nodes = D["nodes"]
        self.edges = D["edges"]
        self.type_zh = {k: v["zh"] for k, v in D["types"].items()}
        self.rel_zh = {k: v["zh"] for k, v in D["rels"].items()}
        self.role_zh = {k: v["zh"] for k, v in D["roles"].items()}
        self.docs = dict(D["docs"])

        n, m = len(self.nodes), len(self.edges)

        # 度与 CSR 邻接（存边号）
        deg = np.zeros(n, dtype=np.int32)
        for e in self.edges:
            deg[e["s"]] += 1
            deg[e["t"]] += 1
        self.degree = deg
        start = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(deg, out=start[1:])
        adj = np.zeros(int(start[-1]), dtype=np.int32)
        cur = start[:-1].copy()
        for k, e in enumerate(self.edges):
            adj[cur[e["s"]]] = k; cur[e["s"]] += 1
            adj[cur[e["t"]]] = k; cur[e["t"]] += 1
        self.adj_start, self.adj = start, adj

        # 实体索引
        node_docs = []
        self.surface = {}                     # 实体名 / 异名 → node id
        for i, nd in enumerate(self.nodes):
            parts = [nd["l"], nd.get("e") or "", self.type_zh.get(nd["t"], "")]
            parts += list(nd.get("a") or [])
            node_docs.append(tokenize(" ".join(parts)))
            for s in [nd["l"]] + list(nd.get("a") or []):
                s = (s or "").strip()
                if len(s) >= 2:
                    self.surface.setdefault(s, i)
        self.node_bm25 = BM25(node_docs)

        # 原文佐证索引（只索引真正带引文的边）
        self.quote_eid = []
        quote_docs = []
        for k, e in enumerate(self.edges):
            q = (e.get("q") or "").strip()
            if not q:
                continue
            self.quote_eid.append(k)
            quote_docs.append(tokenize(
                q + " " + self.rel_zh.get(e["y"], "") + " "
                + self.nodes[e["s"]]["l"] + " " + self.nodes[e["t"]]["l"]))
        self.quote_bm25 = BM25(quote_docs)
        self.quote_eid = np.asarray(self.quote_eid, dtype=np.int32)

        if verbose:
            print(f"✔ 图谱索引就绪：{n:,} 实体 · {m:,} 关系 · "
                  f"{len(self.quote_eid):,} 条带原文佐证 · "
                  f"{len(self.docs)} 部文献 · {len(self.type_zh)} 类实体 · {len(self.rel_zh)} 类关系")

    # ------------------------------------------------------------------ 检索
    def retrieve(self, query, focus_entities=(), top_seeds=DEFAULT_TOP_SEEDS,
                 max_edges=DEFAULT_MAX_EDGES, max_nodes=DEFAULT_MAX_NODES) -> Retrieval:
        q_text = query if not focus_entities else query + " " + " ".join(focus_entities)
        toks = tokenize(q_text)

        node_score = self.node_bm25.score(toks).astype(np.float32)

        # 佐证原文命中 → 回流到两端实体，同时记住直接命中的边
        direct_edges = {}
        if len(self.quote_eid):
            qs = self.quote_bm25.score(toks)
            if qs.max() > 0:
                top_q = np.argpartition(-qs, min(60, len(qs) - 1))[:60]
                top_q = top_q[np.argsort(-qs[top_q])]
                mx = float(qs[top_q[0]]) or 1.0
                for j in top_q:
                    if qs[j] <= 0:
                        break
                    ei = int(self.quote_eid[j])
                    e = self.edges[ei]
                    w = float(qs[j])
                    node_score[e["s"]] += 0.55 * w
                    node_score[e["t"]] += 0.55 * w
                    direct_edges[ei] = 0.9 * w / mx

        # 实体名整串出现在问题里 → 强加权（中医专名往往可精确匹配）
        for surf, nid in self.surface.items():
            if surf in q_text:
                node_score[nid] += 4.0 + 0.9 * len(surf)

        if node_score.max() <= 0:
            return Retrieval(query, [], [], [], self)

        k = min(top_seeds * 4, len(node_score) - 1)
        cand = np.argpartition(-node_score, k)[:k + 1]
        cand = cand[np.argsort(-node_score[cand])]
        # 同名实体（不同文献里的同一概念）只留分最高的一个，把种子名额让给别的概念
        seeds, seen_label = [], set()
        for i in cand:
            if node_score[i] <= 0:
                continue
            lab = self.nodes[int(i)]["l"]
            if lab in seen_label:
                continue
            seen_label.add(lab)
            seeds.append((int(i), float(node_score[i])))
            if len(seeds) >= top_seeds:
                break
        if not seeds:
            return Retrieval(query, [], [], [], self)
        top_score = seeds[0][1] or 1.0

        # 1 跳扩展：按「佐证质量 / 知识来源 / 种子得分 / 对端得分」打分。
        # 枢纽实体（如「失眠」）往往挂着几十条同类型关系，若不加约束，
        # 检索结果会被「见症→失眠」这类重复三元组塞满，因此对每个种子
        # 按关系类型做配额，逼出「主治 / 功效 / 辨证为 / 出典」等不同侧面。
        edge_score = {}
        per_seed_cap = max(6, max_edges // max(1, len(seeds)))
        per_type_cap = 3
        for nid, sc in seeds:
            picked = []
            for p in range(self.adj_start[nid], self.adj_start[nid + 1]):
                ei = int(self.adj[p])
                e = self.edges[ei]
                other = e["t"] if e["s"] == nid else e["s"]
                q = (e.get("q") or "").strip()
                s = (sc / top_score) * 1.0
                # 只有实质性的引文才算佐证；「紫河车9g」这类等同于标签，几乎没有信息量
                s += 0.50 if len(q) >= 10 else (0.16 if len(q) >= 4 else 0.0)
                # 佐证原文若只是把实体名重抄一遍（如「见症→失眠」佐证写作「失眠」），
                # 对回答毫无增量，压到后面去
                if len(q) < 8 and (q in self.nodes[other]["l"] or q in self.nodes[nid]["l"]):
                    s -= 0.40
                s += 0.55 * ROLE_WEIGHT.get(e.get("r"), 0.4)
                s += 0.30 * min(node_score[other] / top_score, 1.0)
                s -= 0.12 * min(math.log1p(self.degree[other]) / 6.0, 1.0)
                if e.get("Q"):
                    s -= 0.25
                picked.append((s, ei, e["y"]))
            picked.sort(key=lambda x: -x[0])

            type_used, taken, spill = defaultdict(int), 0, []
            for s, ei, y in picked:
                if taken >= per_seed_cap:
                    break
                if type_used[y] >= per_type_cap:
                    spill.append((s, ei))
                    continue
                type_used[y] += 1
                taken += 1
                edge_score[ei] = max(edge_score.get(ei, 0.0), s)
            for s, ei in spill[:max(0, per_seed_cap - taken)]:      # 配额没用满再回填
                edge_score[ei] = max(edge_score.get(ei, 0.0), s - 0.3)

        for ei, s in direct_edges.items():                 # 佐证直接命中的边一定保留
            edge_score[ei] = max(edge_score.get(ei, 0.0), s + 1.2)

        # 最终排序：先去掉字面重复的三元组，再按关系类型分桶做轮转取样。
        # 硬配额挡不住「失眠」这种被多个同义种子共同放大的类型——超额的部分
        # 回填时又会把名额抢回去；轮转取样则天然保证各个侧面都有位置，
        # 而在关系类型本来就少的时候又能自动退化成纯按分排序。
        buckets, seen_sig = defaultdict(list), set()
        for ei, sc_e in sorted(edge_score.items(), key=lambda kv: -kv[1]):
            e = self.edges[ei]
            sig = (e["y"], self.nodes[e["s"]]["l"], self.nodes[e["t"]]["l"], (e.get("q") or "")[:24])
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            buckets[e["y"]].append((ei, sc_e))

        order_types = sorted(buckets, key=lambda y: -buckets[y][0][1])
        bucket_cap = max(3, max_edges // 4)      # 单一关系类型最多占四分之一
        chosen, round_i = [], 0
        while len(chosen) < max_edges and round_i < bucket_cap:
            progressed = False
            for y in order_types:
                if round_i < len(buckets[y]):
                    chosen.append(buckets[y][round_i])
                    progressed = True
                    if len(chosen) >= max_edges:
                        break
            if not progressed:
                break
            round_i += 1
        chosen.sort(key=lambda kv: -kv[1])

        # 子图实体：种子 + 被选中关系的两端，按得分排序
        order, seen = [], set()
        for nid, _ in seeds:
            if nid not in seen:
                seen.add(nid); order.append(nid)
        for ei, _ in chosen:
            for nid in (self.edges[ei]["s"], self.edges[ei]["t"]):
                if nid not in seen:
                    seen.add(nid); order.append(nid)
        order = order[:max_nodes]

        return Retrieval(query, seeds, order, chosen, self)

    def entity_names(self, retrieval, k=3):
        """取本轮核心实体名，用于下一轮的指代消解。"""
        return [self.nodes[i]["l"] for i, _ in retrieval.seeds[:k]]
