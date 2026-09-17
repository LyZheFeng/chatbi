"""固定 5 题冒烟评测(评测守护):演示前、对外报任何评估数字前必跑。

题型覆盖:计数 / 聚合 / 占比 / 时间序列 / 脏数据点名。
断言(每题共有):agent 无 error、SQL 已实际执行(row_count >= 1)、结论非空;
  - 计数题:单值 == 1000(与 build_db 固定数据集绑定,1000 行明细)
  - 聚合/占比/时间序列:图表产出且 mark 类型符合预期(bar / arc / line)
  - 脏数据点名:行号集合 == {58, 62, 220}(build_db 确定性注入的 quantity<=0 行)
输出:一页漂移报告(与 eval/smoke_baseline.json 快照对比哪题变了),跑完写入新快照。
口径:结果以「当次跑批」为准,带日期记 PROGRESS(与 rag-qa scripts/smoke_eval.py 同一口径)。

用法:.venv/Scripts/python.exe -X utf8 scripts/smoke_eval.py
依赖:data/chatbi.db + 内网 vLLM(agent 走真实 function-calling 循环)。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

BASELINE = ROOT / "eval" / "smoke_baseline.json"

# chart 期望值 = Vega-Lite spec 的 mark 类型(与前端 ChartCard 的 CHART_LABEL 同口径);
# None 表示该题型按契约就不出图(如单值计数 len(rows)<2、单列脏数据点名)。
QUESTIONS: list[dict] = [
    dict(qid="s1-count", cat="计数", question="订单明细一共有多少行?", scalar=1000, chart=None),
    dict(qid="s2-agg", cat="聚合", question="三个商品大类各自的销售额和总利润是多少?", chart="bar"),
    dict(qid="s3-share", cat="占比", question="各市场销售额占比?", chart="arc"),
    dict(qid="s4-ts", cat="时间序列", question="亚太市场按月的销售额趋势是怎样的?", chart="line"),
    dict(qid="s5-dirty", cat="脏数据点名", question="数量小于等于 0 的异常明细有哪些行号?",
         rowset={58, 62, 220}, chart=None),
]


def chart_mark(spec: dict | None) -> str | None:
    """取 spec 的 mark 类型,容忍 layer 包装(与前端 chartTypeLabel 同样的回退)。"""
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


def _num(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def check(q: dict, resp) -> list[str]:
    fails: list[str] = []
    if resp.error:
        fails.append(f"error={resp.error}")
    if not resp.sql:
        fails.append("无SQL")
    if resp.row_count < 1:
        fails.append("row_count=0(表格为空)")
    if not resp.summary.strip():
        fails.append("空结论")
    if "scalar" in q and not fails:
        got = _num(resp.rows[0][0]) if resp.rows else None
        if got != q["scalar"]:
            fails.append(f"计数值 {got} != {q['scalar']}")
    if q.get("chart") and not fails:
        mark = chart_mark(resp.chart_spec)
        if resp.chart_spec is None:
            fails.append("缺图表")
        elif mark != q["chart"]:
            fails.append(f"mark={mark} != {q['chart']}")
    if "rowset" in q and not fails:
        got = {_num(row[0]) for row in resp.rows} - {None}
        if got != set(q["rowset"]):
            fails.append(f"行号集 {sorted(got)} != {sorted(q['rowset'])}")
    return fails


def _prev_snapshot() -> dict | None:
    if not BASELINE.exists():
        return None
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    from app.config import get_settings
    from app.service import get_service

    settings = get_settings()
    t0 = time.time()
    svc = get_service()
    load_s = time.time() - t0

    results = []
    for q in QUESTIONS:
        resp = svc.ask(q["question"])
        fails = check(q, resp)
        results.append(dict(
            qid=q["qid"], cat=q["cat"], question=q["question"], ok=not fails, failed=fails,
            mark=chart_mark(resp.chart_spec), row_count=resp.row_count,
            latency_ms=resp.latency_ms, n_steps=len(resp.steps),
            stats=resp.stats, summary_head=resp.summary[:60],
        ))
        mark = "PASS" if not fails else "FAIL"
        print(f"[{mark:>4}] {q['qid']:<9} {q['cat']:<6} {resp.latency_ms}ms "
              f"步骤={len(resp.steps)} 图={chart_mark(resp.chart_spec) or '无'} 行数={resp.row_count}")
        for f in fails:
            print(f"       ✗ {f}")

    prev = _prev_snapshot()
    prev_by = {r["qid"]: r for r in prev["results"]} if prev else {}
    drift = []
    for r in results:
        p = prev_by.get(r["qid"])
        if p is None:
            continue
        diffs = []
        for field in ("ok", "mark", "row_count"):
            if r[field] != p[field]:
                diffs.append(f"{field}: {p[field]!r}→{r[field]!r}")
        if diffs:
            drift.append((r["qid"], "; ".join(diffs)))

    BASELINE.parent.mkdir(exist_ok=True)
    BASELINE.write_text(json.dumps(dict(
        date=time.strftime("%Y-%m-%d %H:%M"), llm_model=settings.llm_model,
        db_path=str(settings.db_path), results=results,
    ), ensure_ascii=False, indent=1), encoding="utf-8")

    hard = [r for r in results if not r["ok"]]
    print("\n" + "=" * 78)
    print(f"chatbi 冒烟评测 · 漂移报告  {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"agent {settings.llm_model}(内网 vLLM)| 库 {Path(settings.db_path).name} | 服务加载 {load_s:.1f}s")
    print(f"基线快照: {prev['date'] if prev else '无(本次为首跑,跑完即建基线)'}")
    print("-" * 78)
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"{mark:<4} {r['qid']:<9} {r['cat']:<6} 图={r['mark'] or '无':<5} 行数={r['row_count']:<4} "
              f"自愈(尝试/失败/反思)={r['stats'].get('sql_attempts', 0)}/"
              f"{r['stats'].get('sql_failures', 0)}/{r['stats'].get('reflections', 0)}")
        print(f"     结论:{r['summary_head']}")
        if r["failed"]:
            print(f"     失败项:{'; '.join(r['failed'])}")
    print("-" * 78)
    if drift:
        print("漂移(与上次快照比):")
        for qid, d in drift:
            print(f"  {qid:<9} {d}")
    else:
        print("漂移:无(全部题与上次快照同表现)")
    n_ok = sum(r["ok"] for r in results)
    print(f"汇总:{n_ok}/{len(results)} 通过 | 快照已写入 {BASELINE.relative_to(ROOT)}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
