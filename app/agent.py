"""function calling agent 循环:中文问题 → 工具调用序列 → 结构化结果。

自愈策略(Day 17-18):
- SQL 报错 → 错误信息 + 分类提示原样回传模型修正重试,连续失败上限 max_sql_retries;
- 空结果/异常结果(单列全 0/NULL)→ 追加反思提示,让模型判断"SQL 写错还是数据本身如此";
- self_heal=False 时关闭以上两条(首错即降级),用于开关对比实验;
- 任何超限都优雅降级:error 字段写明原因,绝不编造表格。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from .db import run_select
from .llm import LLM
from .schemas import FinalAnswerArgs, SqlResult, ToolStep
from .tools import TOOL_SPECS, ToolError, dispatch

SYSTEM_PROMPT = """你是数据分析 agent(ChatBI),连接一个 SQLite 电商订单库(Global Superstore,全球零售 2013-2014,金额单位美元)。

工作流程:
1. 先调用 get_schema 查看表结构(开头是表关系图;DDL 注释里有列的业务含义和枚举列的实际取值);
2. 编写 SQLite SELECT 语句,调用 execute_sql 执行;
3. 拿到结果后调用 final_answer 给出中文结论。

SQL 约定:
- 只写单条 SELECT;日期列为 TEXT 'YYYY-MM-DD',按月汇总用 strftime('%Y-%m', order_date),按季度汇总用 (CAST(strftime('%m', order_date) AS INTEGER) - 1) / 3 + 1;
- 中位数:非空值排序后,奇数个取正中值,偶数个取中间两值的平均(如再套一层 AVG),最终只返回一个数值;
- 枚举列(market / segment / category / sub_category / ship_mode / order_priority)的实际取值已写在 DDL 注释里,过滤条件直接照抄注释中的值,不要自造缩写(如把 Asia Pacific 写成 APAC);
- 明细在 order_items,需要订单/客户/商品信息时按外键 JOIN;geography 只能经 customers 的 (country, region) 关联到达;
- 执行报错时读错误信息修正 SQL 重试;结果为空或异常(全 0、大量 NULL)时先检查 JOIN 条件和过滤条件,再考虑是否数据本身如此。

数据已知问题(如实反映,不要脑补):
- customers.postal_code 约 80% 为 NULL;
- 个别客户 region 缺失(关联 geography 会丢这几单);
- 个别明细 quantity 为 0 或负数、sales 为 NULL;
- 2 张订单 ship_date 早于 order_date。

final_answer 要求:summary 用中文直接回答用户问题,点出关键数字(从查询结果里来);sql 填最终用的那条。"""

REFLECTION_HINT = """

