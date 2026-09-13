"""Streamlit 界面:中文提问 → 结论 + 表格 + SQL/轨迹(排查用)。

运行:streamlit run app/ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import AskResponse  # noqa: E402
from app.service import get_service  # noqa: E402

EXAMPLES = [
    "2014 年销售额最高的 5 个国家是哪些?",
    "各大类(Furniture/Office Supplies/Technology)的销售额和利润对比",
    "亚太市场按月销售额趋势",
    "哪些客户购买了 3 次以上?列出姓名和消费总额",
    "折扣超过 0.3 的订单明细,利润怎么样?",
]


def _render(resp: AskResponse) -> None:
    if resp.error:
        st.error(f"未能完成分析:{resp.error}")
    if resp.summary:
        st.success(resp.summary)
    if resp.row_count:
        if resp.chart_spec:
            # theme=None:关闭 Streamlit 的 vega 主题接管(深色模式下它会把文字刷成浅色,
            # 叠在 spec 自带的白底上看不清);spec 内已显式钉死深色文字,双保险
            st.vega_lite_chart(resp.chart_spec, use_container_width=True, theme=None)
        if resp.chart_reading:
            st.info(f"📈 **怎么读这张图**:{resp.chart_reading}")
        st.dataframe(pd.DataFrame(resp.rows, columns=resp.columns), use_container_width=True)
        st.caption(f"{resp.row_count} 行 · {resp.latency_ms} ms")
    with st.expander("SQL 与执行轨迹"):
        if resp.sql:
            st.code(resp.sql, language="sql")
        for s in resp.steps:
            icon = "✅" if s.ok else "❌"
            st.markdown(f"{icon} **步骤{s.step} · {s.tool}** `{s.args}`")
            st.caption(s.detail)


st.set_page_config(page_title="ChatBI · 电商订单分析", page_icon="📊", layout="wide")
st.title("ChatBI · 电商订单分析")
st.caption("中文提问 → 生成 SQL → 执行 → 图表 + 表格 + 结论(Global Superstore,2012-2015)")
st.markdown("**示例问题:** " + " · ".join(f"`{e}`" for e in EXAMPLES))

if "history" not in st.session_state:
    st.session_state.history: list[AskResponse] = []

for resp in st.session_state.history:
    with st.chat_message("user"):
        st.write(resp.question)
    with st.chat_message("assistant"):
        _render(resp)

question = st.chat_input("用中文问一个数据问题,回车发送")
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("agent 执行中:get_schema → execute_sql → final_answer …"):
            resp = get_service().ask(question)
        _render(resp)
    st.session_state.history.append(resp)
