# -*- coding: utf-8 -*-
"""
国医大师孙光荣中医知识图谱 · 智能问答（Gradio）
Sun Guangrong TCM Knowledge Graph — RAG chat UI

研发：孙光荣大师弟子田建辉团队 联合 医哲未来人工智能研究院（IMPF-AI Institute）

左侧多轮对话，右侧同步展示本轮 RAG 实际检索到的知识图谱数据
（子图 / 实体表 / 三元组与原文佐证 / 送入模型的完整上下文），
答案与证据一屏对照，便于核验，不做黑箱。
"""

from __future__ import annotations

import os
import traceback

import inspect

import gradio as gr

from kg_rag import (DEFAULT_MAX_CHARS, DEFAULT_MAX_EDGES, DEFAULT_TOP_SEEDS, KGRag)
from llm_clients import (DEFAULT_MINIMAX_MODEL, DEFAULT_POE_MODEL, LLMError,
                         MINIMAX_BASE_CN, MINIMAX_BASE_INTL, MiniMaxClient, PoeClient)

SITE_CN = "国内站 api.minimax.chat"
SITE_INTL = "国际站 api.minimaxi.chat"

# 界面初值。Colab 启动格可以整体覆盖（见 build_demo 的 defaults 参数）。
UI_DEFAULTS = {
    "provider": "MiniMax",
    "poe_model": DEFAULT_POE_MODEL,
    "mm_model": DEFAULT_MINIMAX_MODEL,
    "mm_site": SITE_CN,
    "mm_group": "",
    "temperature": 0.3,
    "top_seeds": DEFAULT_TOP_SEEDS,
    "max_edges": DEFAULT_MAX_EDGES,
    "max_ctx": DEFAULT_MAX_CHARS,
}

SYSTEM_PROMPT = """你是「国医大师孙光荣中医知识图谱」的学术问答助手，由孙光荣大师弟子田建辉团队与医哲未来人工智能研究院（IMPF-AI Institute）联合研制。

作答规则：
1. 只依据【图谱证据】作答。证据里没有的内容，明确说「图谱中未见记载」，不得凭常识补充或杜撰。
2. 引用证据时标注编号，如「据 [R3]」；涉及原文时一并给出出处编号（如 D3#c0037）。
3. 区分知识来源：「孙光荣原创」是孙老本人的论断，「孙光荣编纂」是他选编他人内容，「经典引文」出自古籍，
   「他人临床报道」是其他医家的工作。凡属孙老本人观点，请明确说明；不要把他人观点说成孙老的。
4. 标注「⚑ 未通过本体校验」的关系，若要引用须注明其为待审信息。
5. 用中文作答，条理清晰；涉及辨证论治时按「病因病机 — 治则治法 — 方药」的顺序展开。
6. 结尾附一句提醒：本回答仅供学术研究与教学参考，不能替代执业医师的诊断与处方。

【图谱证据】之外的闲聊或与中医无关的问题，可以简短回应并引导回图谱主题。"""

CSS = """
.gradio-container{max-width:1400px!important;
  font-family:"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
#sgr-head{text-align:center;padding:16px 12px 12px;
  background:linear-gradient(180deg,#E3D5B9,#F3E9D6);border:1px solid rgba(36,28,21,.15);
  border-radius:4px;margin-bottom:10px;position:relative}
#sgr-head h1{font-family:"Noto Serif CJK SC","Songti SC",serif;font-size:23px;margin:0 0 2px;
  letter-spacing:.14em;color:#241C15}
#sgr-head .en{font-size:10px;letter-spacing:.2em;color:#7C6C58;text-transform:uppercase}
#sgr-head .team{margin-top:7px;font-family:"Noto Serif CJK SC","Songti SC",serif;
  font-size:12.5px;color:#4C4033;letter-spacing:.04em}
#sgr-head .seal{display:inline-block;background:#A8322A;color:#FBF3E4;border-radius:3px;
  padding:2px 9px;font-family:"Noto Serif CJK SC",serif;font-size:11px;letter-spacing:.2em}
.sgr-panel{background:#EDE1CA;border:1px solid rgba(36,28,21,.15);border-radius:4px;padding:8px}
.sgr-note{font-size:11.5px;color:#7C6C58;line-height:1.8}
footer{display:none!important}
"""

