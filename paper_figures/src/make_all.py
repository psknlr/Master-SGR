# -*- coding: utf-8 -*-
"""一键重绘全部论文图表：python3 paper_figures/src/make_all.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import style
style.setup()

import charts, diagrams, eval_fig, herbs, ontology, rag_figs, retrieval_eval, sankey, tables, zhonghe


def preview_pdf():
    """把 12 幅图的 PNG 缩印成一份预览 PDF（投稿请用 output/pdf 下的矢量文件）。"""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    png = os.path.join(style.OUT, "png")
    files = sorted((f for f in os.listdir(png) if f.endswith(".png")),
                   key=lambda s: int(s.split("_")[0][1:]))
    pages = []
    for f in files:
        im = Image.open(os.path.join(png, f)).convert("RGB")
        im.thumbnail((2400, 3200))
        pages.append(im)
    out = os.path.join(style.OUT, "全部图表预览.pdf")
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=200)
    print("  ✔", out)


if __name__ == "__main__":
    t = time.time()
    print("① 框架与本体")
    diagrams.fig_framework()
    ontology.fig_ontology()
    print("② 统计图")
    charts.fig_type_distribution()
    charts.fig_source_distribution()
    charts.fig_quality()
    topo = charts.fig_topology()
    sankey.fig_sankey()
    zhonghe.fig_zhonghe()
    herbs.fig_herbs()
    print("③ GraphRAG 与检索评测")
    rag_figs.fig_rag_framework()
    rag_figs.fig_evidence_chain()
    retrieval_eval.run()
    eval_fig.fig_eval()
    print("④ 表格")
    tables.build_all(topo)
    preview_pdf()
    print(f"完成，用时 {time.time() - t:.1f} s")
