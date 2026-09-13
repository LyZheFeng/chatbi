"""编排:问题 → agent 循环 → AskResponse(计时 + 轨迹)。"""

from __future__ import annotations

import time
from functools import lru_cache

from .agent import ChatbiAgent
from .charts import build_chart
from .db import connect_ro
from .llm import LLM
from .schemas import AskResponse


class ChatbiService:
    def __init__(self, agent_factory):
        """agent_factory: () -> ChatbiAgent,每次请求新建(持有只读连接)。"""

        self.agent_factory = agent_factory

    def ask(self, question: str) -> AskResponse:
        t0 = time.perf_counter()
        agent = self.agent_factory()
        r = agent.run(question)
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
        )

    return ChatbiService(factory)
