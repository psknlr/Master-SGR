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
    def context(self, max_chars=6500):
        kg = self.kg
        if not self.nodes:
            return "（图谱中未检索到与该问题直接相关的实体。）"

        buf = ["以下是从《国医大师孙光荣中医知识图谱》检索到的知识片段，"
               f"共 {len(self.nodes)} 个实体、{len(self.edges)} 条关系。\n"]

        buf.append("〖实体〗")
        seed_ids = {i for i, _ in self.seeds}
        for nid in self.nodes[:18]:
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

        buf.append("\n〖关系与原文佐证〗")
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
            buf.append(seg)
            if sum(len(x) for x in buf) > max_chars:
                buf.append(f"…（其余 {len(self.edges) - k} 条关系因篇幅省略）")
                break

        return "\n".join(buf)

    # -------- 子图 SVG（国风配色，无外部依赖） --------
    def svg(self, width=520, height=420, theme="paper"):
        kg = self.kg
        ids = self.nodes[:46]
        if not ids:
            return "<div style='padding:28px;text-align:center;color:#7C6C58'>暂无检索结果</div>"
        idx = {n: i for i, n in enumerate(ids)}
        pairs = []
        for ei, _ in self.edges:
            e = kg.edges[ei]
            if e["s"] in idx and e["t"] in idx:
                pairs.append((idx[e["s"]], idx[e["t"]], kg.rel_zh.get(e["y"], e["y"])))

        bg, fg, sub = ("#F1E6D1", "#241C15", "#7C6C58") if theme == "paper" else ("#131009", "#EDE3D0", "#93866F")
        n = len(ids)
        rng = np.random.default_rng(7)
        pos = np.stack([np.cos(np.arange(n) / n * 2 * np.pi), np.sin(np.arange(n) / n * 2 * np.pi)], 1)
        pos = pos * 120 + rng.normal(0, 6, (n, 2))
        E = np.array([[a, b] for a, b, _ in pairs], dtype=np.int32) if pairs else np.zeros((0, 2), np.int32)

        for it in range(180):                       # 迷你力导向
            d = pos[:, None, :] - pos[None, :, :]
            dist = np.hypot(d[..., 0], d[..., 1]) + 1e-6
            rep = (d / dist[..., None]) * (2600.0 / dist[..., None] ** 2)
            np.fill_diagonal(rep[..., 0], 0); np.fill_diagonal(rep[..., 1], 0)
            disp = rep.sum(1)
            if len(E):
                dv = pos[E[:, 1]] - pos[E[:, 0]]
                np.add.at(disp, E[:, 0], dv * 0.045)
                np.add.at(disp, E[:, 1], -dv * 0.045)
            disp -= pos * 0.012
            step = np.clip(1.0 - it / 180.0, 0.05, 1.0) * 4.0
            norm = np.hypot(disp[:, 0], disp[:, 1])[:, None] + 1e-6
            pos += disp / norm * np.minimum(norm, step)

        lo, hi = pos.min(0), pos.max(0)
        span = np.maximum(hi - lo, 1e-6)
        pad = 40
        pos = (pos - lo) / span * np.array([width - 2 * pad, height - 2 * pad]) + pad

        seed_ids = {i for i, _ in self.seeds}
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
               f'style="width:100%;height:auto;background:{bg};border-radius:4px">']
        out.append(f'<g stroke="{sub}" stroke-opacity="0.42" stroke-width="1">')
        for a, b, rel in pairs:
            out.append(f'<line x1="{pos[a,0]:.1f}" y1="{pos[a,1]:.1f}" '
                       f'x2="{pos[b,0]:.1f}" y2="{pos[b,1]:.1f}"><title>{html.escape(rel)}</title></line>')
        out.append("</g>")
        for nid in ids:
            i = idx[nid]
            nd = kg.nodes[nid]
            is_seed = nid in seed_ids
            r = 8.5 if is_seed else 4.5
            col = ROLE_COLOR.get(nd["r"], "#7E6F5C")
            out.append(f'<circle cx="{pos[i,0]:.1f}" cy="{pos[i,1]:.1f}" r="{r}" fill="{col}"'
                       + (f' stroke="{bg}" stroke-width="2.4"' if is_seed else "")
                       + f'><title>{html.escape(nd["l"])}</title></circle>')
            if is_seed or n <= 22:
                lab = nd["l"][:9] + ("…" if len(nd["l"]) > 9 else "")
                weight = ' font-weight="600"' if is_seed else ""
                fs = 11 if is_seed else 9.5
                # 中日韩字符约等于一个字号宽，西文约半个；据此估宽，越界就改成右对齐画到左边
                est = sum(fs if ch > "\u2e7f" else fs * 0.55 for ch in lab)
                tx, anchor = pos[i, 0] + r + 3, "start"
                if tx + est > width - 4:
                    tx, anchor = pos[i, 0] - r - 3, "end"
                    if tx - est < 4:            # 两边都放不下就居中压在节点上方
                        tx, anchor = min(max(pos[i, 0], est / 2 + 4), width - est / 2 - 4), "middle"
                out.append('<text x="%.1f" y="%.1f" font-size="%s" fill="%s" text-anchor="%s" '
                           'font-family="Noto Serif CJK SC,Songti SC,serif"%s>%s</text>'
                           % (tx, pos[i, 1] + 3.5, fs, fg, anchor, weight, html.escape(lab)))
        out.append("</svg>")
        return "".join(out)


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
    def retrieve(self, query, focus_entities=(), top_seeds=8, max_edges=48,
                 max_nodes=46) -> Retrieval:
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
