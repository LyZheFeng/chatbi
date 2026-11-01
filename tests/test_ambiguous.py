"""歧义/无法回答题判定规则单测(纯规则,不调 LLM)。"""

from __future__ import annotations

from eval.ambiguous import QUESTIONS, judge


def test_question_bank_shape():
    assert len(QUESTIONS) == 10
    ids = [q["id"] for q in QUESTIONS]
    assert len(set(ids)) == 10
    kinds = [q["kind"] for q in QUESTIONS]
    assert kinds.count("unanswerable") == 5 and kinds.count("ambiguous") == 5


def test_unanswerable_passes_on_graceful_degrade():
    ok, reason = judge("unanswerable", "SQL 执行失败:no such column: return_rate", "…", 0)
    assert ok and "优雅降级" in reason


def test_unanswerable_passes_when_missing_data_explained():
    ok, reason = judge("unanswerable", None, "库里没有退货字段/退货表,无法计算退货率。", 0)
    assert ok and "说明缺失" in reason


def test_unanswerable_passes_when_assumption_stated():
    ok, _ = judge("unanswerable", None, "数据中没有退货金额,假设用负利润近似退货口径,结果如下。", 3)
    assert ok


def test_unanswerable_fails_on_silent_table():
    ok, reason = judge("unanswerable", None, "各市场销售额如下。", 5)
    assert not ok and "静默" in reason


def test_ambiguous_passes_when_clarifying():
    ok, reason = judge("ambiguous", None, "您指的是哪一年?全期还是某一年?请补充。", 1)
    assert ok and "澄清" in reason


def test_ambiguous_passes_when_assumption_stated():
    ok, _ = judge("ambiguous", None, "按 2012–2015 全期销售额口径,最高的是 Asia Pacific。", 5)
    assert ok


def test_ambiguous_passes_when_metric_and_scope_named():
    # 不反问但把"用了哪个指标、什么范围"写清楚,也算透明(本轮实跑 b01/b03/b05 的形态)
    ok, reason = judge("ambiguous", None, "2014 年销售额 45.54 万,比 2013 年增长 29.2%。", 2)
    assert ok and "写明指标/范围" in reason


def test_ambiguous_passes_without_result_table():
    ok, _ = judge("ambiguous", None, "这个问题需要先明确指标。", 0)
    assert ok


def test_ambiguous_fails_on_bare_answer():
    ok, reason = judge("ambiguous", None, "Asia Pacific。", 5)
    assert not ok and "静默" in reason