EXAMPLES = [
    "什么是「中和思想」？中和组方的基本原则是什么？",
    "孙光荣治疗脾胃病的学术观点有哪些？",
    "H7N9 禽流感在中医里属于什么范畴，分几个阶段辨证？",
    "带下病的外治法，图谱里有哪些记载？",
    "「三联药组」是什么？举几个孙老常用的药组。",
    "肿瘤的中医治疗思路，孙老怎么讲？",
]


def _c(cls, **kw):
    """
    Gradio 4/5/6 兼容层：只把当前版本签名里存在的参数传下去。
    （Gradio 6 移除了 Chatbot(type=...)、show_copy_button，并把 theme/css 从
      Blocks 挪到了 launch()；Colab 上装到哪个版本不由我们决定，故做签名过滤。）
    """
    allowed = set(inspect.signature(cls.__init__).parameters)
    return cls(**{k: v for k, v in kw.items() if k in allowed})


def _launch_kw(**kw):
    allowed = set(inspect.signature(gr.Blocks.launch).parameters)
    return {k: v for k, v in kw.items() if k in allowed and v is not None}


def _blocks_kw(**kw):
    allowed = set(inspect.signature(gr.Blocks.__init__).parameters)
    return {k: v for k, v in kw.items() if k in allowed}


def _client(provider, poe_key, poe_model, mm_key, mm_model, mm_site, mm_group):
    if provider == "Poe":
        return PoeClient(poe_key or os.environ.get("POE_API_KEY", ""),
                         poe_model or DEFAULT_POE_MODEL)
    base = MINIMAX_BASE_INTL if mm_site == SITE_INTL else MINIMAX_BASE_CN
    return MiniMaxClient(mm_key or os.environ.get("MINIMAX_API_KEY", ""),
                         mm_model or DEFAULT_MINIMAX_MODEL,
                         base_url=base, group_id=mm_group or "")


