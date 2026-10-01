# -*- coding: utf-8 -*-
"""
可溯源 GraphRAG 检索评测（纯检索层，确定性、可复现，不调用大模型）。

基准 A（模板问答，含标准答案）：从“孙光荣原创/编纂”关系中按关系类型分层抽样，
  以“主语 + 关系”生成自然语言问题，标准答案 = 图谱中同主语、同关系类型的全部三元组。
  指标：Hit@k、Recall@k、MRR。
基准 B（开放问题，无标准答案）：围绕中和学术思想手工撰写 30 问，
  考察检索结果的侧面覆盖与证据质量：关系类型数、类型熵、最大类型占比、
  孙光荣原创占比、实质佐证占比（引文≥10 字）、文献/文本块覆盖、时延。

对比方案
  M1 文本块 BM25   ：以出处编号聚合原文佐证为文本块，块级 BM25 后展开其中关系（模拟常规文本 RAG）
  M2 佐证句 BM25   ：直接对每条关系的原文佐证做 BM25
  M3 实体 + 一跳   ：实体索引召回种子后取全部一跳关系，仅按种子得分排序
  M4 本文（无轮转）：双路召回 + 证据加权打分，但不做关系类型轮转采样
  M5 本文（完整）  ：rag/kg_rag.py 中的 KGRag.retrieve，原样调用
"""
import json
import math
import os
import random
import re
import statistics as st
import sys
import time
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "rag"))
from kg_rag import KGRag, BM25, tokenize, ROLE_WEIGHT  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "output", "tables")
GRAPH = os.path.join(REPO, "android/app/src/main/assets/web/data/graph.json")
MAX_EDGES = 120
SEED = 2026

TEMPLATES = {
    "THOUGHT_HAS_PRINCIPLE": "“{s}”包含哪些治疗原则？",
    "PRINCIPLE_GUIDES_METHOD": "在“{s}”这一治则指导下，宜采用哪些治法？",
    "ESTABLISHES_METHOD": "{s}应如何立法治疗？",
    "EXPLAINED_BY": "{s}的病机是什么？",
    "ATTRIBUTED_TO": "{s}的病因有哪些？",
    "METHOD_USES_FORMULA": "{s}可选用哪些方剂？",
    "HAS_FUNCTION": "三联药组“{s}”有何功效？",
    "TREATS": "{s}主治哪些病证？",
    "HAS_SYMPTOM": "{s}有哪些临床表现？",
    "DERIVED_FROM": "“{s}”的学术渊源是什么？",
    "MAXIM_EXPRESSES": "心法要诀“{s}”阐述了什么思想？",
    "CITES": "“{s}”引用了哪些经典？",
}
REL_ZH_SHORT = {
    "THOUGHT_HAS_PRINCIPLE": "思想含治则", "PRINCIPLE_GUIDES_METHOD": "治则指导治法",
    "ESTABLISHES_METHOD": "明机立法", "EXPLAINED_BY": "求因明机", "ATTRIBUTED_TO": "审证求因",
    "METHOD_USES_FORMULA": "立法组方", "HAS_FUNCTION": "药组功效", "TREATS": "主治",
    "HAS_SYMPTOM": "见症", "DERIVED_FROM": "渊源", "MAXIM_EXPRESSES": "要诀所述", "CITES": "引经据典",
}
PER_TYPE = 20

OPEN_QUESTIONS = [
    "孙光荣中和学术思想的核心内涵是什么？",
    "中和思想的理论渊源有哪些经典？",
    "如何理解“调气血、平升降、衡出入”？",
    "孙光荣“中和组方”的基本原则是什么？",
    "中和辨证方法包括哪些要点？",
    "什么是三联药组？孙光荣如何以三联药组组方？",
    "人参、黄芪、丹参三联药组的组方意义是什么？",
    "孙光荣治疗失眠常用哪些三联药组？",
    "孙光荣如何辨治中风后遗症？",
    "孙光荣治疗胃脘痛的思路是什么？",
    "眩晕如何辨证用药？",
    "孙光荣对肿瘤的中和治疗思路是什么？",
    "妇科月经不调的中和辨治方法有哪些？",
    "小儿咳喘组方用药为何尤以中和为贵？",
    "“扶正祛邪益中和”的含义是什么？",
    "“护正防邪固中和”体现了怎样的治未病思想？",
    "孙光荣养生要诀“上善、中和、下畅”是什么意思？",
    "形神相合与中和健康观有什么关系？",
    "孙光荣的学术师承与学派渊源如何？",
    "孙光荣如何运用《中藏经》的学术思想？",
    "中和用药讲究“清、平、轻、巧、灵”指什么？",
    "气虚血瘀证应如何立法组方？",
    "肝肾阴虚证的常见临床表现与治法是什么？",
    "孙光荣常用的安神药组有哪些？",
    "清热解毒散结类三联药组有哪些？",
    "孙光荣医案中如何体现“审辨燮和”？",
    "调和肝脾、安养心神的治则适用于哪些病证？",
    "以调和阴阳为核心的中和治疗观包括哪些治则？",
    "孙光荣如何看待经方的继承与创新？",
    "中医康复研究中常用哪些康复技术治疗中风后瘫痪？",
]


