# -*- coding: utf-8 -*-
"""流程图/框架图绘制小工具：以毫米为单位在一张画布上摆放圆角框与箭头。"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

from style import INK, INK2, INK3, CM, SERIF, SANS


class Canvas:
    def __init__(self, w_mm, h_mm):
        self.w, self.h = w_mm, h_mm
        self.fig = plt.figure(figsize=(w_mm / 10 * CM, h_mm / 10 * CM))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, w_mm)
        self.ax.set_ylim(h_mm, 0)          # y 向下，便于按版面坐标摆放
        self.ax.axis("off")

    # ---- 基本元素 ----
    def box(self, x, y, w, h, text="", fc="#FFFFFF", ec=INK3, lw=0.6, r=1.2,
            fs=7.5, color=INK, weight="normal", ls="-", z=2, family=None, ha="center",
            linespacing=1.25, alpha=1.0):
        p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                           fc=fc, ec=ec, lw=lw, ls=ls, zorder=z, alpha=alpha)
        self.ax.add_patch(p)
        if text:
            tx = x + w / 2 if ha == "center" else x + 1.6
            self.ax.text(tx, y + h / 2, text, ha=ha, va="center", fontsize=fs, color=color,
                         fontweight=weight, zorder=z + 1, family=family or SERIF,
                         linespacing=linespacing)
        return (x, y, w, h)

    def rect(self, x, y, w, h, fc, ec="none", lw=0.0, z=0, alpha=1.0):
        self.ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=ec, lw=lw, zorder=z, alpha=alpha))

    def text(self, x, y, s, fs=7.5, color=INK, ha="center", va="center", weight="normal",
             family=None, z=5, rotation=0, style="normal", linespacing=1.2, bbox=None):
        return self.ax.text(x, y, s, fontsize=fs, color=color, ha=ha, va=va, fontweight=weight,
                            family=family or SERIF, zorder=z, rotation=rotation, style=style,
                            linespacing=linespacing, bbox=bbox)

    def arrow(self, p0, p1, color=INK2, lw=0.7, ms=6, style="-|>", rad=0.0, z=1, ls="-",
              shrinkA=0.0, shrinkB=0.0):
        a = FancyArrowPatch(p0, p1, arrowstyle=f"{style},head_length={ms*0.06:.2f},head_width={ms*0.035:.2f}"
                            if style != "-" else "-",
                            connectionstyle=f"arc3,rad={rad}", color=color, lw=lw, zorder=z,
                            linestyle=ls, shrinkA=shrinkA, shrinkB=shrinkB, mutation_scale=10)
        self.ax.add_patch(a)
        return a

    def poly(self, pts, color=INK2, lw=0.7, arrow=True, ms=6, z=1, ls="-"):
        """折线箭头（正交连线用）。"""
        xs, ys = zip(*pts)
        self.ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color=color, lw=lw, zorder=z,
                     solid_capstyle="butt", ls=ls)
        if arrow:
            self.arrow(pts[-2], pts[-1], color=color, lw=lw, ms=ms, z=z)