def build_demo(kg: KGRag, share_note: str = "", show_settings: bool = True,
               defaults: dict | None = None) -> gr.Blocks:
    """
    show_settings=False 时「模型与检索设置」面板整体隐藏（组件仍然存在并生效，
    只是不显示），适合把参数在 Colab 里定好后交付给他人使用的场景。
    """
    D = dict(UI_DEFAULTS)
    if defaults:
        D.update({k: v for k, v in defaults.items() if v is not None and v != ""})

    def check_model(provider, poe_model, mm_model):
        try:
            if provider == "Poe":
                actual, note = PoeClient("", poe_model or DEFAULT_POE_MODEL).resolve_model()
                return f"当前将使用 Poe 模型：**{actual}**　{note}"
            return f"当前将使用 MiniMax 模型：**{mm_model or DEFAULT_MINIMAX_MODEL}**"
        except Exception as e:
            return f"模型校验失败：{e}"

    def respond(message, chat, provider, poe_key, poe_model, mm_key, mm_model,
                mm_site, mm_group, temperature, top_seeds, max_edges, max_ctx, focus):
        message = (message or "").strip()
        if not message:
            yield chat, gr.update(), gr.update(), gr.update(), gr.update(), "请输入问题。", focus
            return

        chat = list(chat or [])
        chat.append({"role": "user", "content": message})

        # ---- 1. 检索：先把图谱证据摆出来，用户不必等模型 ----
        r = kg.retrieve(message, focus_entities=focus or [],
                        top_seeds=int(top_seeds), max_edges=int(max_edges))
        svg = r.svg()
        ents, tris = r.entity_rows(), r.triple_rows()
        context = r.context(max_chars=int(max_ctx))
        stat = (f"本轮检索：种子实体 {len(r.seeds)} · 子图实体 {len(r.nodes)} · "
                f"关系 {len(r.edges)} · 上下文 {len(context)} 字")

        chat.append({"role": "assistant", "content": "正在依据图谱证据作答…"})
        yield chat, svg, ents, tris, context, stat, focus

        # ---- 2. 生成 ----
        try:
            client = _client(provider, poe_key, poe_model, mm_key, mm_model, mm_site, mm_group)
            if provider == "Poe":
                actual, note = client.resolve_model()
                if actual != client.model:
                    client.model = actual
                    stat += f"　|　{note}"

            history_msgs = []
            for m in chat[:-2][-8:]:          # 近 4 轮，控制上下文长度
                if m.get("role") in ("user", "assistant") and m.get("content"):
                    history_msgs.append({"role": m["role"], "content": m["content"]})

            msgs = ([{"role": "system", "content": SYSTEM_PROMPT}] + history_msgs +
                    [{"role": "user", "content": f"{context}\n\n———\n用户问题：{message}"}])

            acc = ""
            for piece in client.stream(msgs, temperature=float(temperature), max_tokens=2048):
                acc += piece
                chat[-1] = {"role": "assistant", "content": acc}
                yield chat, svg, ents, tris, context, stat, focus
            if not acc.strip():
                chat[-1] = {"role": "assistant", "content": "（模型未返回内容，请重试或更换模型）"}
                yield chat, svg, ents, tris, context, stat, focus
        except LLMError as e:
            chat[-1] = {"role": "assistant",
                        "content": f"⚠ {e}\n\n右侧「RAG 知识图谱数据」面板仍展示了本轮检索到的图谱证据，可直接查阅。"}
            yield chat, svg, ents, tris, context, stat, focus
        except Exception:
            chat[-1] = {"role": "assistant", "content": "⚠ 生成出错：\n```\n" + traceback.format_exc()[-900:] + "\n```"}
            yield chat, svg, ents, tris, context, stat, focus
            return

        # ---- 3. 记住本轮核心实体，供下一轮指代消解（「它」「这个方」…）----
        yield chat, svg, ents, tris, context, stat, kg.entity_names(r, 3)

    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.red, neutral_hue=gr.themes.colors.stone,
        font=["Noto Sans CJK SC", "PingFang SC", "sans-serif"],
    )

    with gr.Blocks(**_blocks_kw(title="国医大师孙光荣中医知识图谱 · 智能问答",
                               theme=theme, css=CSS)) as demo:
        gr.HTML(f"""
        <div id="sgr-head">
          <span class="seal">中和</span>
          <h1>国医大师孙光荣中医知识图谱 · 智能问答</h1>
          <div class="en">Sun Guangrong TCM Knowledge Graph — Graph-RAG Assistant</div>
          <div class="team">孙光荣大师弟子 <b>田建辉</b> 团队　联合研发　<b>医哲未来人工智能研究院</b>（IMPF-AI Institute）</div>
          <div class="en" style="margin-top:5px">
            {kg.degree.size:,} 实体 · {len(kg.edges):,} 关系 · 8 部文献 · 检索增强问答{share_note}</div>
        </div>""")

        focus = gr.State([])

        with gr.Row():
            # ------------------ 左：多轮对话 ------------------
            with gr.Column(scale=9):
                chatbot = _c(gr.Chatbot, type="messages", height=560, label="问答",
                             avatar_images=(None, None), show_copy_button=True)
                with gr.Row():
                    box = _c(gr.Textbox, placeholder="请就孙光荣学术思想、辨证、方药、医案提问…",
                             scale=8, lines=2, max_lines=6, show_label=False, autofocus=True)
                    send = gr.Button("问 道", variant="primary", scale=1, min_width=88)
                with gr.Row():
                    clear = gr.Button("清空对话", size="sm", scale=1)
                    gr.Markdown("", scale=4)
                status = gr.Markdown("", elem_classes="sgr-note")
                gr.Examples(EXAMPLES, inputs=box, label="示例问题")

            # ------------------ 右：RAG 知识图谱数据 ------------------
            with gr.Column(scale=11):
                gr.Markdown("### RAG 知识图谱数据\n"
                            "<span class='sgr-note'>本轮回答实际依据的图谱证据，与左侧答案一一对应。</span>")
                with gr.Tab("检索子图"):
                    sub_svg = _c(gr.HTML,
                                 value="<div style='padding:28px;text-align:center;color:#7C6C58'>"
                                       "提问后在此展示检索到的子图</div>", label="检索子图")
                with gr.Tab("三元组与佐证"):
                    tri_df = _c(gr.Dataframe, headers=r_headers_tri(), interactive=False,
                                wrap=True, max_height=520, show_label=False,
                                column_widths=["7%", "17%", "11%", "17%", "31%", "12%", "10%", "7%"])
                with gr.Tab("实体"):
                    ent_df = _c(gr.Dataframe, headers=r_headers_ent(), interactive=False,
                                wrap=True, max_height=520, show_label=False,
                                column_widths=["6%", "26%", "13%", "14%", "13%", "9%", "22%"])
                with gr.Tab("送入模型的上下文"):
                    ctx_box = _c(gr.Textbox, lines=22, max_lines=22, show_label=False,
                                 show_copy_button=True, interactive=False)

        # ------------------ 设置（可整体隐藏） ------------------
        with _c(gr.Accordion, label="模型与检索设置", open=False, visible=show_settings):
            with gr.Row():
                provider = gr.Radio(["MiniMax", "Poe"], value=D["provider"],
                                    label="模型提供方", scale=2)
                temperature = gr.Slider(0.0, 1.0, value=D["temperature"], step=0.05,
                                        label="温度", scale=3)
            with gr.Row():
                with gr.Column():
                    gr.Markdown("**MiniMax**　密钥在开放平台「账户管理 - 接口密钥」获取")
                    mm_model = gr.Textbox(D["mm_model"], label="MiniMax 模型")
                    mm_key = _c(gr.Textbox, value="", label="MiniMax API Key", type="password",
                                placeholder="留空则用环境变量 MINIMAX_API_KEY")
                    mm_site = gr.Radio([SITE_CN, SITE_INTL], value=D["mm_site"], label="接入站点")
                    mm_group = gr.Textbox(D["mm_group"], label="GroupId（可选）")
                with gr.Column():
                    gr.Markdown("**Poe**　密钥在 https://poe.com/api_key 获取")
                    poe_model = _c(gr.Textbox, value=D["poe_model"], label="Poe 模型",
                                   info="Poe 上尚未上架时会自动退到同族最新版")
                    poe_key = _c(gr.Textbox, value="", label="Poe API Key", type="password",
                                 placeholder="留空则用环境变量 POE_API_KEY")
            with gr.Row():
                top_seeds = gr.Slider(3, 60, value=D["top_seeds"], step=1, label="种子实体数")
                max_edges = gr.Slider(12, 300, value=D["max_edges"], step=4, label="检索关系数")
                max_ctx = gr.Slider(2000, 20000, value=D["max_ctx"], step=100,
                                    label="上下文字数上限")
            check_btn = gr.Button("校验当前模型名", size="sm")
            check_out = gr.Markdown("")
            check_btn.click(check_model, [provider, poe_model, mm_model], check_out)

        gr.Markdown(
            "<div class='sgr-note' style='text-align:center;margin-top:10px'>"
            "本应用为中医药学术研究与教学参考工具，所载内容由文献自动抽取并经抽样审校，"
            "<b>不能替代执业医师的诊断与处方</b>，请勿据此自行用药。<br>"
            "孙光荣大师弟子田建辉团队 × 医哲未来人工智能研究院（IMPF-AI Institute）"
            "</div>")

        ins = [box, chatbot, provider, poe_key, poe_model, mm_key, mm_model,
               mm_site, mm_group, temperature, top_seeds, max_edges, max_ctx, focus]
        outs = [chatbot, sub_svg, ent_df, tri_df, ctx_box, status, focus]
        send.click(respond, ins, outs).then(lambda: "", None, box)
        box.submit(respond, ins, outs).then(lambda: "", None, box)
        clear.click(lambda: ([], [], ""), None, [chatbot, focus, status])

    return demo


