# -*- coding: utf-8 -*-
"""
论文图表统一样式：面向中文核心期刊（北大核心）排版习惯。

- 中文用宋体（Noto Serif CJK SC 代替），西文与数字用 Times 度量兼容的 Liberation Serif；
  matplotlib ≥3.6 支持按字形回退，因此一个 family 列表即可做到“中宋西 Times”。
- 字号以 8 pt（小五号≈9 pt，六号≈7.5 pt）为基准，单栏 8.5 cm、通栏 17.5 cm。
- 知识来源五色取自图谱 App 的传统色系，按色盲可分性重新定阶（已用校验脚本验证相邻对 ΔE）。
- 输出：600 dpi PNG（投稿）、PDF（矢量，TrueType 嵌入）、SVG（可编辑）。
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "output")

CM = 1 / 2.54
W_SINGLE = 8.5 * CM
W_DOUBLE = 17.5 * CM

# 知识来源（与 App/RAG 语义一致）：朱砂·藤黄·靛青·青碧·绛紫
ROLE_ORDER = ["sun_original", "sun_compiled", "classical_source", "third_party_clinical", "general_tcm"]
ROLE_ZH = {
    "sun_original": "孙光荣原创", "sun_compiled": "孙光荣编纂", "classical_source": "经典引文",
    "third_party_clinical": "他人临床报道", "general_tcm": "中医通识",
}
ROLE_COLOR = {
    "sun_original": "#B8322A", "sun_compiled": "#D9961A", "classical_source": "#2A6BB0",
    "third_party_clinical": "#1E9C80", "general_tcm": "#7B4AA5",
}

INK = "#1F1B16"        # 正文墨色
INK2 = "#5A534A"       # 次级文字
INK3 = "#8C857A"       # 弱化文字/坐标轴
GRID = "#E3DED5"
PAPER = "#FFFFFF"
ACCENT = "#B8322A"     # 强调（朱砂），单序列图默认色
SEQ = "#2A6BB0"        # 单一量值色（靛青）
MUTED = "#B9B2A6"      # 背景/对照序列

SERIF = ["Liberation Serif", "Noto Serif CJK SC"]
SANS = ["Liberation Sans", "Noto Sans CJK SC"]


def setup():
    for f in ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
    plt.rcParams.update({
        "font.family": SERIF,
        "font.size": 8,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "axes.edgecolor": INK3,
        "axes.labelcolor": INK,
        "axes.linewidth": 0.6,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "text.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "grid.color": GRID,
        "grid.linewidth": 0.5,
        "legend.frameon": False,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "path",
        "savefig.dpi": 600,
        "figure.dpi": 150,
        "mathtext.fontset": "stix",
    })


def panel_label(ax, s, x=-0.02, y=1.02, **kw):
    """分图标号：A、B……（加粗西文）。"""
    ax.text(x, y, s, transform=ax.transAxes, fontsize=10, fontweight="bold",
            ha="right", va="bottom", family=SANS, **kw)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        d = os.path.join(OUT, ext)
        os.makedirs(d, exist_ok=True)
        fig.savefig(os.path.join(d, f"{name}.{ext}"), dpi=600 if ext == "png" else None,
                    bbox_inches="tight", pad_inches=0.04, facecolor=PAPER)
    plt.close(fig)
    print("  ✔", name)
