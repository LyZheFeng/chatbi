"""Streamlit 界面:中文提问 → 图表 + 解读 + 表格 + SQL/轨迹。

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
    "各市场销售额占比",
    "哪些明细的数量为负或为 0?",
]

_CHART_LABEL = {"bar": "柱状图", "hbar": "条形图", "line": "折线图", "arc": "饼图", "point": "散点图"}

# 卡片化消息 + 胶囊按钮 + hero 横幅;颜色用半透明叠加,深浅主题都成立
_CSS = """
<style>
.hero{background:linear-gradient(120deg,#0f2b46 0%,#1d4e89 55%,#2a9d8f 135%);
 border-radius:14px;padding:22px 26px;margin-bottom:4px;color:#fff}
.hero-title{font-size:26px;font-weight:700;letter-spacing:.5px}
.hero-sub{opacity:.92;margin-top:6px;font-size:14.5px}
.hero-facts{opacity:.72;margin-top:10px;font-size:12.5px}
[data-testid="stChatMessage"]{border:1px solid rgba(128,128,128,.28);border-radius:14px;
 padding:12px 16px !important;background:rgba(128,128,128,.05)}
.stButton>button{border-radius:999px;font-size:12.5px;padding:2px 14px}
[data-testid="stExpander"]{border-radius:12px}
.badges span{opacity:.78;font-size:12.5px;margin-right:14px}
</style>
"""


def _fmt_num(v) -> str:
    if isinstance(v, float) and v != int(v):
        return f"{v:,.2f}"
    return f"{int(v):,}"


@st.cache_data(ttl=600, show_spinner=False)
def _table_counts(db_path: str) -> dict[str, int] | None:
    try:
        from app.db import TABLES, connect_ro

        conn = connect_ro(db_path)
        try:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        finally:
            conn.close()
    except Exception:
        return None


def _badges(resp: AskResponse) -> None:
    tok = resp.stats.get("llm_tokens", 0)
    fail = resp.stats.get("sql_failures", 0)
    refl = resp.stats.get("reflections", 0)
    parts = [f"⏱ {resp.latency_ms:,} ms", f"🪜 {len(resp.steps)} 步"]
    if fail:
        parts.append(f"🔁 SQL 重试 {fail}")
    if refl:
        parts.append(f"🤔 反思 {refl}")
    if tok:
        parts.append(f"🧮 {tok:,} tokens")
    st.markdown('<div class="badges">' + "".join(f"<span>{p}</span>" for p in parts) + "</div>",
                unsafe_allow_html=True)


def _render(resp: AskResponse) -> None:
    if resp.error:
        st.error(f"未能完成分析:{resp.error}")
    if resp.summary:
        st.success(resp.summary)

    single = (
        resp.row_count == 1 and len(resp.columns) == 1
        and isinstance(resp.rows[0][0], (int, float))
    )
    if single:
        col, _ = st.columns([1, 2])
        col.metric(resp.columns[0], _fmt_num(resp.rows[0][0]))
        _badges(resp)
    if resp.row_count and not single:
        if resp.chart_spec:
            label = _CHART_LABEL.get(resp.chart_spec["mark"]["type"], "图表")
            st.caption(f"📈 自动选型:**{label}**")
            # theme=None:关闭 Streamlit 的 vega 主题接管(深色模式下它会把文字刷成浅色,
            # 叠在 spec 自带的白底上看不清);spec 内已显式钉死深色文字,双保险
            st.vega_lite_chart(resp.chart_spec, use_container_width=True, theme=None)
        if resp.chart_reading:
            with st.container(border=True):
                st.markdown(f"**📖 怎么读这张图**:{resp.chart_reading}")
        st.dataframe(pd.DataFrame(resp.rows, columns=resp.columns),
                     use_container_width=True, hide_index=True)
        st.caption(f"{resp.row_count} 行")
        _badges(resp)
    elif not single:
        _badges(resp)
    with st.expander("🔍 SQL 与执行轨迹"):
        if resp.sql:
            st.code(resp.sql, language="sql")
        for s in resp.steps:
            icon = "✅" if s.ok else "❌"
            st.markdown(f"{icon} **步骤{s.step} · `{s.tool}`** `{s.args}`")
            st.caption(s.detail)


def _handle(question: str) -> None:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("agent 执行中:get_schema → execute_sql → final_answer …"):
            resp = get_service().ask(question)
        _render(resp)
    st.session_state.history.append(resp)


def _sidebar() -> None:
    from app.config import get_settings

    with st.sidebar:
        st.markdown("### 🗄️ 数据概况")
        counts = _table_counts(get_settings().db_path)
        if counts:
            for t, n in counts.items():
                st.caption(f"· `{t}` **{n:,}** 行")
        else:
            st.caption("5 张关联表(geography / customers / products / orders / order_items)")
        st.caption(f"模型:{get_settings().llm_model} · temperature=0")

        st.divider()
        st.markdown("### 📊 本次会话")
        h = st.session_state.history
        if h:
            avg = sum(r.latency_ms for r in h) / len(h)
            tok = sum(r.stats.get("llm_tokens", 0) for r in h)
            c1, c2 = st.columns(2)
            c1.metric("提问", len(h))
            c2.metric("平均延迟", f"{avg / 1000:.1f}s")
            st.caption(f"累计 {tok:,} tokens")
        else:
            st.caption("还没有提问,从上面的示例开始 👆")

        st.divider()
        if st.button("🧹 清空对话", use_container_width=True):
            st.session_state.history = []
            st.rerun()
        st.caption("只读连接 · SQL 护栏 · 超时 5s · 自愈重试上限 3")


st.set_page_config(page_title="ChatBI · 电商订单分析", page_icon="📊", layout="wide")
st.markdown(_CSS, unsafe_allow_html=True)
st.markdown(
    """<div class="hero">
  <div class="hero-title">📊 ChatBI · 电商订单分析</div>
  <div class="hero-sub">中文提问 → 生成 SQL → 自愈执行 → 图表 + 解读 + 结论,数字全部来自本地执行</div>
  <div class="hero-facts">Global Superstore · 5 张关联表 · 2012–2015 · 注入 5 类确定性脏数据</div>
</div>""",
    unsafe_allow_html=True,
)

if "history" not in st.session_state:
    st.session_state.history: list[AskResponse] = []

_sidebar()

with st.container(border=True):
    st.markdown("**💡 试试这些问题**(点击直接提问)")
    cols = st.columns(len(EXAMPLES))
    for i, (col, q) in enumerate(zip(cols, EXAMPLES)):
        if col.button(q if len(q) <= 14 else q[:13] + "…", key=f"example-{i}", use_container_width=True):
            st.session_state.pending = q

for resp in st.session_state.history:
    with st.chat_message("user"):
        st.write(resp.question)
    with st.chat_message("assistant"):
        _render(resp)

pending_question = st.session_state.pop("pending", None)
if pending_question:
    _handle(pending_question)

question = st.chat_input("用中文问一个数据问题,回车发送")
if question:
    _handle(question)
