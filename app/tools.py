"""三个工具的 OpenAI 定义 + 本地执行器。

工具协议(function calling)的职责边界:
- get_schema / execute_sql / final_answer 都只是"模型表达意图"的通道;
- arguments 一律先过 pydantic 校验再执行,表格数据一律来自本地执行结果,
  模型自报的数字不进业务字段(防编造)。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import ValidationError

from . import db
from .schemas import ExecuteSqlArgs, FinalAnswerArgs, GetSchemaArgs, SqlResult

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": "获取数据库表结构(建表 DDL,含中文列注释和行数)。回答任何数据问题前应先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "只要部分表时传入表名;不传返回全部 5 张表",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "执行一条只读 SELECT(SQLite 方言)查询电商订单库,返回列名和数据行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "单条 SELECT 语句;日期是 TEXT 'YYYY-MM-DD'"}
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "给出最终结论:基于查询结果的中文自然语言回答(summary)+ 所用 SQL(sql)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "中文结论,直接回答用户问题,含关键数字"},
                    "sql": {"type": "string", "description": "得出该结论使用的 SQL"},
                },
                "required": ["summary"],
            },
        },
    },
]


class ToolError(Exception):
    """工具执行失败(参数不合法或 SQL 报错)。消息会回传给模型供其修正。"""


def dispatch(conn: sqlite3.Connection, name: str, arguments: str, *, cap: int = 200, auto_limit: int = 100) -> tuple[str, SqlResult | None]:
    """执行一个工具调用,返回 (给模型看的结果文本, 最近的 SqlResult)。

    校验/执行失败抛 ToolError,由 agent 捕获——错误信息原样回传模型,
    让它自己修正重试(Day 17-18 自愈循环的入口)。
    """
    try:
        if name == "get_schema":
            args = GetSchemaArgs(**_parse(arguments))
            return db.schema_text(conn, args.tables), None
        if name == "execute_sql":
            args = ExecuteSqlArgs(**_parse(arguments))
            result = db.run_select(conn, args.sql, cap=cap, auto_limit=auto_limit)
            return _format_result(result), result
        if name == "final_answer":
            FinalAnswerArgs(**_parse(arguments))  # 只做校验,汇总在 agent 层完成
            return "OK", None
        raise ToolError(f"未知工具:{name}")
    except ValidationError as e:
        raise ToolError(f"参数校验失败:{e.errors(include_url=False)[:2]}") from e
    except (ValueError, sqlite3.Error) as e:
        raise ToolError(f"{type(e).__name__}: {e}") from e


def _parse(arguments: str) -> dict[str, Any]:
    import json

    try:
        obj = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        raise ToolError(f"arguments 不是合法 JSON:{e}") from e
    if not isinstance(obj, dict):
        raise ToolError("arguments 必须是 JSON 对象")
    return obj


def _format_result(r: SqlResult) -> str:
    """把查询结果压成模型友好的文本(首行列名,| 分隔)。"""
    lines = ["|".join(r.columns)] + ["|".join("" if v is None else str(v) for v in row) for row in r.rows]
    head = f"共 {r.row_count} 行{'(已截断,超过上限)' if r.truncated else ''}"
    return head + "\n" + "\n".join(lines)
