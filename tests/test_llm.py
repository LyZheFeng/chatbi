"""llm.py:并发闸门与 token 用量统计(不依赖网络,fake client 驱动)。"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.llm import _GATES, LLMBusy, LLM


def _fake_client(usage_tokens: int = 0):
    """返回一个 chat.completions.create 可用的假 client,响应带 usage。"""
    resp = SimpleNamespace(
        usage=SimpleNamespace(total_tokens=usage_tokens),
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
    )

    def create(**kw):
        return resp

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_gate_timeout_raises_busy():
    llm = LLM(_fake_client(), "m", max_concurrency=1, gate_wait_s=0.05)
    gate = _GATES.setdefault(1, threading.BoundedSemaphore(1))
    gate.acquire()  # 占满并发额度
    try:
        with pytest.raises(LLMBusy):
            llm.chat([{"role": "user", "content": "hi"}])
    finally:
        gate.release()


def test_gate_released_after_call():
    llm = LLM(_fake_client(), "m", max_concurrency=1, gate_wait_s=1)
    gate = _GATES.setdefault(1, threading.BoundedSemaphore(1))
    llm.chat([{"role": "user", "content": "hi"}])
    assert gate.acquire(blocking=False)  # 调用结束必须已释放
    gate.release()


def test_token_usage_accumulates():
    llm = LLM(_fake_client(usage_tokens=5), "m", max_concurrency=1, gate_wait_s=1)
    llm.chat([{"role": "user", "content": "hi"}])
    llm.chat([{"role": "user", "content": "again"}])
    assert llm.used_tokens == 10


def test_agent_stats_carry_llm_tokens(conn):
    """agent.run 把 LLM 实例上的 used_tokens 汇总进 stats;FakeLLM 无该属性时记 0。"""
    from tests.test_agent import FakeLLM, _agent, _msg, _tc

    def _script():
        return [
            _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM orders")]),
            _msg([_tc("final_answer", summary="订单共 7 张。")]),
        ]

    r = _agent(conn, FakeLLM(_script())).run("多少张订单")
    assert r.stats["llm_tokens"] == 0  # 无属性 → 默认 0

    llm = FakeLLM(_script())
    llm.used_tokens = 123
    r2 = _agent(conn, llm).run("多少张订单")
    assert r2.stats["llm_tokens"] == 123  # 有属性 → 如实带回