# ------------------------------------------------------------------ 基准构造
def build_template_set(kg):
    N, E = kg.nodes, kg.edges
    rng = random.Random(SEED)
    groups = defaultdict(lambda: defaultdict(list))
    for k, e in enumerate(E):
        if e["y"] in TEMPLATES and e["r"] in ("sun_original", "sun_compiled"):
            s = N[e["s"]]["l"].strip()
            if 2 <= len(s) <= 28:
                groups[e["y"]][s].append(k)
    qs = []
    for y in TEMPLATES:
        subjects = sorted(groups[y])
        rng.shuffle(subjects)
        for s in subjects[:PER_TYPE]:
            qs.append({"rel": y, "subject": s, "question": TEMPLATES[y].format(s=s)})
    # 标准答案：同主语标签、同关系类型的全部三元组（跨文献同名实体一并计入）
    sig_of = lambda k: (E[k]["y"], N[E[k]["s"]]["l"].strip(), N[E[k]["t"]]["l"].strip())
    by_subj = defaultdict(set)
    for k, e in enumerate(E):
        by_subj[(e["y"], N[e["s"]]["l"].strip())].add(sig_of(k))
    for q in qs:
        q["gold"] = sorted(by_subj[(q["rel"], q["subject"])])
    return qs, sig_of


