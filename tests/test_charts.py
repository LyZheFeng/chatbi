"""charts.py:选型确定性、spec 形状、解读数字锚定、脏数据剔除约定、service 集成。"""

from __future__ import annotations

import json

from app.charts import build_chart


def _bar_table():
    return ["market", "total"], [["EU", 1815], ["AP", 905], ["US", 300]]


# ---------- 柱状 / 横条 / 饼图 ----------


def test_bar_vertical_by_default():
    spec, reading = build_chart("各市场销售额", *_bar_table())
    assert spec["mark"] == {"type": "bar"}
    assert spec["encoding"]["x"]["field"] == "market"
    assert spec["encoding"]["x"]["sort"] is None
    # 数据预排序:从大到小
    assert [r["market"] for r in spec["data"]["values"]] == ["EU", "AP", "US"]
    assert "最高是 EU(1,815)" in reading and "最低 US(300)" in reading


def test_hbar_when_long_labels():
    cols = ["product_name", "sales"]
    rows = [["这是一个很长的商品名称甲", 100], ["这是一个很长的商品名称乙", 300], ["这是一个很长的商品名称丙", 200]]
    spec, _ = build_chart("销售额最高的商品", cols, rows)
    # 标签 >8 字 → 横条:维度在 y 轴,且最大值排最上(数据升序)
    assert spec["encoding"]["y"]["field"] == "product_name"
    assert spec["encoding"]["x"]["type"] == "quantitative"
    vals = [r["sales"] for r in spec["data"]["values"]]
    assert vals == sorted(vals) and vals[-1] == 300


def test_pie_when_question_asks_share():
    spec, reading = build_chart("各市场销售额占比", *_bar_table())
    assert spec["mark"]["type"] == "arc"
    assert spec["encoding"]["theta"]["field"] == "total"
    assert "占比最大" in reading and "60.1%" in reading  # 1815/3020


def test_no_pie_without_share_keyword():
    spec, _ = build_chart("各市场销售额对比", *_bar_table())
    assert spec["mark"] == {"type": "bar"}


def test_pie_falls_back_to_bar_when_negative():
    cols = ["market", "total"]
    rows = [["EU", 1815], ["AP", 905], ["US", -300]]
    spec, reading = build_chart("各市场销售额占比", cols, rows)
    assert spec["mark"] == {"type": "bar"}
    assert "1 项为负值" in reading


def test_two_measure_bar_uses_fold():
    cols = ["category", "sales", "profit"]
    rows = [["Fur", 1000, -50], ["Tec", 900, 120], ["Off", 800, 60]]
    spec, reading = build_chart("各大类销售额和利润对比", cols, rows)
    assert spec["mark"] == {"type": "bar"}
    assert spec["transform"][0]["fold"] == ["sales", "profit"]
    assert spec["encoding"]["color"]["field"] == "指标"
    assert spec["encoding"]["xOffset"]["field"] == "指标"
    assert "按 profit 计,最高是 Tec(120)" in reading


def test_extra_ratio_column_does_not_kill_bar():
    # 真实链路常见形态:模型多算一列利润率/占比(第 3 个数值列),柱状图取前两个数值列
    cols = ["category", "total_sales", "total_profit", "profit_margin_pct"]
    rows = [["Technology", 756983.02, 145068.68, 19.16],
            ["Furniture", 598238.22, 82188.95, 13.74],
            ["Office Supplies", 352496.14, 61662.81, 17.49]]
    spec, reading = build_chart("各大类销售额和利润对比", cols, rows)
    assert spec is not None and spec["mark"] == {"type": "bar"}
    assert spec["transform"][0]["fold"] == ["total_sales", "total_profit"]


def test_pie_ignores_extra_pct_column():
    # 问占比时模型常附带 pct 列;饼图只画第一个数值列,share 按图内合计重算
    cols = ["market", "sales", "pct"]
    rows = [["Asia Pacific", 797866.37, 46.72], ["Europe", 503568.21, 29.49],
            ["LATAM", 231207.8, 13.54], ["Africa", 115205.93, 6.75], ["USCA", 55422.09, 3.25]]
    spec, reading = build_chart("各市场销售额占比", cols, rows)
    assert spec["mark"]["type"] == "arc"
    assert spec["encoding"]["theta"]["field"] == "sales"
    assert "图内合计" in reading and "占比最大" in reading


