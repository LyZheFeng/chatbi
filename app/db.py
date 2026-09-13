"""SQLite 只读访问:连接、schema 导出、带护栏的 SELECT 执行。

护栏(Day 21 加固后,三层):
- 连接只读(mode=ro),物理上写不进库——最后防线;
- token 级白名单:词法扫描(字符串/引号标识符/注释各自成 token,不会被关键字伪装绕过),
  首 token 必须 SELECT/WITH、禁止分号拼多条、禁 PRAGMA/ATTACH/EXPLAIN 等语句关键字、
  禁 load_extension/randomblob/pragma_* 等危险函数调用;
- 执行超时(progress_handler 按秒掐断)+ 未写 LIMIT 自动补上限 + cap 截断——防资源耗尽。
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from .schemas import SqlResult

TABLES = ["geography", "customers", "products", "orders", "order_items"]

# 表关系图(schema 输出的固定头,Day 19):箭头 = 外键指向。
# geography 只能经 customers 的 (country, region) 复合键到达,是最容易 JOIN 错的一跳。
ER_DIAGRAM = """-- 表关系(→ 为外键指向;事实表是 order_items,一行 = 一张订单里的一种商品):
-- order_items.order_id → orders.order_id;order_items.product_id → products.product_id
-- orders.customer_id → customers.customer_id;customers.(country, region) → geography.(country, region)
-- geography 无独立入口,须经 customers 关联到达;customers.region 缺失的客户关联不上 geography"""

# ---------- token 级 SQL 护栏(Day 21) ----------

# 词法:空白/行注释/块注释/字符串/三种引号标识符/词/其他单字符,各成一个 token。
_TOKEN_RE = re.compile(
    r"""\s+ | --[^\n]* | /\*.*?\*/ | '(?:[^']|'')*' | "(?:[^"]|"")*" | `[^`]*` | \[[^\]]*\] | [A-Za-z_][A-Za-z0-9_$]* | .""",
    re.VERBOSE | re.DOTALL,
)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")

# 语句级关键字:只读库里多数本来写不进去,但 ATTACH/PRAGMA/EXPLAIN 仍可能越界,一律前置拒绝。
_FORBIDDEN_KEYWORDS = {
    "PRAGMA", "ATTACH", "DETACH", "EXPLAIN", "VACUUM", "ANALYZE", "REINDEX",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
    "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER",
}
# 危险函数:扩展加载 / 大内存分配 / 文件读写(shell 函数)/ 未知副作用一并不赌。
_FORBIDDEN_FUNCS = {
    "LOAD_EXTENSION", "RANDOMBLOB", "ZEROBLOB", "READFILE", "WRITEFILE", "EDIT",
}


def _guard_sql(sql: str) -> tuple[str, bool]:
    """词法校验,返回 (去掉结尾分号/注释的干净 SQL, 是否含真正的 LIMIT 子句)。

    不合法抛 ValueError(消息回传模型自愈)。LIMIT 也按词法 token 判定:
    字符串字面量或注释里出现的 'limit' 不算,不会被用来绕过自动行数上限。
    """
    toks = [(m.group(0), m.span()) for m in _TOKEN_RE.finditer(sql)]

    def meaningful():
        return [(t, s) for t, s in toks if not (t.isspace() or t.startswith("--") or t.startswith("/*"))]

    meat = meaningful()
    if not meat or not _WORD_RE.fullmatch(meat[0][0]) or meat[0][0].upper() not in ("SELECT", "WITH"):
        raise ValueError("仅允许 SELECT / WITH 开头的只读查询")

    # 结尾若是分号则连同其后注释一起剥掉;剥完仍剩分号 = 多条语句
    cut = len(sql)
    if meat[-1][0] == ";":
        cut = meat[-1][1][0]
        meat = meat[:-1]
    if any(t == ";" for t, _ in meat):
        raise ValueError("不允许一次执行多条语句")

    has_limit = False
    for i, (t, _) in enumerate(meat):
        if not _WORD_RE.fullmatch(t):
            continue
        up = t.upper()
        if up == "LIMIT":
            has_limit = True
        if up in _FORBIDDEN_KEYWORDS:
            raise ValueError(f"只读护栏:禁止 {up}")
        if up in _FORBIDDEN_FUNCS or up.startswith("PRAGMA_"):
            nxt = meat[i + 1][0] if i + 1 < len(meat) else ""
            if nxt == "(" or up.startswith("PRAGMA_"):
                raise ValueError(f"只读护栏:禁止函数 {up}")
    return sql[:cut].strip(), has_limit


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
    conn: sqlite3.Connection, sql: str, *, cap: int = 200, auto_limit: int = 100,
    timeout_s: float = 5.0,
) -> SqlResult:
    """执行一条受护栏保护的 SELECT,永不抛异常以外的东西(错误由调用方格式化回传)。

    timeout_s 用 progress_handler 实现:虚拟机每跑 N 条指令回调一次,超过期限返回非零
    触发 SQLITE_INTERRUPT,防 RECURSIVE CTE / 笛卡尔积一类资源耗尽(连接只读挡不住算力攻击)。
    """
    guarded, has_limit = _guard_sql(sql.strip())
    executed = guarded if has_limit else f"{guarded}\nLIMIT {auto_limit}"
    deadline = time.monotonic() + timeout_s

    def _abort() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_abort, 10_000)
    try:
        cur = conn.execute(executed)
        fetched = cur.fetchmany(cap + 1)
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e).lower():
            raise ValueError(
                f"查询超时(>{timeout_s:.0f}s):扫描量过大,请加 WHERE 过滤、减少 JOIN 或加 LIMIT 缩小范围"
            ) from e
        raise
    finally:
        conn.set_progress_handler(None, 0)
    truncated = len(fetched) > cap
    rows = [list(r) for r in fetched[:cap]]
    return SqlResult(
        columns=[d[0] for d in cur.description or []],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        executed_sql=executed,
    )