[反思提示] 本次查询结果为空或全为异常值,请先判断原因再继续:
(a) SQL 写错了——过滤条件过严、枚举值拼写与库中实际取值不一致(以 DDL 注释里的枚举为准,拿不准就 SELECT DISTINCT 该列核对)、日期范围内本就没有数据;可去掉过滤条件、或先 SELECT DISTINCT 该列核对实际取值,再修正重查;
(b) 数据本身如此——接受结果,用 final_answer 如实说明(库里有少量脏数据,见系统说明)。"""


def _error_hint(msg: str) -> str:
    """按 SQLite 报错内容附一句定向提示,帮模型少走弯路。"""
    m = msg.lower()
    if "no such table" in m:
        return "\n[提示] 表名不存在,请先 get_schema 核对可用表名。"
    if "no such column" in m:
        return "\n[提示] 列名不存在,请核对 DDL 里的列名,不要自造同义词(如把 sales 写成 revenue)。"
    if "syntax error" in m or "unrecognized token" in m or "incomplete input" in m or "near" in m:
        return "\n[提示] SQL 语法问题,检查引号/括号/关键字拼写。"
    if "no such function" in m:
        return "\n[提示] SQLite 没有这个函数,日期处理用 strftime() / date()。"
    if "only allows" in m or "只读" in m or "多条" in m:
        return "\n[提示] 只允许单条 SELECT 只读查询。"
    if "超时" in msg:
        return "\n[提示] 查询超时说明扫描量过大:加 WHERE 过滤、缩小时间范围或加 LIMIT,不要无界 JOIN/递归。"
    return ""


def _looks_suspicious(r: SqlResult) -> bool:
    """空结果,或单列数值全为 0/NULL(常见于过滤条件写错导致聚合落空)。"""
    if r.row_count == 0:
        return True
    if len(r.columns) == 1:
        vals = [row[0] for row in r.rows]
        if vals and all(v is None or v == 0 for v in vals):
            return True
    return False


@dataclass
class AgentResult:
    summary: str = ""
    sql: str | None = None
    result: SqlResult | None = None
    steps: list[ToolStep] = field(default_factory=list)
    error: str | None = None
    stats: dict[str, int] = field(default_factory=lambda: {"sql_attempts": 0, "sql_failures": 0, "reflections": 0})
    sql_fail_streak: int = 0  # execute_sql 连续失败计数(成功即清零)


class ChatbiAgent:
    def __init__(
        self,
        llm: LLM,
        conn: sqlite3.Connection,
        *,
        max_steps: int = 8,
        cap: int = 200,
        auto_limit: int = 100,
        self_heal: bool = True,
        max_sql_retries: int = 3,
        sql_timeout_s: float = 5.0,
        sql_mutator: Callable[[str], str] | None = None,
    ):
        self.llm = llm
        self.conn = conn
        self.max_steps = max_steps
        self.cap = cap
        self.auto_limit = auto_limit
        self.self_heal = self_heal
        self.max_sql_retries = max_sql_retries
        self.sql_timeout_s = sql_timeout_s
        # 故障注入实验用(评估脚本 --chaos):仅改坏每次 run 的第一次 execute_sql,
        # 生产链路恒为 None
        self.sql_mutator = sql_mutator
        self._mutated_once = False

    def run(self, question: str) -> AgentResult:
        state = AgentResult()
        try:
            self._run_loop(question, state)
            return state
        finally:
            # token 用量汇总(FakeLLM 无此属性时记 0,不影响离线测试)
            state.stats["llm_tokens"] = getattr(self.llm, "used_tokens", 0)

    def _run_loop(self, question: str, state: AgentResult) -> None:
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
                if self._execute(state, messages, tc):
                    return

        if state.error is None:
            state.error = f"达到工具调用步数上限({self.max_steps}),未能产出最终答案。"

    def _execute(self, state: AgentResult, messages: list, tc) -> bool:
        """执行单个 tool_call。返回 True 表示循环应结束(final_answer 已给出或已降级)。"""
        name = tc.function.name
        step_no = len(state.steps) + 1
        degrade: str | None = None

        raw_args = tc.function.arguments
        if name == "execute_sql" and self.sql_mutator is not None and not self._mutated_once:
            self._mutated_once = True
            try:
                obj = json.loads(raw_args or "{}")
                if isinstance(obj.get("sql"), str):
                    obj["sql"] = self.sql_mutator(obj["sql"])
                    raw_args = json.dumps(obj, ensure_ascii=False)
            except json.JSONDecodeError:
                pass

        try:
            text, sql_result = dispatch(
                self.conn, name, raw_args, cap=self.cap, auto_limit=self.auto_limit,
                timeout_s=self.sql_timeout_s,
            )
            if name == "execute_sql" and sql_result is not None:
                state.result = sql_result  # 记住最近一次成功查询(final_answer 组装表格用)
                state.stats["sql_attempts"] += 1
                state.sql_fail_streak = 0  # 成功即清零连续失败计数
                if self.self_heal and _looks_suspicious(sql_result):
                    state.stats["reflections"] += 1
                    text += REFLECTION_HINT
        except ToolError as e:
            text, sql_result = f"ERROR: {e}", None
            if name == "execute_sql":
                state.stats["sql_attempts"] += 1
                state.stats["sql_failures"] += 1
                state.sql_fail_streak += 1
                text += _error_hint(str(e))
                if not self.self_heal:
                    degrade = f"SQL 执行失败(自愈已关闭,不重试):{e}"
                elif state.sql_fail_streak >= self.max_sql_retries:
                    degrade = (
                        f"SQL 连续 {self.max_sql_retries} 次执行失败,已停止重试。最后一次错误:{e}"
                    )

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

        if degrade is not None:
            state.error = degrade
            return True

        if name == "final_answer" and not text.startswith("ERROR"):
            args = FinalAnswerArgs(**json.loads(tc.function.arguments or "{}"))
            state.summary = args.summary
            state.sql = args.sql
            if args.sql:
                # 自报 SQL 本地重执行,保证"展示的 SQL ↔ 展示的表格"一致:
                # 模型可能在最终计数后又跑过探查性查询,直接用"最近一次结果"会对不上结论
                try:
                    state.result = run_select(self.conn, args.sql, cap=self.cap, auto_limit=self.auto_limit, timeout_s=self.sql_timeout_s)
                except (ValueError, sqlite3.Error):
                    pass  # 自报 SQL 跑不动时保留最近一次成功结果
            elif state.result is not None:
                state.sql = state.result.executed_sql
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
