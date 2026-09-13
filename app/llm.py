"""内网 vLLM(OpenAI 兼容)薄封装:固定 temperature=0、关闭思维链。

健壮性(Day 21 后追加):
- 网络重试走 openai SDK 内建(max_retries,连接错误/429/5xx 自动指数退避,Settings.llm_max_retries);
- 并发闸门:全局信号量限制同时在途的 LLM 调用数(llm_max_concurrency),闸门外排队
  llm_gate_wait_s 超时抛 LLMBusy(API 层转 503),不占线程死等;
- token 用量:每次调用累加 used_tokens,由 agent 汇总进 stats(观测最小集)。
"""

from __future__ import annotations

import threading

from openai import OpenAI

# 信号量按容量缓存共享:LLM 实例每请求新建,闸门必须跨请求
_GATES: dict[int, threading.BoundedSemaphore] = {}


class LLMBusy(RuntimeError):
    """LLM 并发已达上限且排队超时。"""


class LLM:
    def __init__(self, client: OpenAI, model: str, timeout: int = 90,
                 max_concurrency: int = 8, gate_wait_s: float = 30.0):
        self.client = client
        self.model = model
        self.timeout = timeout
        self.max_concurrency = max_concurrency
        self.gate_wait_s = gate_wait_s
        self.used_tokens = 0

    @classmethod
    def from_settings(cls) -> "LLM":
        from .config import get_settings

        s = get_settings()
        return LLM(
            OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=90,
                   max_retries=s.llm_max_retries),
            s.llm_model,
            max_concurrency=s.llm_max_concurrency,
            gate_wait_s=s.llm_gate_wait_s,
        )

    def chat(self, messages: list, tools: list | None = None):
        """一次对话调用。temperature=0 保证评估数字可复现。"""
        kwargs: dict = dict(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=0,
            max_tokens=2000,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        if tools is None:
            kwargs.pop("tools")
        gate = _GATES.setdefault(self.max_concurrency, threading.BoundedSemaphore(self.max_concurrency))
        if not gate.acquire(timeout=self.gate_wait_s):
            raise LLMBusy(f"LLM 并发已达上限({self.max_concurrency}),排队 {self.gate_wait_s}s 超时")
        try:
            resp = self.client.chat.completions.create(**kwargs)
        finally:
            gate.release()
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.used_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        return resp.choices[0].message
