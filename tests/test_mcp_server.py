"""mcp_server.py:走真实 stdio 子进程的协议级测试。

用官方 SDK 的 in-process ClientSession 启动 `python -m app.mcp_server`
(与 MCP Inspector 相同的入口),覆盖:
- 三类原语的发现与调用(tools / resources+templates / prompts);
- 护栏错误以 isError 结果完整回传(自愈信号不丢);
- 50 题 gold SQL「经 MCP 通道 vs 本地直连」结果一致(交接单点名的验证资产)。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REAL_DB = ROOT / "data" / "chatbi.db"


def run_over_stdio(scenario, db_path: str | None = None):
    """起一个真实 server 子进程跑完 scenario(coroutine)后关闭,返回其结果。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(ROOT),
        env={"DB_PATH": str(db_path)} if db_path else None,  # 叠加在安全默认环境之上
    )

    async def main():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await scenario(session)

    return asyncio.run(main())


def _parse_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """把 _format_result 的文本(首行'共 N 行'+列名行+数据行)解析回列与行。"""
    lines = text.splitlines()
    columns = lines[1].split("|")
    rows = [line.split("|") for line in lines[2:]]
    return columns, rows


def test_protocol_surface():
    """tools/resources/templates/prompts 都可发现,内容与 db.py 同源。"""

    async def scenario(s):
        tools = {t.name for t in (await s.list_tools()).tools}
        assert tools == {"get_schema", "execute_sql"}

        schema_text = (await s.call_tool("get_schema", {})).content[0].text
        assert "表关系" in schema_text and "CREATE TABLE geography" in schema_text
        only = (await s.call_tool("get_schema", {"tables": ["orders", "not_a_table"]})).content[0].text
        assert "CREATE TABLE orders" in only and "未知表" in only

        uris = {str(r.uri) for r in (await s.list_resources()).resources}
        assert "chatbi://schema" in uris
        templates = {t.uri_template for t in (await s.list_resource_templates()).resource_templates}
        assert "chatbi://tables/{table}" in templates

        full = (await s.read_resource("chatbi://schema")).contents[0].text
        assert full.startswith("-- 表关系")
        one = (await s.read_resource("chatbi://tables/orders")).contents[0].text
        assert "CREATE TABLE orders" in one and "表关系" in one  # 子集也带关系图(Day 19 约定)
        unknown = (await s.read_resource("chatbi://tables/nope")).contents[0].text
        assert "未知表" in unknown

        prompts = {p.name for p in (await s.list_prompts()).prompts}
        assert prompts == {"analyze_data"}
        rendered = (await s.get_prompt("analyze_data", {"question": "各市场的总利润?"})).messages[0].content.text
        assert "各市场的总利润" in rendered and "中位数" in rendered and "Asia Pacific" in rendered

    run_over_stdio(scenario, db_path=str(REAL_DB) if REAL_DB.exists() else None)


@pytest.mark.skipif(not REAL_DB.exists(), reason="需要真实 data/chatbi.db(离线 mini 库不含 gold 数据)")
def test_execute_sql_and_guardrail_over_stdio():
    """查询经 MCP 返回真实数据;护栏拒绝以 isError + 完整消息回传。"""

    async def scenario(s):
        ok = await s.call_tool("execute_sql", {"sql": "SELECT COUNT(*) FROM order_items"})
        assert not ok.is_error
        assert ok.content[0].text == "共 1 行\nCOUNT(*)\n1000"

        for bad_sql in ("DELETE FROM orders", "SELECT 1; DROP TABLE orders", "PRAGMA database_list"):
            res = await s.call_tool("execute_sql", {"sql": bad_sql})
            assert res.is_error, bad_sql
            msg = res.content[0].text
            assert "仅允许 SELECT" in msg or "只读护栏" in msg or "多条" in msg, msg

        # 常见 SQL 错误(表名写错)也要带原始报错回传——自愈循环的输入
        res = await s.call_tool("execute_sql", {"sql": "SELECT * FROM nope"})
        assert res.is_error and "no such table" in res.content[0].text

    run_over_stdio(scenario)


@pytest.mark.skipif(not REAL_DB.exists(), reason="需要真实 data/chatbi.db(gold SQL 针对真实数据)")
def test_gold_sql_parity_mcp_vs_local():
    """50 题 gold SQL:经 MCP execute_sql 与本地 db.run_select 逐题结果一致。"""
    from app.db import connect_ro, run_select
    from eval.questions import QUESTIONS

    async def scenario(s):
        conn = connect_ro(REAL_DB)
        try:
            for q in QUESTIONS:
                res = await s.call_tool("execute_sql", {"sql": q["gold"]})
                assert not res.is_error, (q["id"], res.content[0].text)
                columns, rows = _parse_rows(res.content[0].text)
                direct = run_select(conn, q["gold"])
                assert columns == direct.columns, q["id"]
                assert rows == [[("" if v is None else str(v)) for v in r] for r in direct.rows], q["id"]
        finally:
            conn.close()

    run_over_stdio(scenario)
