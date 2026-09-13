"""db.py:只读连接、schema 导出、SELECT 护栏、原子建库。"""

import sqlite3

import pytest

from app.db import connect_ro, run_select, schema_text


def test_connect_ro_rejects_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        connect_ro(tmp_path / "nope.db")


def test_readonly_connection_is_physically_readonly(conn):
    with pytest.raises(Exception):
        conn.execute("CREATE TABLE hack(x)")


def test_schema_text_contains_comments_and_counts(conn):
    text = schema_text(conn)
    assert "CREATE TABLE order_items" in text
    assert "客户编号" in text  # 中文列注释随 DDL 保留
    assert "约 12 行" in text  # 行数注释
    only_two = schema_text(conn, ["orders", "order_items", "not_a_table"])
    assert "CREATE TABLE orders" in only_two and "未知表" in only_two


def test_schema_text_contains_er_diagram(conn):
    text = schema_text(conn, ["orders"])  # 只取子集时关系图仍然返回
    assert "表关系" in text and "geography" in text


def test_ddl_comments_match_actual_data(conn):
    """Day 19 回归:DDL 注释里的枚举值由建库脚本从数据动态生成,必须与库中取值一致。

    Day 17-18 踩过坑:注释手写 'APAC / EU',库里实际是 'Asia Pacific / Europe',
    模型照注释写过滤条件查空,白白消耗探查步数。
    """
    text = schema_text(conn)
    for col_sql, hint in [
        ("SELECT DISTINCT market FROM geography", "市场枚举"),
        ("SELECT DISTINCT segment FROM customers", "客户类型枚举"),
        ("SELECT DISTINCT category FROM products", "商品大类枚举"),
        ("SELECT DISTINCT ship_mode FROM orders", "配送方式枚举"),
    ]:
        for (value,) in conn.execute(col_sql):
            assert value in text, f"{hint} 注释缺少实际取值 {value!r}"


def test_run_select_auto_limit(conn):
    r = run_select(conn, "SELECT row_id FROM order_items", auto_limit=5)
    assert r.row_count == 5
    assert "LIMIT 5" in r.executed_sql


def test_auto_limit_not_fooled_by_string_or_comment(conn):
    """评审 P0-3:字符串/注释里出现 'limit' 不构成真 LIMIT 子句,不能绕过自动行数上限。"""
    r = run_select(conn, "SELECT 'limit' AS s", auto_limit=100)
    assert "LIMIT 100" in r.executed_sql
    r = run_select(conn, "SELECT 1 AS v -- limit", auto_limit=100)
    assert "LIMIT 100" in r.executed_sql
    r = run_select(conn, 'SELECT "limit" AS v FROM orders LIMIT 3', auto_limit=100)
    assert r.row_count == 3 and "LIMIT 100" not in r.executed_sql  # 引号标识符同理,真 LIMIT 仍生效


def test_build_replaces_atomically_with_backup(db_path, tmp_path):
    """评审 P1-8:重建走 .tmp 原子替换,旧库自动备份 .bak,正式库始终完整可用。"""
    from scripts.build_db import build
    from tests.conftest import MINI_CSV

    csv = tmp_path / "mini.csv"
    csv.write_text(MINI_CSV, encoding="utf-8")
    target = tmp_path / "x.db"

    first = build(csv, target)
    assert target.exists() and not (tmp_path / "x.db.bak").exists()

    second = build(csv, target)
    assert target.exists() and (tmp_path / "x.db.bak").exists()
    assert first["tables"] == second["tables"]  # 确定性注入,重建同结果
    bak = sqlite3.connect(f"file:{tmp_path / 'x.db.bak'}?mode=ro", uri=True)
    try:
        assert bak.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] > 0
    finally:
        bak.close()


def test_run_select_respects_written_limit(conn):
    r = run_select(conn, "SELECT row_id FROM order_items LIMIT 2", auto_limit=5)
    assert r.row_count == 2 and "LIMIT 5" not in r.executed_sql


def test_run_select_cap_truncates(conn):
    r = run_select(conn, "SELECT row_id FROM order_items LIMIT 20", cap=10)
    assert r.row_count == 10 and r.truncated


def test_run_select_rejects_non_select(conn):
    for bad in [
        "UPDATE order_items SET sales = 0",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "INSERT INTO orders VALUES (1)",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE 'x.db' AS x",
        "EXPLAIN SELECT 1",
        "VACUUM",
    ]:
        with pytest.raises(ValueError, match="只读|仅允许"):
            run_select(conn, bad)


def test_run_select_rejects_multi_statement(conn):
    with pytest.raises(ValueError, match="多条"):
        run_select(conn, "SELECT 1; SELECT 2")


def test_token_guard_blocks_dangerous_functions(conn):
    for bad in [
        "SELECT load_extension('evil.dll')",
        "SELECT randomblob(1024)",
        "SELECT * FROM pragma_table_info('orders')",  # 表值 PRAGMA 函数探测库结构
        "WITH x AS (SELECT 1) DELETE FROM orders",     # WITH 开头也拦得住后面的写语句
    ]:
        with pytest.raises(ValueError, match="护栏|多条|仅允许"):
            run_select(conn, bad)


def test_token_guard_allows_benign_forms(conn):
    """注释/字符串里的关键字是惰性文本,CASE...END 是合法表达式,不得误杀。"""
    r = run_select(conn, "SELECT row_id, -- 注释里的 DELETE FROM orders 无害\nrow_id FROM order_items LIMIT 1")
    assert r.row_count == 1
    assert run_select(conn, "/* 头部注释 */ SELECT 1 AS v").rows == [[1]]
    assert run_select(conn, "SELECT 'DROP TABLE orders' AS s").row_count == 1
    r = run_select(
        conn,
        "SELECT CASE WHEN quantity > 0 THEN '正常' ELSE '异常' END AS flag "
        "FROM order_items WHERE quantity <= 0 LIMIT 3",
    )
    assert r.rows and r.rows[0][0] == "异常"
    # 结尾分号+尾注释:剥掉后正常执行
    assert run_select(conn, "SELECT 2 AS v; -- done").rows == [[2]]


def test_run_select_timeout_interrupts_unbounded_query(conn):
    """无界 RECURSIVE CTE 是只读连接挡不住的算力攻击,必须被超时掐断。"""
    import time as _time

    t0 = _time.monotonic()
    with pytest.raises(ValueError, match="超时"):
        run_select(
            conn,
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c",
            timeout_s=0.3,
        )
    assert _time.monotonic() - t0 < 3  # 0.3s 期限 + 回调粒度,远早于 3s


def test_run_select_returns_typed_rows(conn):
    r = run_select(
        conn,
        "SELECT o.order_id, i.sales, i.quantity FROM order_items i "
        "JOIN orders o ON i.order_id = o.order_id WHERE i.sales IS NOT NULL ORDER BY i.row_id LIMIT 3",
    )
    assert r.columns == ["order_id", "sales", "quantity"]
    assert isinstance(r.rows[0][1], float) and isinstance(r.rows[0][2], int)