def r_headers_ent():
    from kg_rag import Retrieval
    return Retrieval.ENTITY_HEADERS


def r_headers_tri():
    from kg_rag import Retrieval
    return Retrieval.TRIPLE_HEADERS


def launch(demo, share=False, port=7860, auth=None, quiet=False):
    """统一的启动入口：Colab 与本地共用，屏蔽 Gradio 版本差异。"""
    theme = gr.themes.Base(primary_hue=gr.themes.colors.red,
                           neutral_hue=gr.themes.colors.stone)
    return demo.queue(default_concurrency_limit=4).launch(
        **_launch_kw(share=share, server_port=port, server_name="0.0.0.0",
                     auth=auth, show_api=False, quiet=quiet, theme=theme, css=CSS,
                     inline=False, debug=False))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="孙光荣中医知识图谱 · RAG 问答")
    ap.add_argument("--graph", default="graph.json", help="graph.json 或原始 explorer.html")
    ap.add_argument("--share", action="store_true", help="生成公网可访问链接")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--user", default="", help="可选：访问用户名")
    ap.add_argument("--password", default="", help="可选：访问密码")
    ap.add_argument("--hide-settings", action="store_true", help="隐藏「模型与检索设置」面板")
    a = ap.parse_args()

    kg = KGRag(a.graph)
    demo = build_demo(kg, show_settings=not a.hide_settings)
    launch(demo, share=a.share, port=a.port,
           auth=(a.user, a.password) if a.user and a.password else None)


if __name__ == "__main__":
    main()
