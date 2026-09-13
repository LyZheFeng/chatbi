"""内网 vLLM(OpenAI 兼容)薄封装:固定 temperature=0、关闭思维链。

网络健壮性走 openai SDK 内建重试(max_retries,连接错误/429/5xx 自动指数退避),
次数由 Settings.llm_max_retries 显式配置;熔断/fallback 模型属部署层,不在 v0.1 范围。
"""

from __future__ import annotations

from functools import lru_cache

from openai import OpenAI


class LLM:
    def __init__(self, client: OpenAI, model: str, timeout: int = 90):
        self.client = client
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> "LLM":
        from .config import get_settings

        s = get_settings()
        return LLM(
            OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=90,
                   max_retries=s.llm_max_retries),
            s.llm_model,
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
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message
