"""编排:问题 → agent 循环 → AskResponse(计时 + 轨迹)。

流式(ask_stream)产出 (event, payload) 二元组,SSE 语义在 api 层编码:
  sources → agent 每执行完一个工具调用,推累计 steps(与 rag-qa 的 hits 同位);
  delta   → 中文结论分段增量(final_answer 一次产出,服务端按句切分下发);
  done    → 权威终态(完整 AskResponse,含 chart_spec/chart_reading)。
error 事件由 api 层统一捕获下发(LLM 繁忙/未预期异常);agent 内部优雅降级
(error 字段)仍走 done,不在传输层混淆。
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from functools import lru_cache

from .agent import AgentResult, ChatbiAgent
from .charts import build_chart
from .db import connect_ro
from .llm import LLM
from .schemas import AskResponse

# delta 分段:按句切、攒够约 24 字下发,配 10ms 间隔营造打字机节奏;
# 内容与 done.summary 严格一致,只是呈现节奏(总增量耗时 <1s)
_DELTA_MIN_CHARS = 24
_DELTA_GAP_S = 0.01
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n…])")


class ChatbiService:
    def __init__(self, agent_factory):
        """agent_factory: () -> ChatbiAgent,每次请求新建(持有只读连接)。"""

        self.agent_factory = agent_factory

    def ask(self, question: str) -> AskResponse:
        t0 = time.perf_counter()
        agent = self.agent_factory()
        try:
            r = agent.run(question)
        finally:
            agent.conn.close()  # 每请求一个只读连接,跑完即回收,长期运行不积累句柄
        return self._respond(question, r, t0)

    def ask_stream(self, question: str) -> Iterator[tuple[str, dict]]:
        t0 = time.perf_counter()
        agent = self.agent_factory()
        try:
            for _step in agent.stream(question):
                r = agent.last_result
                # 推累计步骤而非单步:前端无脑替换即可,漏帧也能自愈
                yield "sources", {"steps": [s.model_dump() for s in r.steps]}
            r = agent.last_result
        finally:
            agent.conn.close()
        for chunk in _split_summary(r.summary):
            yield "delta", {"text": chunk}
            time.sleep(_DELTA_GAP_S)
        yield "done", self._respond(question, r, t0).model_dump()

    @staticmethod
    def _respond(question: str, r: AgentResult, t0: float) -> AskResponse:
        # 图表与解读只在拿到最终结果时生成:纯呈现层,选型和数字
        # 全部来自已执行的 columns/rows,不影响 agent 与评估口径
        chart_spec, chart_reading = (None, "")
        if r.error is None and r.result is not None and r.result.row_count:
            chart_spec, chart_reading = build_chart(question, r.result.columns, r.result.rows)
        return AskResponse(
            question=question,
            summary=r.summary,
            sql=r.sql,
            columns=r.result.columns if r.result else [],
            rows=r.result.rows if r.result else [],
            row_count=r.result.row_count if r.result else 0,
            chart_spec=chart_spec,
            chart_reading=chart_reading,
            steps=r.steps,
            error=r.error,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            stats=r.stats,
        )


def _split_summary(text: str) -> Iterator[str]:
    """中文结论按句切分、攒够 _DELTA_MIN_CHARS 下发;短结论整体一段。"""
    buf = ""
    for part in _SENTENCE_SPLIT.split(text):
        buf += part
        if len(buf) >= _DELTA_MIN_CHARS:
            yield buf
            buf = ""
    if buf:
        yield buf


@lru_cache(maxsize=1)
def get_service() -> ChatbiService:
    from .config import get_settings

    s = get_settings()

    def factory() -> ChatbiAgent:
        return ChatbiAgent(
            LLM.from_settings(),
            connect_ro(s.db_path),
            max_steps=s.max_tool_steps,
            cap=s.sql_row_cap,
            auto_limit=s.auto_limit,
            self_heal=s.self_heal,
            max_sql_retries=s.max_sql_retries,
            sql_timeout_s=s.sql_timeout_s,
        )

    return ChatbiService(factory)