# ---------- 折线 ----------


def test_line_monthly_sorted_and_reading():
    cols = ["月份", "销售额"]
    rows = [["2014-03", 300], ["2014-01", 100], ["2014-02", 200]]
    spec, reading = build_chart("2014 年按月销售额趋势", cols, rows)
    assert spec["mark"] == {"type": "line", "point": True}
    assert spec["encoding"]["x"]["field"] == "月份"
    assert [r["月份"] for r in spec["data"]["values"]] == ["2014-01", "2014-02", "2014-03"]
    assert "共 3 期(2014-01~2014-03)" in reading
    assert "整体上升 200.0%" in reading
    assert "峰值在第 2014-03 期(300)" in reading


def test_line_two_measures_fold():
    cols = ["月份", "sales", "profit"]
    rows = [["2014-01", 100, 10], ["2014-02", 200, -5], ["2014-03", 150, 30]]
    spec, _ = build_chart("按月销售额与利润趋势", cols, rows)
    assert spec["transform"][0]["fold"] == ["sales", "profit"]
    assert spec["encoding"]["y"]["field"] == "值"
    assert spec["encoding"]["color"]["field"] == "指标"


def test_multiline_with_group():
    cols = ["月份", "market", "sales"]
    rows = [
        ["2014-01", "EU", 100], ["2014-02", "EU", 120],
        ["2014-01", "AP", 60], ["2014-02", "AP", 90],
    ]
    spec, reading = build_chart("各市场按月销售额趋势", cols, rows)
    assert spec["encoding"]["color"]["field"] == "market"
    assert "按 sales 合计" in reading
    assert "累计最高的是 EU(220)" in reading  # EU 220 > AP 150


def test_year_quarter_columns_merged():
    cols = ["year", "quarter", "total"]
    rows = [[2014, 1, 100], [2013, 4, 90], [2014, 3, 120], [2014, 2, 150]]
    spec, reading = build_chart("按年季度销售额趋势", cols, rows)
    assert spec["mark"]["type"] == "line"
    labels = [r["year×quarter"] for r in spec["data"]["values"]]
    assert labels == ["2013Q4", "2014Q1", "2014Q2", "2014Q3"]  # 时间排序,不是字典序
    assert "共 4 期(2013Q4~2014Q3)" in reading


def test_quarter_only_column_is_period():
    cols = ["quarter", "total"]
    rows = [[2, 20], [1, 10], [4, 25], [3, 15]]
    spec, _ = build_chart("按季度销售额", cols, rows)
    assert spec["mark"]["type"] == "line"
    assert [r["quarter"] for r in spec["data"]["values"]] == ["1", "2", "3", "4"]


# ---------- 散点 / 不画图 ----------


def test_scatter_two_numeric():
    cols = ["discount", "profit"]
    rows = [[0.1, 50], [0.2, -10], [0.3, 80], [0.0, 20]]
    spec, reading = build_chart("折扣和利润的关系", cols, rows)
    assert spec["mark"]["type"] == "point"
    assert spec["encoding"]["x"]["field"] == "discount"
    assert "4 个点" in reading and "r=" in reading


def test_id_like_numeric_column_is_dimension_not_measure():
    cols = ["order_no", "amount"]
    rows = [[1, 10], [2, 30], [3, 20]]
    spec, _ = build_chart("订单金额", cols, rows)
    assert spec["mark"] == {"type": "bar"}  # 编号列当维度,不进散点


def test_no_chart_cases():
    assert build_chart("总数", ["n"], [[5], [6]]) == (None, "")            # 列数不足
    assert build_chart("总量", ["k", "v"], [[1, 2]]) == (None, "")          # 行数不足
    assert build_chart("各市场各大类", ["market", "category", "sales"],
                       [["EU", "T", 1], ["AP", "F", 2]]) == (None, "")      # 两个维度列
    assert build_chart("三列数值", ["a", "b", "c"],
                       [[1, 2, 3], [4, 5, 6]]) == (None, "")                # 三个数值列
    assert build_chart("重名列", ["market", "market"],
                       [["EU", 1], ["AP", 2]]) == (None, "")                # 列名重复