# ------------------------------------------------------------------ 对比方案
class Methods:
    def __init__(self, kg):
        self.kg = kg
        E = kg.edges
        self.chunk_edges = defaultdict(list)
        for k, e in enumerate(E):
            self.chunk_edges[e["c"]].append(k)
        self.chunks = sorted(self.chunk_edges)
        docs = []
        for c in self.chunks:
            seen, parts = set(), []
            for k in self.chunk_edges[c]:
                q = (E[k].get("q") or "").strip()
                if q and q not in seen:
                    seen.add(q); parts.append(q)
            docs.append(tokenize("。".join(parts)))
        self.chunk_bm25 = BM25(docs)

    def m1_chunk(self, q):
        sc = self.kg_tok_score(self.chunk_bm25, q)
        order = np.argsort(-sc)
        out = []
        for j in order:
            if sc[j] <= 0 or len(out) >= MAX_EDGES:
                break
            out.extend(self.chunk_edges[self.chunks[j]])
        return out[:MAX_EDGES]

    def m2_quote(self, q):
        sc = self.kg.quote_bm25.score(tokenize(q))
        order = np.argsort(-sc)[:MAX_EDGES]
        return [int(self.kg.quote_eid[j]) for j in order if sc[j] > 0]

    def m3_entity(self, q):
        kg = self.kg
        toks = tokenize(q)
        ns = kg.node_bm25.score(toks).astype(np.float32)
        for surf, nid in kg.surface.items():
            if surf in q:
                ns[nid] += 4.0 + 0.9 * len(surf)
        seeds = self._seeds(ns)
        if not seeds:
            return []
        top = seeds[0][1] or 1.0
        es = {}
        for nid, sc in seeds:
            for p in range(kg.adj_start[nid], kg.adj_start[nid + 1]):
                ei = int(kg.adj[p])
                es[ei] = max(es.get(ei, 0.0), sc / top)
        return self._dedup_sorted(es)[:MAX_EDGES]

    def m4_norotate(self, q):
        return self._graphrag(q, rotate=False)

    def m5_full(self, q):
        r = self.kg.retrieve(q, max_edges=MAX_EDGES)
        return [ei for ei, _ in r.edges]

    # ---- 工具 ----
    @staticmethod
    def kg_tok_score(bm, q):
        return bm.score(tokenize(q))

    def _seeds(self, node_score, top_seeds=35):
        kg = self.kg
        if node_score.max() <= 0:
            return []
        k = min(top_seeds * 4, len(node_score) - 1)
        cand = np.argpartition(-node_score, k)[:k + 1]
        cand = cand[np.argsort(-node_score[cand])]
        seeds, seen = [], set()
        for i in cand:
            if node_score[i] <= 0:
                continue
            lab = kg.nodes[int(i)]["l"]
            if lab in seen:
                continue
            seen.add(lab)
            seeds.append((int(i), float(node_score[i])))
            if len(seeds) >= top_seeds:
                break
        return seeds

    def _dedup_sorted(self, es):
        kg = self.kg
        out, seen = [], set()
        for ei, _ in sorted(es.items(), key=lambda kv: (-kv[1], kv[0])):
            e = kg.edges[ei]
            sig = (e["y"], kg.nodes[e["s"]]["l"], kg.nodes[e["t"]]["l"], (e.get("q") or "")[:24])
            if sig in seen:
                continue
            seen.add(sig)
            out.append(ei)
        return out

    def _graphrag(self, query, rotate):
        """与 KGRag.retrieve 同一套打分；rotate=True 时结果与之逐条一致（见 self_check）。"""
        kg = self.kg
        toks = tokenize(query)
        node_score = kg.node_bm25.score(toks).astype(np.float32)
        direct = {}
        qs = kg.quote_bm25.score(toks)
        if qs.max() > 0:
            top_q = np.argpartition(-qs, min(60, len(qs) - 1))[:60]
            top_q = top_q[np.argsort(-qs[top_q])]
            mx = float(qs[top_q[0]]) or 1.0
            for j in top_q:
                if qs[j] <= 0:
                    break
                ei = int(kg.quote_eid[j]); e = kg.edges[ei]; w = float(qs[j])
                node_score[e["s"]] += 0.55 * w; node_score[e["t"]] += 0.55 * w
                direct[ei] = 0.9 * w / mx
        for surf, nid in kg.surface.items():
            if surf in query:
                node_score[nid] += 4.0 + 0.9 * len(surf)
        seeds = self._seeds(node_score)
        if not seeds:
            return []
        top = seeds[0][1] or 1.0
        es = {}
        per_seed_cap = max(6, MAX_EDGES // max(1, len(seeds)))
        for nid, sc in seeds:
            picked = []
            for p in range(kg.adj_start[nid], kg.adj_start[nid + 1]):
                ei = int(kg.adj[p]); e = kg.edges[ei]
                other = e["t"] if e["s"] == nid else e["s"]
                q = (e.get("q") or "").strip()
                s = sc / top
                s += 0.50 if len(q) >= 10 else (0.16 if len(q) >= 4 else 0.0)
                if len(q) < 8 and (q in kg.nodes[other]["l"] or q in kg.nodes[nid]["l"]):
                    s -= 0.40
                s += 0.55 * ROLE_WEIGHT.get(e.get("r"), 0.4)
                s += 0.30 * min(node_score[other] / top, 1.0)
                s -= 0.12 * min(math.log1p(kg.degree[other]) / 6.0, 1.0)
                if e.get("Q"):
                    s -= 0.25
                picked.append((s, ei, e["y"]))
            picked.sort(key=lambda x: -x[0])
            used, taken, spill = defaultdict(int), 0, []
            for s, ei, y in picked:
                if taken >= per_seed_cap:
                    break
                if used[y] >= 3:
                    spill.append((s, ei)); continue
                used[y] += 1; taken += 1
                es[ei] = max(es.get(ei, 0.0), s)
            for s, ei in spill[:max(0, per_seed_cap - taken)]:
                es[ei] = max(es.get(ei, 0.0), s - 0.3)
        for ei, s in direct.items():
            es[ei] = max(es.get(ei, 0.0), s + 1.2)
        if not rotate:
            ranked = self._dedup_sorted(es)
            return ranked[:MAX_EDGES]
        buckets, seen = defaultdict(list), set()
        for ei, sc in sorted(es.items(), key=lambda kv: -kv[1]):
            e = kg.edges[ei]
            sig = (e["y"], kg.nodes[e["s"]]["l"], kg.nodes[e["t"]]["l"], (e.get("q") or "")[:24])
            if sig in seen:
                continue
            seen.add(sig); buckets[e["y"]].append((ei, sc))
        order_types = sorted(buckets, key=lambda y: -buckets[y][0][1])
        cap = max(3, MAX_EDGES // 4)
        chosen, r = [], 0
        while len(chosen) < MAX_EDGES and r < cap:
            prog = False
            for y in order_types:
                if r < len(buckets[y]):
                    chosen.append(buckets[y][r]); prog = True
                    if len(chosen) >= MAX_EDGES:
                        break
            if not prog:
                break
            r += 1
        chosen.sort(key=lambda kv: -kv[1])
        return [ei for ei, _ in chosen]


METHODS = [
    ("M1", "文本块BM25", "m1_chunk"),
    ("M2", "佐证句BM25", "m2_quote"),
    ("M3", "实体+一跳", "m3_entity"),
    ("M4", "本文(无轮转)", "m4_norotate"),
    ("M5", "本文(完整)", "m5_full"),
]
KS = [1, 3, 5, 10, 20, 30, 50, 80, 120]


def entropy_norm(cnt):
    tot = sum(cnt.values())
    if tot == 0 or len(cnt) <= 1:
        return 0.0
    p = np.array(list(cnt.values())) / tot
    return float(-(p * np.log(p)).sum() / math.log(len(cnt)))


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.perf_counter()
    kg = KGRag(GRAPH, verbose=False)
    build_s = time.perf_counter() - t0
    M = Methods(kg)

    # 自检：重实现的 rotate=True 与官方 retrieve 逐条一致
    for q in OPEN_QUESTIONS[:10]:
        assert M._graphrag(q, rotate=True) == M.m5_full(q), q

    qs, sig_of = build_template_set(kg)
    res = {"build_seconds": build_s, "n_template": len(qs), "n_open": len(OPEN_QUESTIONS),
           "template": {}, "template_by_rel": {}, "open": {}, "latency_ms": {}}
    per_q = []
    for code, name, fn in METHODS:
        f = getattr(M, fn)
        hits = {k: [] for k in KS}
        recall20, rr, lat = [], [], []
        by_rel = defaultdict(list)
        for q in qs:
            t = time.perf_counter()
            ranked = f(q["question"])
            lat.append((time.perf_counter() - t) * 1000)
            gold = set(map(tuple, q["gold"]))
            sigs = [sig_of(ei) for ei in ranked]
            first = next((i for i, s in enumerate(sigs) if s in gold), None)
            for k in KS:
                hits[k].append(1.0 if first is not None and first < k else 0.0)
            rr.append(1.0 / (first + 1) if first is not None else 0.0)
            got20 = len(gold & set(sigs[:20]))
            recall20.append(got20 / min(len(gold), 20))
            by_rel[q["rel"]].append(1.0 if first is not None and first < 10 else 0.0)
            per_q.append({"method": code, "rel": q["rel"], "question": q["question"],
                          "rank_first_gold": None if first is None else first + 1})
        res["template"][code] = {
            "name": name, **{f"hit@{k}": float(np.mean(hits[k])) for k in KS},
            "recall@20": float(np.mean(recall20)), "mrr": float(np.mean(rr)),
        }
        res["template_by_rel"][code] = {y: float(np.mean(v)) for y, v in by_rel.items()}

        # ---- 开放问题：侧面覆盖与证据质量 ----
        rows, lat_o = [], []
        for q in OPEN_QUESTIONS:
            t = time.perf_counter()
            ranked = f(q)
            lat_o.append((time.perf_counter() - t) * 1000)
            E = [kg.edges[ei] for ei in ranked]
            for K in (30, MAX_EDGES):
                sub = E[:K]
                tc = Counter(e["y"] for e in sub)
                rows.append({
                    "K": K, "n": len(sub), "types": len(tc), "entropy": entropy_norm(tc),
                    "max_share": (max(tc.values()) / len(sub)) if sub else 0.0,
                    "sun_original": (sum(e["r"] == "sun_original" for e in sub) / len(sub)) if sub else 0.0,
                    "substantive": (sum(len((e["q"] or "").strip()) >= 10 for e in sub) / len(sub)) if sub else 0.0,
                    "docs": len({e["d"] for e in sub}), "chunks": len({e["c"] for e in sub}),
                    "traceable": (sum(bool(e["c"]) and bool((e["q"] or "").strip()) for e in sub) / len(sub)) if sub else 0.0,
                })
        agg = {}
        for K in (30, MAX_EDGES):
            R = [r for r in rows if r["K"] == K]
            agg[str(K)] = {k: float(np.mean([r[k] for r in R])) for k in R[0] if k != "K"}
            agg[str(K)]["types_list"] = [r["types"] for r in R]
            agg[str(K)]["max_share_list"] = [r["max_share"] for r in R]
        res["open"][code] = agg
        lat_all = lat + lat_o
        res["latency_ms"][code] = {"median": float(np.median(lat_all)), "p95": float(np.percentile(lat_all, 95))}
        print(f"{code} {name}: hit@10={res['template'][code]['hit@10']:.3f} mrr={res['template'][code]['mrr']:.3f} "
              f"types@120={agg[str(MAX_EDGES)]['types']:.1f} lat={res['latency_ms'][code]['median']:.1f}ms")

    with open(os.path.join(OUT, "retrieval_eval.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "benchmark_template_questions.jsonl"), "w", encoding="utf-8") as f:
        for q in qs:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "benchmark_open_questions.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OPEN_QUESTIONS) + "\n")
    with open(os.path.join(OUT, "retrieval_eval_per_question.jsonl"), "w", encoding="utf-8") as f:
        for r in per_q:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    run()
