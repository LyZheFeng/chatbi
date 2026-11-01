"""评测 2.0 指标:图表选型准确率 + 延迟分布(p50/p90)。纯函数,不碰 LLM/数据库,可单测。

口径(与 README、eval/results.md 同步,报数字前先对口径):
- 期望图型按**题目意图**在 `eval/questions.py` 的 `CHART_EXPECTATIONS` 里逐题标注:
  line / bar / arc / point(`Vega-Lite mark` 名),None = 按契约不该出图(单值、编号列表、
  明细多列、类别 >30);标注只依赖题目与标准答案形状,不看某次跑批的结果。
- 选型准确率 = 应出图题(期望非 None)中,产出 mark 与期望一致的题数 / 应出图题数。
  它抓两类真实漂移:①模型把时间列答成表达式列名,选型退化成散点;②该画没画/画错图型。
- 单值题被模型端出完整榜单(排序题常见)后补出图表:表本身可画,契约允许,记为 extra
  (合规扩展),**不计入选型错误**,单列计数——尺子不把"答得比 gold 更全"判成错。
- 延迟 = 单题端到端 `latency_ms`(含 LLM 多轮与 SQL 执行);p50/p90 用线性插值,
  与 `numpy.percentile` 默认算法一致,不依赖 numpy。

用法:
    python -X utf8 eval/metrics.py eval/runs/heal-on-<时间>.json            # 人读汇总
    python -X utf8 eval/metrics.py eval/runs/heal-on-<时间>.json --markdown # results.md 表格行
    python -X utf8 eval/metrics.py --latest                                  # 最近一次自然跑批
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.questions import CHART_EXPECTATIONS  # noqa: E402

CHART_LABEL = {"line": "折线", "bar": "柱状", "arc": "饼图", "point": "散点"}


# ---------- 图表 mark ----------


def chart_mark(spec: dict | None) -> str | None:
    """取 Vega-Lite spec 的 mark 类型;饼图在 layer[0] 里,故带 layer 回退(与前端同口径)。"""
    if not isinstance(spec, dict):
        return None
    mark = spec.get("mark")
    if isinstance(mark, dict):
        return mark.get("type")
    if isinstance(mark, str):
        return mark
    layer = spec.get("layer")
    if isinstance(layer, list) and layer and isinstance(layer[0], dict):
        m = layer[0].get("mark")
        return m.get("type") if isinstance(m, dict) else m
    return None


def mark_of(record: dict) -> str | None:
    """跑批记录里的 mark;历史记录用空串表示"没出图",统一归一成 None。"""
    return (record.get("chart") or None) or None


def chart_accuracy(records: list[dict], expected: dict[str, str | None] | None = None) -> dict:
    """选型准确率:应出图题按 mark 比对,不出图题按"确实没出图"比对。

    每道跑批记录都必须有期望标注(漏标直接 KeyError,不静默跳过——口径不靠记忆)。
    """
    expected = CHART_EXPECTATIONS if expected is None else expected
    need = [r for r in records if expected[r["id"]]]
    hit = [r for r in need if mark_of(r) == expected[r["id"]]]
    mismatches = [
        {"id": r["id"], "expected": expected[r["id"]], "actual": mark_of(r)}
        for r in need
        if mark_of(r) != expected[r["id"]]
    ]
    none_rows = [r for r in records if not expected[r["id"]]]
    no_chart = [r for r in none_rows if mark_of(r) is None]
    return {
        "total": len(records),
        "expected_charts": len(need),
        "matched": len(hit),
        "accuracy": round(len(hit) / len(need), 4) if need else 0.0,
        "mismatches": mismatches,
        "no_chart_expected": len(none_rows),
        "no_chart_ok": len(no_chart),
        "extra_charts": [r["id"] for r in none_rows if mark_of(r) is not None],
        "by_type": {
            t: {
                "expected": sum(1 for r in need if expected[r["id"]] == t),
                "matched": sum(1 for r in hit if expected[r["id"]] == t),
            }
            for t in CHART_LABEL
        },
    }


# ---------- 延迟分布 ----------


def percentile(values: list[float] | list[int], p: float) -> float:
    """线性插值分位数(0~100),与 numpy.percentile 默认 method='linear' 同法。"""
    if not values:
        raise ValueError("percentile 需要至少一个样本")
    if not 0 <= p <= 100:
        raise ValueError(f"p 必须在 0~100: {p}")
    s = sorted(float(v) for v in values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def latency_stats(latencies: list[int]) -> dict:
    """端到端延迟汇总:p50/p90(主指标)+ 均值/极值(看长尾)。"""
    vals = [int(v) for v in latencies]
    if not vals:
        raise ValueError("latency_stats 需要至少一个样本")
    return {
        "n": len(vals),
        "mean_ms": round(sum(vals) / len(vals)),
        "p50_ms": round(percentile(vals, 50)),
        "p90_ms": round(percentile(vals, 90)),
        "min_ms": min(vals),
        "max_ms": max(vals),
    }


# ---------- 汇总 ----------


def summarize_run(run: dict, source: str = "") -> dict:
    """一份跑批明细 → 指标汇总(选型 + 延迟),不改动输入。

    source 是文件名:评测 2.0 之前的跑批没有 summary.chaos 字段,靠文件名里的 chaos 兜底。
    """
    s = run.get("summary", {})
    records = run["records"]
    chart = chart_accuracy(records, CHART_EXPECTATIONS)
    lat = latency_stats([r["latency_ms"] for r in records])
    chaos = bool(s["chaos"]) if "chaos" in s else ("chaos" in source.lower())
    mode = ("注入⚡" if chaos else "自然") + (
        "/自愈" + ("开" if s.get("heal") == "on" else "关")
    )
    return {
        "date": s.get("date", ""),
        "mode": mode,
        "model": s.get("llm_model", ""),
        "total": len(records),
        "chart": chart,
        "latency": lat,
        "execution_accuracy": s.get("accuracy"),
    }


def _fmt_type(by_type: dict) -> str:
    return "、".join(
        f"{CHART_LABEL[t]} {v['matched']}/{v['expected']}"
        for t, v in by_type.items()
        if v["expected"]
    ) or "无应出图题"


def main() -> int:
    parser = argparse.ArgumentParser(description="评测 2.0:图表选型准确率 + 延迟 p50/p90")
    parser.add_argument("run", nargs="?", help="eval/runs/*.json 路径")
    parser.add_argument("--latest", action="store_true", help="取最近一次自然(非 chaos)跑批")
    parser.add_argument("--markdown", action="store_true", help="输出 results.md 表格行")
    args = parser.parse_args()

    run_path: Path | None = Path(args.run).resolve() if args.run else None
    if run_path is None and args.latest:
        cands = sorted((ROOT / "eval" / "runs").glob("heal-*.json"), key=lambda p: p.name)
        cands = [
            p for p in cands
            if "chaos" not in p.name and json.loads(p.read_text(encoding="utf-8")).get("summary", {}).get("total", 0) >= 50
        ]
        run_path = cands[-1] if cands else None
    if run_path is None:
        parser.error("需要给出跑批 JSON 路径,或加 --latest")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    got = summarize_run(run, source=run_path.name)
    c, lat = got["chart"], got["latency"]

    if args.markdown:
        print(
            f"| {got['date']} | {got['mode']} | {got['model'] or '—'} | "
            f"{c['matched']}/{c['expected_charts']} | {c['accuracy']:.1%} | "
            f"{c['no_chart_ok']}/{c['no_chart_expected']} | "
            f"{'、'.join(c['extra_charts']) or '无'} | {lat['p50_ms']} | {lat['p90_ms']} |"
        )
        return 0

    shown = run_path.relative_to(ROOT) if run_path.is_relative_to(ROOT) else run_path
    print(f"跑批:{shown}")
    print(f"时间/模式/模型:{got['date']} | {got['mode']} | {got['model'] or '(未记录)'}")
    print(f"执行准确率(原指标):{got['execution_accuracy']:.1%}" if got["execution_accuracy"] is not None else "")
    print(
        f"图表选型:{c['matched']}/{c['expected_charts']} = {c['accuracy']:.1%} "
        f"({_fmt_type(c['by_type'])})"
    )
    if c["mismatches"]:
        for m in c["mismatches"]:
            print(f"  ✗ {m['id']}: 期望 {m['expected']},实得 {m['actual']}")
    print(f"不出图契约:{c['no_chart_ok']}/{c['no_chart_expected']} 未出图")
    if c["extra_charts"]:
        print(f"榜单扩展出图(合规,不计错):{'、'.join(c['extra_charts'])}")
    print(
        f"延迟(ms):p50={lat['p50_ms']} p90={lat['p90_ms']} 均值={lat['mean_ms']} "
        f"最小={lat['min_ms']} 最大={lat['max_ms']} n={lat['n']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())