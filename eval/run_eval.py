"""评估入口:问题集 × 自愈开关 → 执行准确率,结果追加进 eval/results.md。

用法:
    .venv/Scripts/python.exe -X utf8 eval/run_eval.py --heal off   # 自愈关
    .venv/Scripts/python.exe -X utf8 eval/run_eval.py --heal on    # 自愈开
    加 --chaos 注入故障(每题首条 SQL 强制改错表名),量恢复能力。

规则(数字必须全量真实跑出,温度 0):
- 执行准确率 = agent 最终表格与 gold 表格"值集合"一致(浮点圆整 2 位、行序无关、列子集投影、
  单行 gold 答案点包含);gold SQL 不圆整,容差只在判定器一处
- 模型降级/报错/未产出表格 → 不匹配
- 出图率 = chart_spec 非空的比例(呈现层参考指标,不进执行准确率口径)
- 明细 JSON 落 eval/runs/,汇总表追加 eval/results.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.questions import QUESTIONS  # noqa: E402


def normalize(rows: list[list]) -> list[tuple]:
    """值集合归一:浮点圆整 2 位(金额口径),None→'NULL',行排序(与行序无关比较)。"""

    def cell(v):
        if v is None:
            return "NULL"
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, int):
            return v
        return str(v)

    return sorted(tuple(cell(v) for v in row) for row in rows)


def table_matches(agent_columns: list[str], agent_rows: list[list], gold_rows: list[list]) -> bool:
    """答案包含判定:gold 的答案在 agent 表中出现即算对。

    - 多行 gold(列表题):值集合完全一致(行序无关);
    - 单行 gold(最值/单一数字题):该答案行作为"答案点"在返回表中出现即可
      (模型常把完整排名端出来,第一行就是答案);
    - 允许模型比 gold 多带上下文列:取 agent 的列子集投影比对。
    """
    if not agent_columns or not gold_rows:
        return False
    gold_width = len(gold_rows[0])
    gold_set = normalize(gold_rows)
    if len(agent_columns) == gold_width and normalize(agent_rows) == gold_set:
        return True
    if len(agent_columns) > gold_width:
        from itertools import combinations

        for combo in combinations(range(len(agent_columns)), gold_width):
            projected = normalize([[row[i] for i in combo] for row in agent_rows])
            if len(gold_rows) == 1:
                if gold_set[0] in projected:
                    return True
            elif projected == gold_set:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heal", choices=["on", "off"], required=True)
    parser.add_argument("--chaos", action="store_true",
                        help="故障注入:每题第一次 execute_sql 的表名被强制改错,量恢复能力(非自然准确率)")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题(调试用)")
    parser.add_argument("--only", type=str, default="", help="只跑指定 id(逗号分隔,调试用)")
    args = parser.parse_args()

    import re

    from app import db
    from app.agent import ChatbiAgent
    from app.config import Settings
    from app.db import connect_ro
    from app.llm import LLM
    from app.service import ChatbiService

    settings = Settings(self_heal=args.heal == "on")
    mutator = None
    if args.chaos:
        table_re = re.compile(r"\b(order_items|orders|customers|products|geography)\b")

        def mutator(sql: str) -> str:  # noqa: F811
            return table_re.sub(lambda m: m.group(1) + "_typo", sql, count=1)

    service = ChatbiService(lambda: ChatbiAgent(
        LLM.from_settings(), connect_ro(settings.db_path),
        max_steps=settings.max_tool_steps, cap=settings.sql_row_cap,
        auto_limit=settings.auto_limit, self_heal=settings.self_heal,
        max_sql_retries=settings.max_sql_retries, sql_mutator=mutator,
    ))
    gold_conn = connect_ro(settings.db_path)

    questions = QUESTIONS
    if args.limit:
        questions = questions[: args.limit]
    if args.only:
        wanted = {q.strip() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    records, matched, healed_and_matched, degraded = [], 0, 0, 0
    charted = 0
    latencies: list[int] = []
    for q in questions:
        gold = db.run_select(gold_conn, q["gold"], cap=100_000, auto_limit=100_000)
        t0 = time.perf_counter()
        resp = service.ask(q["question"])
        ok = (
            resp.error is None
            and table_matches(resp.columns, resp.rows, gold.rows)
        )
        chart_type = resp.chart_spec["mark"]["type"] if resp.chart_spec else ""
        if chart_type:
            charted += 1
        if ok:
            matched += 1
        if resp.error:
            degraded += 1
        if resp.stats.get("sql_failures", 0) > 0 and ok:
            healed_and_matched += 1
        latencies.append(resp.latency_ms)
        records.append(dict(
            id=q["id"], tags=q["tags"], question=q["question"], match=ok,
            chart=chart_type, error=resp.error, stats=resp.stats, latency_ms=resp.latency_ms,
            steps=[s.tool for s in resp.steps], sql=resp.sql,
            columns=resp.columns, rows=resp.rows[:20],
            gold_rows=gold.rows[:20],
        ))
        flag = "✓" if ok else "✗"
        print(f"{flag} {q['id']} [{q['tags']}] {resp.latency_ms}ms chart={chart_type or '-'} "
              f"attempts={resp.stats.get('sql_attempts', 0)} "
              f"fail={resp.stats.get('sql_failures', 0)} refl={resp.stats.get('reflections', 0)}"
              + (f" ERROR={resp.error[:60]}" if resp.error else ""), flush=True)

    total = len(questions)
    acc = matched / total if total else 0
    summary = dict(
        heal=args.heal, date=datetime.now().strftime("%Y-%m-%d %H:%M"), total=total,
        matched=matched, accuracy=round(acc, 4), degraded=degraded,
        healed_and_matched=healed_and_matched, charted=charted,
        avg_latency_ms=sum(latencies) // max(len(latencies), 1),
    )

    runs_dir = ROOT / "eval" / "runs"
    runs_dir.mkdir(exist_ok=True)
    tag = f"heal-{args.heal}" + ("-chaos" if args.chaos else "")
    detail = runs_dir / f"{tag}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    detail.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")

    mode = ("注入⚡" if args.chaos else "自然") + ("/自愈" + ("开" if args.heal == "on" else "关"))
    print(f"\n=== {mode} === 准确率 {matched}/{total} = {acc:.1%},降级 {degraded},"
          f"出错后自愈成功 {healed_and_matched},出图 {charted}/{total},平均延迟 {summary['avg_latency_ms']}ms")
    print(f"明细:{detail}")

    results = ROOT / "eval" / "results.md"
    with results.open("a", encoding="utf-8") as f:
        f.write(
            f"| {summary['date']} | {mode} | {matched}/{total} "
            f"| {acc:.1%} | {degraded} | {healed_and_matched} | {charted}/{total} | {summary['avg_latency_ms']} |\n"
        )


if __name__ == "__main__":
    main()
