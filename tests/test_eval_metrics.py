"""评测 2.0 指标单测:分位数、mark 提取、选型准确率与标注完整性(不依赖网络/真实库)。"""

from __future__ import annotations

import pytest

from eval.metrics import (
    CHART_LABEL,
    chart_accuracy,
    chart_mark,
    latency_stats,
    mark_of,
    percentile,
    summarize_run,
)
from eval.questions import CHART_EXPECTATIONS, QUESTIONS
from eval.run_eval import ask_with_retry, chaos_mutator, table_matches, table_matches_semantic


def test_percentile_linear_interpolation():
    vals = [1, 2, 3, 4]
    assert percentile(vals, 50) == 2.5
    assert percentile(vals, 90) == 3.7
    assert percentile(vals, 0) == 1
    assert percentile(vals, 100) == 4


def test_percentile_single_sample_and_bad_args():
    assert percentile([7], 90) == 7
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


def test_latency_stats_p50_p90():
    got = latency_stats([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])
    assert got["n"] == 10
    assert got["p50_ms"] == 550  # k=4.5 → 500 与 600 之间线性插值
    assert got["p90_ms"] == 910  # k=8.1 → 900 + 100×0.1
    assert got["mean_ms"] == 550
    assert (got["min_ms"], got["max_ms"]) == (100, 1000)


def test_chart_mark_tolerates_layer_and_string_marks():
    assert chart_mark({"mark": {"type": "bar"}}) == "bar"
    assert chart_mark({"mark": "line"}) == "line"
    assert chart_mark({"layer": [{"mark": {"type": "arc", "innerRadius": 60}}]}) == "arc"
    assert chart_mark({"layer": [{"mark": "point"}]}) == "point"
    assert chart_mark(None) is None
    assert chart_mark({}) is None


def test_mark_of_normalizes_empty_chart():
    assert mark_of({"chart": ""}) is None
    assert mark_of({"chart": None}) is None
    assert mark_of({}) is None
    assert mark_of({"chart": "bar"}) == "bar"


def _rec(qid: str, chart: str | None, latency_ms: int = 1000) -> dict:
    return {"id": qid, "chart": chart, "latency_ms": latency_ms}


def test_chart_accuracy_counts_extra_chart_as_compliant_extension():
    records = [
        _rec("q06", "line"), _rec("q04", "bar"),
        _rec("q01", None), _rec("q23", "bar"),  # q23:单值题被答成榜单后出图
    ]
    expected = {"q06": "line", "q04": "bar", "q01": None, "q23": None}
    got = chart_accuracy(records, expected)
    assert got["total"] == 4
    assert got["expected_charts"] == 2
    assert got["matched"] == 2
    assert got["accuracy"] == 1.0
    assert got["mismatches"] == []
    assert got["no_chart_expected"] == 2
    assert got["no_chart_ok"] == 1
    assert got["extra_charts"] == ["q23"]  # 合规扩展:不计入选型错误


def test_chart_accuracy_reports_mismatch():
    got = chart_accuracy([_rec("q06", "bar")], {"q06": "line"})
    assert got["matched"] == 0
    assert got["accuracy"] == 0.0
    assert got["mismatches"] == [{"id": "q06", "expected": "line", "actual": "bar"}]


def test_chart_accuracy_fails_loud_on_missing_expectation():
    with pytest.raises(KeyError):
        chart_accuracy([_rec("q99", "bar")], {"q06": "line"})


def test_chart_expectations_cover_question_bank_exactly():
    assert set(CHART_EXPECTATIONS) == {q["id"] for q in QUESTIONS}
    assert all(v is None or v in CHART_LABEL for v in CHART_EXPECTATIONS.values())
    # q20 是别名漂移哨兵:标准答案列名是 SQL 表达式,题目意图仍是季度趋势 → 折线
    assert CHART_EXPECTATIONS["q20"] == "line"


def test_summarize_run_wires_chart_and_latency():
    run = {
        "summary": {"heal": "on", "chaos": False, "date": "2026-01-01 00:00",
                    "accuracy": 0.5, "total": 2},
        "records": [_rec("q06", "line", 1000), _rec("q04", "bar", 3000)],
    }
    got = summarize_run(run)
    assert got["mode"] == "自然/自愈开"
    assert got["chart"]["matched"] == 2
    assert got["latency"] == {
        "n": 2, "mean_ms": 2000, "p50_ms": 2000, "p90_ms": 2800, "min_ms": 1000, "max_ms": 3000,
    }


class _FlakyService:
    def __init__(self, outcomes: list):
        self.outcomes = list(outcomes)
        self.calls = 0

    def ask(self, question: str):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_ask_with_retry_passes_through_on_first_success():
    svc = _FlakyService(["ok"])
    assert ask_with_retry(svc, "q") == "ok"
    assert svc.calls == 1


def test_ask_with_retry_recovers_after_transient_failure():
    svc = _FlakyService([RuntimeError("503"), RuntimeError("503"), "ok"])
    assert ask_with_retry(svc, "q", backoff_s=0) == "ok"
    assert svc.calls == 3


def test_ask_with_retry_raises_after_attempts_exhausted():
    svc = _FlakyService([RuntimeError("503")] * 3)
    with pytest.raises(RuntimeError):
        ask_with_retry(svc, "q", backoff_s=0)
    assert svc.calls == 3


# ---------- 宽松口径(评分器)----------


def test_semantic_accepts_extra_ranking_rows():
    gold = [[1, 0.48], [2, 0.44], [3, 0.40]]
    agent = [[1, 0.48, 99], [2, 0.44, 98], [3, 0.40, 97], [4, 0.39, 96], [5, 0.38, 95]]
    assert table_matches(["a", "b", "c"], agent, gold) is False
    assert table_matches_semantic(["a", "b", "c"], agent, gold) is True


def test_semantic_accepts_month_label_without_year():
    gold = [["2014-01", 100], ["2014-02", 200]]
    agent = [["01", 100], ["02", 200]]
    assert table_matches(["m", "v"], agent, gold) is False
    assert table_matches_semantic(["m", "v"], agent, gold) is True


def test_semantic_accepts_percent_instead_of_ratio():
    gold = [["Africa", 0.23906625]]
    agent = [["Africa", 23.91]]
    assert table_matches(["m", "r"], agent, gold) is False
    assert table_matches_semantic(["m", "r"], agent, gold) is True


def test_semantic_does_not_rescale_counts():
    gold = [["EU", 5]]
    agent = [["EU", 500]]
    assert table_matches_semantic(["m", "v"], agent, gold) is False


# ---------- 故障注入(chaos)----------


def test_chaos_mutator_hits_from_table_not_alias():
    # 裸词匹配会先撞上 `AS orders` 这个别名(它不会被 SQLite 执行),SQL 仍然合法 → 注入空转
    sql = "SELECT COUNT(DISTINCT o.order_id) AS orders, SUM(i.sales) AS sales " \
          "FROM order_items i JOIN orders o ON i.order_id = o.order_id"
    got = chaos_mutator(sql)
    assert "AS orders," in got  # 别名不动
    assert "FROM order_items_typo i" in got


def test_chaos_mutator_leaves_probe_sql_alone():
    sql = "SELECT COUNT(*) FROM sqlite_master"
    assert chaos_mutator(sql) == sql