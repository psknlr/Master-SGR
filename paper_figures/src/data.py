# -*- coding: utf-8 -*-
"""图谱数据装载与派生统计（全部图表共用，单一数据源：App 内置 graph.json）。"""
import json
import os
from collections import Counter, defaultdict
from functools import lru_cache

from style import ROOT

REPO = os.path.dirname(ROOT)
GRAPH = os.path.join(REPO, "android/app/src/main/assets/web/data/graph.json")

# 本体模块划分（六层）。顺序即论文中的叙述顺序。
MODULES = [
    ("中和思想层", ["ZhongheThought", "AcademicViewpoint", "ClinicalMaxim", "Maxim"]),
    ("辨证论治层", ["Symptom", "TongueSign", "PulseSign", "Disease", "Syndrome",
                    "Etiology", "Pathomechanism", "TreatmentPrinciple", "TreatmentMethod"]),
    ("方药配伍层", ["Formula", "Prescription", "NewFormula", "HerbTriplet", "HerbPair",
                    "Herb", "ExternalPreparation", "DietaryTherapy"]),
    ("医案诊次层", ["CaseRecord", "Visit", "Patient"]),
    ("养生康复层", ["HealthPreservationMethod", "RehabilitationTechnique", "CosmeticIndication"]),
    ("传承溯源层", ["ClassicalText", "Physician", "School", "SourceCitation"]),
]
TYPE_MODULE = {t: m for m, ts in MODULES for t in ts}

DOC_SHORT = {
    "D1": "中和思想与临证经验集萃", "D2": "孙光荣医案解读", "D3": "医道中和·临证心法要诀",
    "D4": "中华经典养生名言录", "D5": "中医康复研究", "D6": "炎症的中医辨治",
    "D7": "'91中医新方妙术", "D8": "精方妙药与美容",
}


@lru_cache(maxsize=1)
def load():
    with open(GRAPH, encoding="utf-8") as f:
        return json.load(f)


def label(i):
    return load()["nodes"][i]["l"]


@lru_cache(maxsize=1)
def adjacency():
    D = load()
    adj = defaultdict(list)
    for k, e in enumerate(D["edges"]):
        adj[e["s"]].append(k)
        adj[e["t"]].append(k)
    return adj


@lru_cache(maxsize=1)
def degree():
    D = load()
    deg = Counter()
    for e in D["edges"]:
        deg[e["s"]] += 1
        deg[e["t"]] += 1
    return deg


def _split_triplet(lab):
    for sep in ("+", "、", "，", ",", " "):
        lab = lab.replace(sep, "+")
    return [x.strip() for x in lab.split("+") if x.strip()]


@lru_cache(maxsize=1)
def prescription_herbs():
    """孙光荣医案处方 → 药物集合。

    处方在图谱中主要以“三联药组”编码（处方—含药组→药组），少数直接“含药”。
    药组名本身即孙老的书写习惯（如“生晒参+生黄芪+紫丹参”），按名拆分最能保留其用名；
    同一处方内若同时出现“杜仲/川杜仲”这类简称与全称，只保留全称。
    """
    D = load()
    N, E = D["nodes"], D["edges"]
    out = defaultdict(set)
    for e in E:
        if N[e["s"]]["t"] != "Prescription":
            continue
        if e["y"] == "CONTAINS_TRIPLET":
            out[e["s"]].update(_split_triplet(N[e["t"]]["l"]))
        elif e["y"] == "CONTAINS_HERB":
            out[e["s"]].add(N[e["t"]]["l"].strip())
    clean = {}
    for p, hs in out.items():
        keep = {h for h in hs if not any(h2 != h and h2.endswith(h) and len(h) >= 2 for h2 in hs)}
        if keep:
            clean[p] = keep
    return clean


@lru_cache(maxsize=1)
def prescription_triplets():
    D = load()
    N, E = D["nodes"], D["edges"]
    out = defaultdict(set)
    for e in E:
        if e["y"] == "CONTAINS_TRIPLET" and N[e["s"]]["t"] == "Prescription":
            out[e["s"]].add(N[e["t"]]["l"].replace("、", "+"))
    return out
