"""数据契约:SQL 执行结果、工具轨迹、LLM 工具参数、API 请求/响应。

所有 LLM 产生的结构化输出(tool_call arguments、final_answer 字段)在进入
业务代码前必须先过这里的 pydantic 模型校验(纪律沿袭项目 1)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------- LLM 工具参数契约(严格校验 tool_call arguments) ----------


class GetSchemaArgs(BaseModel):
    tables: list[str] | None = None  # None = 全部表


class ExecuteSqlArgs(BaseModel):
    sql: str = Field(min_length=6)


class FinalAnswerArgs(BaseModel):
    summary: str = Field(min_length=1)  # 中文结论
    sql: str | None = None              # 最终使用的 SQL(展示用)


# ---------- 执行结果 ----------


class SqlResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False   # 是否超过 row_cap 被截断
    executed_sql: str         # 实际执行的 SQL(自动补 LIMIT 后)


# ---------- agent 轨迹与对外响应 ----------


class ToolStep(BaseModel):
    """一次工具调用的记录(前端展示思考过程 / 排查问题用)。"""

    step: int
    tool: str                  # get_schema | execute_sql | final_answer
    args: dict[str, Any]
    ok: bool
    detail: str                # 结果摘要或错误信息(截断到 ~300 字符)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class AskResponse(BaseModel):
    question: str
    summary: str = ""          # final_answer 的中文结论
    sql: str | None = None     # 展示用 SQL
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    chart_spec: dict[str, Any] | None = None  # Vega-Lite 图表配置(UI 与接口共用一份)
    chart_reading: str = ""    # "怎么读这张图"的模板化解读(数字全部来自本地执行结果)
    steps: list[ToolStep] = Field(default_factory=list)
    error: str | None = None   # 优雅降级时的失败原因(不编造)
    latency_ms: int = 0
    stats: dict[str, int] = Field(default_factory=dict)  # sql_attempts / sql_failures / reflections
