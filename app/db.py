"""SQLite 只读访问:连接、schema 导出、带护栏的 SELECT 执行。

护栏(基础版,Day 21 再补超时/完整白名单):
- 连接只读(mode=ro),物理上写不进库
- 仅接受单条 SELECT / WITH 语句
- 未写 LIMIT 的 SQL 自动补默认上限;返回行数超过 cap 时截断并标记
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .schemas import SqlResult

TABLES = ["geography", "customers", "products", "orders", "order_items"]

_SELECT_ONLY = re.compile(r"^(select|with)\b", re.IGNORECASE)
_HAS_LIMIT = re.compile(r"\blimit\b", re.IGNORECASE)


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"数据库不存在:{path}(先跑 scripts/build_db.py)")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def schema_text(conn: sqlite3.Connection, tables: list[str] | None = None) -> str:
    """导出建表 DDL(含中文列注释,建库时写进 sqlite_master)+ 每表行数。

    传入未知表名时给出明确提示(而不是静默丢弃),供模型自行纠正。
    """
    requested = tables or TABLES
    wanted = [t for t in requested if t in TABLES] or TABLES
    unknown = [t for t in requested if t not in TABLES]
    parts = []
    for t in wanted:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()
        if ddl is None:
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        parts.append(f"{ddl[0].rstrip()}; -- 约 {n} 行")
    if unknown:
        parts.append(f"-- 未知表:{', '.join(unknown)}(可用表:{', '.join(TABLES)})")
    return "\n\n".join(parts)


def run_select(
    conn: sqlite3.Connection, sql: str, *, cap: int = 200, auto_limit: int = 100
) -> SqlResult:
    """执行一条受护栏保护的 SELECT,永不抛异常以外的东西(错误由调用方格式化回传)。"""
    sql = sql.strip().rstrip(";").strip()
    if not _SELECT_ONLY.match(sql):
        raise ValueError("仅允许 SELECT / WITH 开头的只读查询")
    if ";" in sql:
        raise ValueError("不允许一次执行多条语句")
    executed = sql if _HAS_LIMIT.search(sql) else f"{sql}\nLIMIT {auto_limit}"
    cur = conn.execute(executed)
    fetched = cur.fetchmany(cap + 1)
    truncated = len(fetched) > cap
    rows = [list(r) for r in fetched[:cap]]
    return SqlResult(
        columns=[d[0] for d in cur.description or []],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        executed_sql=executed,
    )
