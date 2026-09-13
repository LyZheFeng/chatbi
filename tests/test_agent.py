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


# ---------- Day 17-18:自愈循环 ----------


def test_consecutive_sql_failures_hit_cap_and_degrade(conn):
    llm = FakeLLM([_msg([_tc("execute_sql", sql="SELECT nope FROM order_items")])] * 10)
    r = _agent(conn, llm).run("连续打错")
    assert r.error and "连续 3 次执行失败" in r.error and "no such column" in r.error
    assert len([s for s in r.steps if s.tool == "execute_sql"]) == 3  # 上限即停,不烧满 8 步
    assert r.stats == {"sql_attempts": 3, "sql_failures": 3, "reflections": 0}


def test_failure_streak_resets_after_success(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT bad FROM order_items")]),
        _msg([_tc("execute_sql", sql="SELECT bad2 FROM order_items")]),
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM order_items")]),
        _msg([_tc("execute_sql", sql="SELECT bad3 FROM order_items")]),
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM orders")]),
        _msg([_tc("final_answer", summary="订单数拿到了。")]),
    ])
    r = _agent(conn, llm).run("错两次对一次错一次再对")
    assert r.error is None
    assert r.stats["sql_attempts"] == 5 and r.stats["sql_failures"] == 3
    assert r.sql.startswith("SELECT COUNT(*) AS n FROM orders")


def test_error_hint_appended_for_bad_column(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT revenue FROM order_items")]),
        _msg([_tc("final_answer", summary="算了。")]),
    ])
    _agent(conn, llm).run("列名打错")
    fed = llm.seen[1][-1]["content"]
    assert fed.startswith("ERROR") and "列名不存在" in fed


def test_empty_result_triggers_reflection_hint(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM order_items WHERE quantity > 100")]),
        _msg([_tc("final_answer", summary="数量都 <=100,查不到更大的。")]),
    ])
    r = _agent(conn, llm).run("有没有数量大于 100 的明细")
    assert r.stats["reflections"] == 1
    fed = llm.seen[1][-1]["content"]
    assert "反思提示" in fed and "枚举值" in fed
    assert r.result.rows[0][0] == 0  # 空聚合结果照常返回给前端


def test_all_zero_single_column_triggers_reflection(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT SUM(sales) AS s FROM order_items WHERE row_id = -1")]),
        _msg([_tc("final_answer", summary="没有这一行。")]),
    ])
    r = _agent(conn, llm).run("不存在的行求和")
    assert r.stats["reflections"] == 1


def test_normal_result_no_reflection(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM order_items")]),
        _msg([_tc("final_answer", summary="1000 行。")]),
    ])
    r = _agent(conn, llm).run("多少行")
    assert r.stats["reflections"] == 0


def test_self_heal_off_degrades_on_first_error(conn):
    llm = FakeLLM([
        _msg([_tc("get_schema")]),
        _msg([_tc("execute_sql", sql="SELECT bad FROM order_items")]),
        _msg([_tc("final_answer", summary="不会到这里。")]),
    ])
    agent = ChatbiAgent(llm, conn, self_heal=False, cap=50, auto_limit=10)
    r = agent.run("关自愈")
    assert r.error and "自愈已关闭" in r.error and "no such column" in r.error
    assert [s.tool for s in r.steps] == ["get_schema", "execute_sql"]  # 不给重试机会
    assert r.summary == ""  # 没有编造


def test_self_heal_off_no_reflection_on_empty(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM order_items WHERE quantity > 100")]),
        _msg([_tc("final_answer", summary="无。")]),
    ])
    agent = ChatbiAgent(llm, conn, self_heal=False, cap=50, auto_limit=10)
    r = agent.run("关自愈空结果")
    assert r.stats["reflections"] == 0
    assert "反思提示" not in llm.seen[1][-1]["content"]


def test_self_heal_off_success_path_unaffected(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM customers")]),
        _msg([_tc("final_answer", summary="800 个客户。")]),
    ])
    agent = ChatbiAgent(llm, conn, self_heal=False, cap=50, auto_limit=10)
    r = agent.run("多少客户")
    assert r.error is None and r.summary == "800 个客户。"


def test_final_answer_sql_reexecuted_for_display_consistency(conn):
    # 模型探查枚举后又直接作答(没重跑计数)——展示表格必须来自自报 SQL,不是探查结果
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT DISTINCT market FROM geography")]),
        _msg([_tc("final_answer", summary="数量为 0。",
                  sql="SELECT COUNT(*) FROM order_items WHERE quantity > 100")]),
    ])
    r = _agent(conn, llm).run("探查后作答")
    assert r.result.columns == ["COUNT(*)"]
    assert r.result.rows == [[0]]
    assert "quantity > 100" in r.sql


def test_final_answer_bad_sql_keeps_last_result(conn):
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM customers")]),
        _msg([_tc("final_answer", summary="4 个客户。", sql="SELECT FROM WHERE")]),
    ])
    r = _agent(conn, llm).run("自报坏 SQL")
    assert r.result.rows == [[4]]  # 保留最近一次成功结果
    assert r.sql == "SELECT FROM WHERE"  # 展示仍是模型自报的
    assert r.error is None


def test_sql_mutator_breaks_only_first_attempt(conn):
    """故障注入:第一次 execute_sql 被改坏表名,模型重试后恢复。"""
    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM customers")]),  # 会被改成 customers_typo
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM customers")]),  # 第二次不再改
        _msg([_tc("final_answer", summary="4 个客户。")]),
    ])
    import re

    table_re = re.compile(r"\b(customers|orders|order_items|products|geography)\b")
    agent = ChatbiAgent(
        llm, conn, cap=50, auto_limit=10,
        sql_mutator=lambda sql: table_re.sub(lambda m: m.group(1) + "_typo", sql, count=1),
    )
    r = agent.run("多少客户")
    assert r.error is None and r.result.rows == [[4]]
    assert [s.ok for s in r.steps] == [False, True, True]
    assert r.stats["sql_failures"] == 1  # 只坏第一次
