# -*- coding: utf-8 -*-
"""
Poe / MiniMax 对话客户端（流式）
Chat clients for Poe and MiniMax — streaming, dependency-light (requests only).

研发：孙光荣大师弟子田建辉团队 联合 医哲未来人工智能研究院（IMPF-AI Institute）

两家都提供「OpenAI 风格」的接口，但细节不同：
  · Poe      https://api.poe.com/v1/chat/completions    完全 OpenAI 兼容；
             GET /v1/models 无需鉴权即可列出全部可用模型，可据此校正模型名。
  · MiniMax  https://api.minimaxi.chat/v1/text/chatcompletion_v2  （国际站）
             https://api.minimax.chat/v1/text/chatcompletion_v2   （国内站）
             流式分片同为 choices[].delta.content，但错误码放在 base_resp 里，
             且最后一片会把完整文本重复放进 choices[].message.content，需要跳过。
"""

from __future__ import annotations

import json
import time

import requests

POE_BASE = "https://api.poe.com/v1"
MINIMAX_BASE_INTL = "https://api.minimaxi.chat/v1"
MINIMAX_BASE_CN = "https://api.minimax.chat/v1"

# 默认模型。Poe 的模型名是小写点号风格（claude-sonnet-4.6 / minimax-m3）。
DEFAULT_POE_MODEL = "claude-sonnet-5"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"


class LLMError(RuntimeError):
    pass


def _sse_lines(resp):
    """逐行读 SSE，产出 data: 后面的负载字符串。"""
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                yield payload
        elif line == "[DONE]":
            return


class PoeClient:
    """Poe 的 OpenAI 兼容接口。模型名即 Poe 上的 bot 名（小写）。"""

    name = "Poe"

    def __init__(self, api_key: str, model: str = DEFAULT_POE_MODEL,
                 base_url: str = POE_BASE, timeout: int = 180):
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_POE_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ---------- 模型目录 ----------
    def list_models(self):
        """Poe 的模型列表公开可读，不需要 API Key。"""
        r = requests.get(f"{self.base_url}/models", timeout=30)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", []) if m.get("id")]

    def resolve_model(self, desired: str | None = None):
        """
        校正模型名：目录里有就直接用；没有则在同族里挑最新的一个。
        Poe 上线新模型的时间可能晚于本项目，这样即使 claude-sonnet-5 尚未上架，
        也会自动退到 claude-sonnet-4.6，而不是直接报 404。
        返回 (实际模型名, 提示信息)。
        """
        desired = (desired or self.model or DEFAULT_POE_MODEL).strip()
        try:
            ids = self.list_models()
        except Exception as e:
            return desired, f"（未能读取 Poe 模型目录：{e}；仍按 {desired} 发起请求）"
        if desired in ids:
            return desired, ""
        low = desired.lower()
        family = low.split("-")[0] + ("-" + low.split("-")[1] if "-" in low else "")
        cands = [i for i in ids if i.lower().startswith(family)]
        if not cands:
            cands = [i for i in ids if i.lower().startswith(low.split("-")[0])]
        if not cands:
            return desired, f"⚠ Poe 目录中没有「{desired}」，也找不到同族替代，请从模型列表中另选。"

        def ver(mid):
            tail = mid.rsplit("-", 1)[-1]
            try:
                return float(tail)
            except ValueError:
                return -1.0

        pick = sorted(cands, key=ver, reverse=True)[0]
        return pick, f"⚠ Poe 目录中暂无「{desired}」，已自动改用同族最新的「{pick}」。"

    # ---------- 对话 ----------
    def stream(self, messages, temperature=0.3, max_tokens=2048):
        if not self.api_key:
            raise LLMError("未配置 Poe API Key（在 https://poe.com/api_key 获取）。")
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=body, stream=True, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"连接 Poe 失败：{e}")

        if r.status_code >= 400:
            raise LLMError(f"Poe 返回 {r.status_code}：{r.text[:400]}")

        for payload in _sse_lines(r):
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                raise LLMError(f"Poe 错误：{chunk['error']}")
            for ch in chunk.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    yield piece


class MiniMaxClient:
    """MiniMax chatcompletion_v2。默认国内站，可切国际站。"""

    name = "MiniMax"

    def __init__(self, api_key: str, model: str = DEFAULT_MINIMAX_MODEL,
                 base_url: str = MINIMAX_BASE_CN, group_id: str = "", timeout: int = 180):
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_MINIMAX_MODEL
        self.base_url = base_url.rstrip("/")
        self.group_id = (group_id or "").strip()
        self.timeout = timeout

    def list_models(self):
        # MiniMax 未提供公开的模型目录接口，给出常用取值供选择
        return ["MiniMax-M3", "MiniMax-M2", "MiniMax-Text-01", "abab6.5s-chat"]

    def resolve_model(self, desired: str | None = None):
        return (desired or self.model or DEFAULT_MINIMAX_MODEL).strip(), ""

    def stream(self, messages, temperature=0.3, max_tokens=2048):
        if not self.api_key:
            raise LLMError("未配置 MiniMax API Key（在 MiniMax 开放平台「账户管理-接口密钥」获取）。")
        url = f"{self.base_url}/text/chatcompletion_v2"
        if self.group_id:
            url += f"?GroupId={self.group_id}"
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": max(0.01, temperature),   # MiniMax 不接受 0
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=body, stream=True, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"连接 MiniMax 失败：{e}")

        if r.status_code >= 400:
            raise LLMError(f"MiniMax 返回 {r.status_code}：{r.text[:400]}")

        streamed = False
        for payload in _sse_lines(r):
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            br = chunk.get("base_resp") or {}
            if br.get("status_code"):
                raise LLMError(f"MiniMax 错误 {br.get('status_code')}：{br.get('status_msg')}")
            for ch in chunk.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    streamed = True
                    yield piece
                elif not streamed:
                    # 非流式兜底：某些情况下只在最后一片给出完整 message
                    full = (ch.get("message") or {}).get("content")
                    if full:
                        streamed = True
                        yield full


def make_client(provider: str, api_key: str, model: str = "", **kw):
    provider = (provider or "").strip().lower()
    if provider.startswith("poe"):
        return PoeClient(api_key, model or DEFAULT_POE_MODEL, **kw)
    if provider.startswith("mini"):
        return MiniMaxClient(api_key, model or DEFAULT_MINIMAX_MODEL, **kw)
    raise LLMError(f"未知的模型提供方：{provider}")


def selftest(client, prompt="用一句话说明「中和」在中医里的含义。"):
    """连通性自检：跑一次极短的请求，返回 (是否成功, 说明)。"""
    t0 = time.time()
    try:
        out = "".join(client.stream(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=120))
    except Exception as e:
        return False, f"✘ {client.name} 自检失败：{e}"
    return True, f"✔ {client.name} / {client.model} 连通（{time.time()-t0:.1f}s）：{out.strip()[:80]}…"
