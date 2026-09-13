"""tools.py:参数严格校验 + 三工具执行。"""

import pytest

from app.tools import ToolError, dispatch


def test_get_schema_happy(conn):
    text, result = dispatch(conn, "get_schema", "{}")
    assert "CREATE TABLE" in text and result is None
    assert "客户编号" in text


def test_execute_sql_happy(conn):
    text, result = dispatch(conn, "execute_sql", '{"sql": "SELECT COUNT(*) AS n FROM order_items"}')
    assert "n" in text and result.row_count == 1 and result.rows[0][0] == 12


def test_final_answer_only_validates(conn):
    text, result = dispatch(conn, "final_answer", '{"summary": "共 12 行明细"}')
    assert text == "OK" and result is None


def test_bad_json_arguments(conn):
    with pytest.raises(ToolError, match="JSON"):
        dispatch(conn, "execute_sql", "{not json")


def test_missing_required_field(conn):
    with pytest.raises(ToolError, match="参数校验失败"):
        dispatch(conn, "execute_sql", "{}")


def test_sql_error_wrapped_as_toolerror(conn):
    with pytest.raises(ToolError, match="no such table"):
        dispatch(conn, "execute_sql", '{"sql": "SELECT * FROM nope"}')


def test_unknown_tool(conn):
    with pytest.raises(ToolError, match="未知工具"):
        dispatch(conn, "drop_everything", "{}")


def test_final_answer_requires_summary(conn):
    with pytest.raises(ToolError, match="参数校验失败"):
        dispatch(conn, "final_answer", '{"sql": "SELECT 1"}')
