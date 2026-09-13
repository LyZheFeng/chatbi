"""agent.py 循环逻辑(FakeLLM 脚本化驱动,不打网络)。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agent import ChatbiAgent


def _tc(name: str, **args):
    return SimpleNamespace(id=f"call_{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _msg(tool_calls=None, content=""):
    return SimpleNamespace(tool_calls=tool_calls, content=content)


class FakeLLM:
    """按脚本依次吐消息;同时记录收到的 messages 供断言。"""

    def __init__(self, script: list):
        self.script = list(script)
        self.seen: list[list] = []

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        return self.script.pop(0)


def _agent(conn, llm, max_steps=8):
    return ChatbiAgent(llm, conn, max_steps=max_steps, cap=50, auto_limit=10)


def test_happy_path(conn):
    llm = FakeLLM([
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql="SELECT market, SUM(sales) AS total FROM order_items i JOIN orders o ON i.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id JOIN geography g ON c.country=g.country AND c.region=g.region GROUP BY market")]),
        _msg([_tc("final_answer", summary="EU 市场销售额约 1815 美元,居首(USCA 因脏数据关联缺失未计入)。", sql="SELECT market, SUM(sales) FROM ... GROUP BY market")]),
    ])
    r = _agent(conn, llm).run("各市场总销售额")
    assert r.error is None
    assert r.summary.startswith("EU")
    assert r.sql == "SELECT market, SUM(sales) FROM ... GROUP BY market"  # final_answer 自报优先
    # mini 库的脏数据注入把 2 个美国客户 region 置空 → USCA 在 geography join 中丢失,
    # 只剩 APAC/EU —— 表格始终来自本地执行,模型嘴说的数字进不了 rows
    assert r.result.row_count == 2
    assert [row[0] for row in r.result.rows] == ["APAC", "EU"]
    assert r.result.columns == ["market", "total"]
    assert [s.ok for s in r.steps] == [True, True, True]
    # 前两轮的工具结果都以 role=tool 回传了(final_answer 自己的结果在循环结束后才入列)
    def _role(m):
        return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
    tool_msgs = [m for m in llm.seen[-1] if _role(m) == "tool"]
    assert len(tool_msgs) == 2


def test_sql_error_feeds_back_and_model_recovers(conn):
    llm = FakeLLM([
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql="SELECT bad_col FROM order_items")]),
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM order_items")]),
        _msg([_tc("final_answer", summary="明细共 12 行。")]),
    ])
    r = _agent(conn, llm).run("多少行明细")
    assert r.error is None and r.summary == "明细共 12 行。"
    assert [s.ok for s in r.steps] == [True, False, True, True]
    # 报错文本原样回传给了模型(自愈入口)
    err_tool_msg = llm.seen[2][-1]
    assert err_tool_msg["content"].startswith("ERROR")


def test_final_answer_uses_last_executed_sql_when_sql_omitted(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM orders")]),
        _msg([_tc("final_answer", summary="订单共 7 张。")]),
    ])
    r = _agent(conn, llm).run("多少张订单")
    assert r.sql.startswith("SELECT COUNT(*) AS n FROM orders")  # 未自报时用最近执行 SQL(含自动补的 LIMIT)


def test_rows_come_from_local_execution_not_llm(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM customers")]),
        _msg([_tc("final_answer", summary="客户共 999 个。")]),  # 模型虚报,表格必须以本地执行为准
    ])
    r = _agent(conn, llm).run("多少客户")
    assert r.summary == "客户共 999 个。"  # summary 尊重模型原话
    assert r.result.rows[0][0] == 4  # mini 库实际 4 个客户


def test_step_budget_exhaustion_degrades_gracefully(conn):
    llm = FakeLLM([_msg([_tc("execute_sql", sql="SELECT 1")])] * 10)
    r = _agent(conn, llm, max_steps=3).run("故意耗尽步数")
    assert r.error and "上限" in r.error
    assert len(r.steps) == 3
    assert r.summary == ""  # 没编造


def test_model_talks_without_tools_nudge_then_stop(conn):
    llm = FakeLLM([_msg(content="我认为是 42 个。"), _msg(content="还是 42 个。")])
    r = _agent(conn, llm).run("多少客户")
    assert r.error and "final_answer" in r.error
    assert r.summary == ""


def test_nudge_recovers(conn):
    llm = FakeLLM([
        _msg(content=""),  # 空内容不调工具 → 提醒
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM products")]),
        _msg([_tc("final_answer", summary="商品 6 个。")]),
    ])
    r = _agent(conn, llm).run("多少商品")
    assert r.error is None and r.result.rows[0][0] == 12  # mini 库 12 个商品


def test_parallel_tool_calls_in_one_message(conn):
    llm = FakeLLM([
        _msg([
            _tc("get_schema"),
            _tc("execute_sql", sql="SELECT COUNT(*) AS n FROM geography"),
        ]),
        _msg([_tc("final_answer", summary="两条查询都成功了。")]),
    ])
    r = _agent(conn, llm).run("看看库")
    assert [s.tool for s in r.steps] == ["get_schema", "execute_sql", "final_answer"]
    assert all(s.ok for s in r.steps)
