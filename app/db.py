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

# 表关系图(schema 输出的固定头,Day 19):箭头 = 外键指向。
# geography 只能经 customers 的 (country, region) 复合键到达,是最容易 JOIN 错的一跳。
ER_DIAGRAM = """-- 表关系(→ 为外键指向;事实表是 order_items,一行 = 一张订单里的一种商品):
-- order_items.order_id → orders.order_id;order_items.product_id → products.product_id
-- orders.customer_id → customers.customer_id;customers.(country, region) → geography.(country, region)
-- geography 无独立入口,须经 customers 关联到达;customers.region 缺失的客户关联不上 geography"""

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
    """导出 表关系图 + 建表 DDL(含中文列注释、枚举取值)+ 每表行数。

    传入未知表名时给出明确提示(而不是静默丢弃),供模型自行纠正。
    只取部分表时关系图仍然返回——JOIN 路径信息与表数量无关。
    """
    requested = tables or TABLES
    wanted = [t for t in requested if t in TABLES] or TABLES
    unknown = [t for t in requested if t not in TABLES]
    parts = [ER_DIAGRAM]
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
