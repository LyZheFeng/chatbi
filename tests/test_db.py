"""db.py:只读连接、schema 导出、SELECT 护栏。"""

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


def test_run_select_auto_limit(conn):
    r = run_select(conn, "SELECT row_id FROM order_items", auto_limit=5)
    assert r.row_count == 5
    assert "LIMIT 5" in r.executed_sql


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
    ]:
        with pytest.raises(ValueError, match="只读"):
            run_select(conn, bad)


def test_run_select_rejects_multi_statement(conn):
    with pytest.raises(ValueError, match="多条"):
        run_select(conn, "SELECT 1; SELECT 2")


def test_run_select_returns_typed_rows(conn):
    r = run_select(
        conn,
        "SELECT o.order_id, i.sales, i.quantity FROM order_items i "
        "JOIN orders o ON i.order_id = o.order_id WHERE i.sales IS NOT NULL ORDER BY i.row_id LIMIT 3",
    )
    assert r.columns == ["order_id", "sales", "quantity"]
    assert isinstance(r.rows[0][1], float) and isinstance(r.rows[0][2], int)
