# -*- coding: utf-8 -*-
"""Graphviz 布局 + matplotlib 出图：节点尺寸按印刷字号预先测定，布局即成品尺寸。"""
import json
import subprocess

import numpy as np
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Polygon

MM2PT = 72 / 25.4


def text_w(s, fs):
    mm = fs * 0.3528
    return sum(mm if ord(ch) > 0x2E7F else mm * 0.52 for ch in s)


def wrap(s, n):
    """中文按字数折行（不拆西文词）。"""
    if len(s) <= n:
        return s
    lines, cur = [], ""
    for ch in s:
        cur += ch
        if len(cur) >= n and ch not in "，、；：":
            lines.append(cur); cur = ""
    if cur:
        if len(cur) <= 2 and lines:
            lines[-1] += cur
        else:
            lines.append(cur)
    return "\n".join(lines)


def layout(nodes, edges, engine="dot", graph_attrs="", same_rank=()):
    """nodes: {id: (w_mm, h_mm, extra_attr_str)}; edges: [(a, b, attr_str)]
    返回 {id: (cx, cy)}（毫米，y 向下）与 [(pts_mm, head_pts_mm)]、画布尺寸。"""
    L = [f"digraph G {{ graph [{graph_attrs}]; node [shape=box, fixedsize=true, label=\"\"]; "
         "edge [arrowsize=0.5];"]
    ids = {}
    for k, (nid, (w, h, extra)) in enumerate(nodes.items()):
        ids[nid] = f"n{k}"
        L.append(f'n{k} [width={w/25.4:.3f}, height={h/25.4:.3f} {extra}];')
    for k, (a, b, attr) in enumerate(edges):
        L.append(f'{ids[a]} -> {ids[b]} [id="e{k}" {attr}];')
    for grp in same_rank:
        L.append("{rank=same; " + "; ".join(ids[x] for x in grp) + ";}")
    L.append("}")
    res = subprocess.run([engine, "-Tjson"], input="\n".join(L), capture_output=True, text=True, check=True)
    gj = json.loads(res.stdout)
    bb = list(map(float, gj["bb"].split(",")))
    H = bb[3] / MM2PT
    W = bb[2] / MM2PT
    inv = {v: k for k, v in ids.items()}
    pos = {}
    for ob in gj["objects"]:
        if ob.get("name") in inv and "pos" in ob:
            x, y = map(float, ob["pos"].split(","))
            pos[inv[ob["name"]]] = (x / MM2PT, H - y / MM2PT)
    routes = [None] * len(edges)
    for ed in gj.get("edges", []):
        k = int(ed["id"][1:])
        pts = [op["points"] for op in ed.get("_draw_", []) if op["op"] == "b"]
        head = [op["points"] for op in ed.get("_hdraw_", []) if op["op"] in ("P", "p")]
        conv = lambda P: [(p[0] / MM2PT, H - p[1] / MM2PT) for p in P]
        routes[k] = (conv(pts[0]) if pts else None, conv(head[0]) if head else None)
    return pos, routes, (W, H)


def draw_edge(ax, route, color, lw, z=1, ls="-", alpha=1.0, head=True):
    pts, hd = route
    if not pts:
        return
    codes = [Path.MOVETO] + [Path.CURVE4] * (len(pts) - 1)
    ax.add_patch(PathPatch(Path(pts, codes), fc="none", ec=color, lw=lw, zorder=z, ls=ls, alpha=alpha))
    if head and hd:
        ax.add_patch(Polygon(hd, closed=True, fc=color, ec=color, lw=0.2, zorder=z, alpha=alpha))
