"""function calling agent 循环:中文问题 → 工具调用序列 → 结构化结果。

策略:
- 每轮把工具结果以 role=tool 回传,报错也原样回传(自愈的种子);
- 模型不调工具时提醒一次,再犯就优雅降级(error 字段说明原因);
- 步数用尽同样降级,绝不编造表格数据。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .llm import LLM
from .schemas import FinalAnswerArgs, SqlResult, ToolStep
from .tools import TOOL_SPECS, ToolError, dispatch

SYSTEM_PROMPT = """你是数据分析 agent(ChatBI),连接一个 SQLite 电商订单库(Global Superstore,全球零售 2013-2014,金额单位美元)。

工作流程:
1. 先调用 get_schema 查看表结构(DDL 里有中文列注释);
2. 编写 SQLite SELECT 语句,调用 execute_sql 执行;
3. 拿到结果后调用 final_answer 给出中文结论。

SQL 约定:
- 只写单条 SELECT;日期列为 TEXT 'YYYY-MM-DD',按月汇总用 strftime('%Y-%m', order_date);
- 明细在 order_items,需要订单/客户/商品信息时按外键 JOIN;
- 执行报错时读错误信息修正 SQL 重试;结果为空或异常(全 0、大量 NULL)时先检查 JOIN 条件和过滤条件,再考虑是否数据本身如此。

数据已知问题(如实反映,不要脑补):
- customers.postal_code 约 80% 为 NULL;
- 个别客户 region 缺失(关联 geography 会丢这几单);
- 个别明细 quantity 为 0 或负数、sales 为 NULL;
- 2 张订单 ship_date 早于 order_date。

final_answer 要求:summary 用中文直接回答用户问题,点出关键数字(从查询结果里来);sql 填最终用的那条。"""


@dataclass
class AgentResult:
    summary: str = ""
    sql: str | None = None
    result: SqlResult | None = None
    steps: list[ToolStep] = field(default_factory=list)
    error: str | None = None


class ChatbiAgent:
    def __init__(self, llm: LLM, conn: sqlite3.Connection, *, max_steps: int = 8, cap: int = 200, auto_limit: int = 100):
        self.llm = llm
        self.conn = conn
        self.max_steps = max_steps
        self.cap = cap
        self.auto_limit = auto_limit

    def run(self, question: str) -> AgentResult:
        state = AgentResult()
        messages: list = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        nudged = False  # 是否已提醒过"请调用工具"

        while len(state.steps) < self.max_steps:
            msg = self.llm.chat(messages, tools=TOOL_SPECS)
            tool_calls = msg.tool_calls or []

            if not tool_calls:
                if not nudged and not msg.content:
                    nudged = True
                    messages.append({"role": "assistant", "content": msg.content or ""})
                    messages.append({"role": "user", "content": "请按流程调用工具完成分析,最后用 final_answer 作答。"})
                    continue
                state.error = "模型未调用 final_answer 即停止,已终止。"
                break

            messages.append(msg)  # 带 tool_calls 的 assistant 消息原样入列
            for tc in tool_calls:
                done = self._execute(state, messages, tc)
                if done:
                    return state

        if state.error is None:
            state.error = f"达到工具调用步数上限({self.max_steps}),未能产出最终答案。"
        return state

    def _execute(self, state: AgentResult, messages: list, tc) -> bool:
        """执行单个 tool_call。返回 True 表示循环应结束(final_answer 已给出)。"""
        name = tc.function.name
        step_no = len(state.steps) + 1
        try:
            text, sql_result = dispatch(
                self.conn, name, tc.function.arguments, cap=self.cap, auto_limit=self.auto_limit
            )
            if sql_result is not None:
                state.result = sql_result  # 记住最近一次成功查询
        except ToolError as e:
            text = f"ERROR: {e}"
            sql_result = None

        state.steps.append(
            ToolStep(
                step=step_no,
                tool=name,
                args=_short_args(name, tc.function.arguments),
                ok=not text.startswith("ERROR"),
                detail=text[:300],
            )
        )
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

        if name == "final_answer" and not text.startswith("ERROR"):
            args = FinalAnswerArgs(**json.loads(tc.function.arguments or "{}"))
            state.summary = args.summary
            state.sql = args.sql or (state.result.executed_sql if state.result else None)
            return True
        return False


def _short_args(name: str, arguments: str) -> dict:
    try:
        obj = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"_raw": (arguments or "")[:80]}
    if isinstance(obj, dict):
        return {k: (str(v)[:80] + ("…" if len(str(v)) > 80 else "")) for k, v in obj.items()}
    return {"_raw": str(obj)[:80]}