# ---------- 脏数据约定 ----------


def test_null_rows_excluded_from_chart_but_noted():
    cols = ["market", "total"]
    rows = [["EU", 100], [None, 50], ["AP", None], ["US", 80]]
    spec, reading = build_chart("各市场销售额", cols, rows)
    assert len(spec["data"]["values"]) == 2  # 维度缺失、数值缺失各剔除 1 行
    assert "另有 2 行因字段缺失未画入,表格中仍可见" in reading


def test_negative_values_kept_and_called_out():
    cols = ["market", "profit"]
    rows = [["EU", -100], ["AP", 50], ["US", 80]]
    spec, reading = build_chart("各市场利润", cols, rows)
    assert len(spec["data"]["values"]) == 3  # 负值照画,不剔除
    assert "1 项为负值" in reading


def test_spec_is_json_serializable():
    spec, _ = build_chart("各市场销售额占比", *_bar_table())
    json.dumps(spec, ensure_ascii=False)  # API/前端可直接序列化


def test_spec_pins_readable_text_colors():
    """UI 修复回归:深色主题下 Streamlit vega 主题会把文字刷浅叠白底,spec 必须自带深色文字。"""
    spec, _ = build_chart("各市场销售额", *_bar_table())
    cfg = spec["config"]
    assert cfg["background"] == "white"
    assert cfg["title"]["color"] == cfg["axis"]["labelColor"] == cfg["legend"]["labelColor"] == "#262730"


# ---------- service 集成 ----------


def test_service_attaches_chart_and_reading(conn):
    from tests.test_agent import FakeLLM, _msg, _tc

    from app.agent import ChatbiAgent
    from app.service import ChatbiService

    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT market, SUM(sales) AS total FROM order_items i "
                                      "JOIN orders o ON i.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id "
                                      "JOIN geography g ON c.country=g.country AND c.region=g.region GROUP BY market")]),
        _msg([_tc("final_answer", summary="Europe 市场销售额居首。")]),
    ])
    svc = ChatbiService(lambda: ChatbiAgent(llm, conn, cap=50, auto_limit=10))
    resp = svc.ask("各市场销售额")
    assert resp.error is None
    assert resp.chart_spec is not None and resp.chart_spec["mark"]["type"] == "bar"
    assert "Europe" in resp.chart_reading


def test_no_chart_on_degraded_answer(conn):
    from tests.test_agent import FakeLLM, _msg, _tc

    from app.agent import ChatbiAgent
    from app.service import ChatbiService

    llm = FakeLLM([_msg([_tc("execute_sql", sql="SELECT nope FROM order_items")])])
    svc = ChatbiService(lambda: ChatbiAgent(llm, conn, cap=50, auto_limit=10, self_heal=False))
    resp = svc.ask("随便问")
    assert resp.error is not None
    assert resp.chart_spec is None and resp.chart_reading == ""


def test_service_closes_connection_after_ask(conn):
    """评审 P0-2:每请求一个连接,ask 返回后必须已关闭,长期运行不积累句柄。"""
    import pytest as _pytest

    from tests.test_agent import FakeLLM, _msg, _tc

    from app.agent import ChatbiAgent
    from app.service import ChatbiService

    llm = FakeLLM([
        _msg([_tc("execute_sql", sql="SELECT COUNT(*) AS n FROM orders")]),
        _msg([_tc("final_answer", summary="订单共 7 张。")]),
    ])
    holder = {}
    svc = ChatbiService(lambda: holder.setdefault("agent", ChatbiAgent(llm, conn, cap=50, auto_limit=10)) or holder["agent"])
    svc.ask("多少张订单")
    with _pytest.raises(Exception):
        holder["agent"].conn.execute("SELECT 1")  # 已关闭的连接不能再执行
