#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
由 rag/*.py 生成 Colab 笔记本，保证「仓库源码」与「笔记本里的代码」永远一致。
用法：python3 tools/make_notebook.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "colab", "SGR_KG_RAG_Colab.ipynb")
RAW_BASE = ("https://raw.githubusercontent.com/psknlr/Master-SGR/"
            "claude/tcm-knowledge-graph-app-h709bx")


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}


def code(src, **meta):
    return {"cell_type": "code", "execution_count": None, "metadata": meta,
            "outputs": [], "source": src.rstrip("\n").splitlines(keepends=True)}


def writefile(name, path):
    return code(f"%%writefile {name}\n" + read(path))


cells = []

cells.append(md(f"""# 国医大师孙光荣中医知识图谱 · RAG 智能问答

**Sun Guangrong TCM Knowledge Graph — Graph-RAG Assistant**

> 研发：**孙光荣大师弟子田建辉团队** 联合 **医哲未来人工智能研究院（IMPF-AI Institute）**

在 Colab 里一键跑起一个**基于知识图谱检索增强（GraphRAG）的中医问答服务**，
并生成一个**公网可访问的多轮对话链接**（`*.gradio.live`）。

| | |
|---|---|
| 知识底座 | 19,343 实体 · 25,713 关系 · 8 部文献 · 31 类实体 · 44 类关系 |
| 检索 | 实体索引 + 原文佐证索引双路召回 → 1 跳图扩展 → 关系类型轮转采样 |
| 生成 | **Poe**（默认 `claude-sonnet-5`）或 **MiniMax**（默认 `MiniMax-M3`） |
| 可核验 | 右侧面板实时展示本轮实际检索到的子图 / 实体 / 三元组 / 原文佐证 / 送入模型的上下文 |

**依次运行下面每个单元格即可**（约 2 分钟）。第 6 格是「RAG 知识图谱数据」预览，
不配 API Key 也能单独用；第 8 格产出公网链接。

---
> 本应用为中医药学术研究与教学参考工具，内容由文献自动抽取并经抽样审校，
> **不能替代执业医师的诊断与处方**，请勿据此自行用药。
"""))

# 1 依赖
cells.append(md("## 1　安装依赖"))
cells.append(code('''#@title 安装依赖（约 30 秒）
!pip -q install "gradio>=4.44" requests numpy

import gradio, numpy, requests
print("gradio", gradio.__version__, "| numpy", numpy.__version__)'''))

# 2 数据
cells.append(md("""## 2　取得图谱数据

按 `已在本地` → `GitHub 直链` → `手动上传` 的顺序尝试。
仓库为私有时前两步会失败，届时会弹出上传框，
上传 `graph.json` **或**原始的 `sunguangrong_kg_v2_explorer.html` 都可以（后者会自动抽取）。"""))
cells.append(code(f'''#@title 下载 / 上传图谱数据
import os, sys, subprocess

GRAPH = None
CANDIDATES = ["graph.json", "sunguangrong_kg_v2_explorer.html"]
RAW_URL = "{RAW_BASE}/android/app/src/main/assets/web/data/graph.json"

for p in CANDIDATES:
    if os.path.exists(p) and os.path.getsize(p) > 100000:
        GRAPH = p
        print("✔ 使用本地文件：", p, f"({{os.path.getsize(p)/1048576:.1f}} MB)")
        break

if GRAPH is None:
    print("→ 尝试从 GitHub 拉取…")
    rc = subprocess.call(["wget", "-q", "-O", "graph.json", RAW_URL])
    if rc == 0 and os.path.exists("graph.json") and os.path.getsize("graph.json") > 100000:
        GRAPH = "graph.json"
        print("✔ 已下载 graph.json", f"({{os.path.getsize(GRAPH)/1048576:.1f}} MB)")
    else:
        if os.path.exists("graph.json"):
            os.remove("graph.json")
        print("✘ 直链不可用（仓库可能为私有）。请在下方选择文件上传：")
        print("   graph.json  或  sunguangrong_kg_v2_explorer.html")
        from google.colab import files
        up = files.upload()
        for name in up:
            if name.endswith((".json", ".html", ".htm")):
                GRAPH = name
                break

assert GRAPH, "未取得图谱数据，请重新运行本单元格并上传文件。"
print("图谱文件：", GRAPH)'''))

# 3-5 源码
cells.append(md("""## 3　写出源码

三个模块，与 GitHub 仓库 `rag/` 下的文件完全一致：

- `kg_rag.py`　　　图谱索引与检索（双路 BM25 + 图扩展 + 上下文组装 + 子图 SVG）
- `llm_clients.py`　Poe / MiniMax 流式客户端
- `app.py`　　　　Gradio 界面"""))
cells.append(writefile("kg_rag.py", "rag/kg_rag.py"))
cells.append(writefile("llm_clients.py", "rag/llm_clients.py"))
cells.append(writefile("app.py", "rag/app.py"))

# 6 建索引
cells.append(md("## 4　构建检索索引"))
cells.append(code('''#@title 构建索引（约 5 秒）
import sys, importlib
sys.path.insert(0, ".")
for m in ("kg_rag", "llm_clients", "app"):
    if m in sys.modules:
        importlib.reload(sys.modules[m])

from kg_rag import KGRag
kg = KGRag(GRAPH)'''))

# 7 RAG 数据预览
cells.append(md("""## 5　RAG 知识图谱数据预览　🔍

**这一格单独展示 RAG 到底检索到了什么**——改上面的问题重跑即可，不需要 API Key。
（同样的内容也会实时出现在第 8 格问答界面的右侧面板里。）"""))
cells.append(code('''#@title RAG 检索到的知识图谱数据 { display-mode: "form" }
问题 = "什么是中和思想？中和组方的基本原则是什么？"  #@param {type:"string"}
种子实体数 = 8   #@param {type:"slider", min:3, max:16, step:1}
检索关系数 = 48  #@param {type:"slider", min:12, max:90, step:2}
上下文字数上限 = 6500  #@param {type:"slider", min:2000, max:14000, step:500}

import pandas as pd
from IPython.display import HTML, display

r = kg.retrieve(问题, top_seeds=int(种子实体数), max_edges=int(检索关系数))
ctx = r.context(max_chars=int(上下文字数上限))

display(HTML(
    f"<div style='font-family:Noto Serif CJK SC,Songti SC,serif;font-size:15px;"
    f"padding:8px 0;color:#241C15'><b>「{问题}」</b></div>"
    f"<div style='color:#7C6C58;font-size:12.5px;padding-bottom:8px'>"
    f"种子实体 {len(r.seeds)} · 子图实体 {len(r.nodes)} · 关系 {len(r.edges)} · "
    f"上下文 {len(ctx)} 字</div>"))

display(HTML("<h4>① 检索子图</h4>" + r.svg(width=880, height=470)))

df_t = pd.DataFrame(r.triple_rows(), columns=r.TRIPLE_HEADERS)
df_e = pd.DataFrame(r.entity_rows(), columns=r.ENTITY_HEADERS)

display(HTML("<h4>② 三元组与原文佐证</h4>"))
display(df_t.style.hide(axis="index").set_properties(
    **{"text-align": "left", "font-size": "12.5px", "white-space": "pre-wrap"}))

display(HTML("<h4>③ 实体（★ 为检索种子）</h4>"))
display(df_e.style.hide(axis="index").set_properties(
    **{"text-align": "left", "font-size": "12.5px"}))

print("\\n④ 送入模型的上下文（前 1500 字）\\n" + "─" * 60)
print(ctx[:1500])
print("─" * 60, f"\\n共 {len(ctx)} 字")'''))

# 8 API
cells.append(md("""## 6　配置模型 API

支持两家，二选一或都填：

| | 默认模型 | 密钥获取 |
|---|---|---|
| **Poe** | `claude-sonnet-5` | <https://poe.com/api_key> |
| **MiniMax** | `MiniMax-M3` | MiniMax 开放平台 → 账户管理 → 接口密钥 |

推荐把密钥存进 Colab 左侧 🔑 **Secrets**（名字用 `POE_API_KEY` / `MINIMAX_API_KEY`），
这样密钥不会留在笔记本里。没存 Secrets 时会提示手动输入，直接回车可跳过。

> Poe 的模型目录会实时校验：若 `claude-sonnet-5` 尚未上架，会自动改用同族最新版本
> （目前是 `claude-sonnet-4.6`）并给出提示。"""))
cells.append(code('''#@title 填写 / 读取 API 密钥并自检
import os, getpass

def get_key(name):
    try:
        from google.colab import userdata
        v = userdata.get(name)
        if v:
            print(f"  {name}: 已从 Colab Secrets 读取")
            return v.strip()
    except Exception:
        pass
    v = os.environ.get(name, "")
    if v:
        print(f"  {name}: 已从环境变量读取")
        return v.strip()
    try:
        v = getpass.getpass(f"  请粘贴 {name}（不用可直接回车）：")
    except Exception:
        v = ""
    return (v or "").strip()

POE_API_KEY = get_key("POE_API_KEY")
MINIMAX_API_KEY = get_key("MINIMAX_API_KEY")
os.environ["POE_API_KEY"] = POE_API_KEY
os.environ["MINIMAX_API_KEY"] = MINIMAX_API_KEY

from llm_clients import (DEFAULT_MINIMAX_MODEL, DEFAULT_POE_MODEL,
                         MiniMaxClient, PoeClient, selftest)

print("\\n— Poe 模型目录校验 —")
actual, note = PoeClient("", DEFAULT_POE_MODEL).resolve_model()
print(f"  期望 {DEFAULT_POE_MODEL} → 实际 {actual}　{note}")

print("\\n— 连通性自检 —")
if POE_API_KEY:
    print(" ", selftest(PoeClient(POE_API_KEY, actual))[1])
else:
    print("  · 未提供 Poe 密钥，跳过")
if MINIMAX_API_KEY:
    print(" ", selftest(MiniMaxClient(MINIMAX_API_KEY, DEFAULT_MINIMAX_MODEL))[1])
else:
    print("  · 未提供 MiniMax 密钥，跳过")

if not (POE_API_KEY or MINIMAX_API_KEY):
    print("\\n⚠ 两家都没配密钥：问答界面仍可启动，RAG 检索面板照常工作，"
          "但生成回答时会提示缺少密钥。")'''))

# 9 启动
cells.append(md("""## 7　启动问答服务，生成公网链接　🌐

运行后会打印一条 `https://xxxxxxxx.gradio.live` 链接，
**手机、其他电脑都能直接打开**，支持多轮对话，有效期 72 小时。

- 想给链接加口令：把 `访问用户名` / `访问密码` 填上。
- 想长期在线：把 `rag/` 目录部署到 Hugging Face Spaces 或自己的服务器（见仓库 README）。"""))
cells.append(code('''#@title 启动 Gradio（生成公网链接） { display-mode: "form" }
访问用户名 = ""  #@param {type:"string"}
访问密码 = ""    #@param {type:"string"}

import importlib
import app as sgr_app
importlib.reload(sgr_app)

demo = sgr_app.build_demo(kg, share_note=" · Colab 在线版")
auth = (访问用户名, 访问密码) if (访问用户名 and 访问密码) else None

res = sgr_app.launch(demo, share=True, port=7860, auth=auth)
try:
    print("\\n公网链接：", res[2] or "(未生成，请检查 Colab 网络)")
    print("本地链接：", res[1])
except Exception:
    pass

print("\n停止服务：demo.close()")'''))

cells.append(md("""---

## 常见问题

**公网链接打不开 / 没有生成？**　Colab 偶尔无法连上 gradio 的隧道服务，重跑第 8 格即可；
链接有效期 72 小时，会话断开后需要重跑。

**回答说「图谱中未见记载」？**　这是设计如此——系统只依据检索到的图谱证据作答，
不会用通用常识编补。可以在第 6 格看看究竟检索到了什么，或调大「检索关系数」再试。

**怎么换模型？**　界面里「模型与检索设置 → Poe 模型 / MiniMax 模型」直接改。
Poe 的可用模型名可以这样列出：

```python
from llm_clients import PoeClient
ids = PoeClient("").list_models()
print([i for i in ids if "claude" in i or "minimax" in i])
```

**想停止服务？**　`demo.close()`，或直接中断该单元格。

---

<div align="center">

**孙光荣大师弟子田建辉团队** × **医哲未来人工智能研究院（IMPF-AI Institute）**

承国医之道 · 启智能之钥

</div>"""))

nb = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "toc_visible": True,
                  "name": "国医大师孙光荣中医知识图谱 · RAG 智能问答"},
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
    },
    "cells": cells,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print(f"✔ 已生成 {OUT}（{len(cells)} 个单元格，{os.path.getsize(OUT)/1024:.0f} KB）")
