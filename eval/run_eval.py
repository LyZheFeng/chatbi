"""评估入口:问题集 × 自愈开关 → 执行准确率,结果追加进 eval/results.md。

用法:
    .venv/Scripts/python.exe -X utf8 eval/run_eval.py --heal off   # 自愈关
    .venv/Scripts/python.exe -X utf8 eval/run_eval.py --heal on    # 自愈开
    加 --chaos 注入故障(每题首条 SQL 强制改错表名),量恢复能力。

规则(数字必须全量真实跑出,温度 0):
- 执行准确率 = agent 最终表格与 gold 表格"值集合"一致(浮点圆整 2 位、行序无关、列子集投影、
  单行 gold 答案点包含);gold SQL 不圆整,容差只在判定器一处
- 宽松口径(并列报告,不改历史严格口径):多返回行、比率↔百分比、月份标签带不带年份 视为等价,
  另存 semantic_matched/semantic_accuracy;严格口径仍是唯一进 results.md 汇总行的指标
- 模型降级/报错/未产出表格 → 不匹配
- 出图率 = chart_spec 非空的比例(呈现层参考指标,不进执行准确率口径)
- 故障注入(--chaos)只改坏**第一次真正查表**的 execute_sql,探测/元数据 SQL 原样放过;
  命中次数记 stats.injection_hits,summary 汇总为 injection_hits(命中率决定该实验是否有效)
- 评测 2.0 指标(与执行准确率分开报):图表选型准确率(应出图题 mark 是否与
  questions.CHART_EXPECTATIONS 一致)+ 延迟 p50/p90,口径见 eval/metrics.py
- 解读忠实性(评测 2.0 第 2 项):chart_reading 里出现的每个数字都必须能追溯到最终结果表,
  由 eval/fidelity.py 规则校验(模板生成,不新增 LLM 调用);0 违规是期望值
- 明细 JSON 落 eval/runs/,汇总表追加 eval/results.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.fidelity import check_reading  # noqa: E402
from eval.metrics import chart_accuracy, chart_mark, latency_stats  # noqa: E402
from eval.questions import CHART_EXPECTATIONS, QUESTIONS  # noqa: E402


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
        for combo in combinations(range(len(agent_columns)), gold_width):
            projected = normalize([[row[i] for i in combo] for row in agent_rows])
            if len(gold_rows) == 1:
                if gold_set[0] in projected:
                    return True
            elif projected == gold_set:
                return True
    return False


_MONTH_LABEL = re.compile(r"^\d{4}-(\d{2})(?:-\d{2})?$")
_BARE_MONTH = re.compile(r"^\d{2}$")

# 注入只改 FROM/JOIN 后面的业务表:裸词匹配会先撞上别名/列名
# (如 `COUNT(...) AS orders`),SQL 仍然合法,注入等于空转
_TABLE_REF = re.compile(r"\b(FROM|JOIN)\s+(order_items|orders|customers|products|geography)\b", re.I)


def chaos_mutator(sql: str) -> str:
    """故障注入:把第一条 FROM/JOIN 的业务表改成不存在的表;别名/字符串里的同名不动。"""
    return _TABLE_REF.sub(lambda m: f"{m.group(1)} {m.group(2)}_typo", sql, count=1)


def _cell_matches(gold, agent) -> bool:
    """语义口径的单元格等价:数值允许比率↔百分比,字符串允许月份标签带不带年份。"""
    if gold is None or agent is None:
        return gold is None and agent is None
    g_num = isinstance(gold, (int, float)) and not isinstance(gold, bool)
    a_num = isinstance(agent, (int, float)) and not isinstance(agent, bool)
    if g_num and a_num:
        g, a = float(gold), float(agent)
        if round(g, 2) == round(a, 2):
            return True
        # 比率 ↔ 百分比(q47/q23:模型给 ×100 的百分数,gold 是 0~1 的比率)。
        # 只在小数量级一侧换算,避免把"计数 5 vs 500"这类当单位差异放过
        if abs(g) < 1.5 or abs(a) < 1.5:
            return round(g * 100, 2) == round(a, 2) or round(g, 2) == round(a / 100, 2)
        return False
    gs, as_ = str(gold), str(agent)
    gm, am = _MONTH_LABEL.match(gs), _MONTH_LABEL.match(as_)
    if gm and am:
        return gm.group(1) == am.group(1)
    # 一侧是 2014-01、另一侧只有 01(单年内按月的问法)
    if gm and _BARE_MONTH.match(as_):
        return gm.group(1) == as_
    if am and _BARE_MONTH.match(gs):
        return am.group(1) == gs
    return gs == as_


def _contains_rows(gold_rows: list[list], agent_rows: list[list]) -> bool:
    """gold 每行都能在 agent 里找到唯一等价行(语义口径允许模型多返回行)。"""
    pool = list(agent_rows)
    for g in gold_rows:
        for i, a in enumerate(pool):
            if len(g) == len(a) and all(_cell_matches(gc, ac) for gc, ac in zip(g, a)):
                pool.pop(i)
                break
        else:
            return False
    return True


def table_matches_semantic(agent_columns: list[str], agent_rows: list[list], gold_rows: list[list]) -> bool:
    """**宽松口径**(只用于并列报告,不改历史严格口径 `table_matches`)。

    放开的只有三类"内容对、写法不同":排名题多返回行、比率↔百分比、月份标签带不带年份;
    列子集投影与数值圆整沿用严格口径。
    """
    if not agent_columns or not gold_rows:
        return False
    width = len(gold_rows[0])
    if len(agent_columns) < width:
        return False
    for combo in combinations(range(len(agent_columns)), width):
        projected = [[row[i] for i in combo] for row in agent_rows]
        if _contains_rows(gold_rows, projected):
            return True
    return False


def classify_misses(records: list[dict]) -> tuple[list[str], list[str]]:
    """严格失配拆两类:content = 宽松口径也救不回的内容缺失;shape = 写法差异(多返回行/百分比/标签)。"""
    content = [r["id"] for r in records if not r["match"] and not r.get("semantic_match")]
    shape = [r["id"] for r in records if not r["match"] and r.get("semantic_match")]
    return content, shape


def ask_with_retry(service, question: str, *, attempts: int = 3, backoff_s: float = 600.0):
    """整题重跑:LLM 侧 503/网络抖动不该把整轮跑批作废(2026-11-01 实跑撞上过)。

    只重试**抛异常**的情况(服务故障);agent 内部优雅降级(error 字段)是模型行为,不重试。
    2026-11-02 用户规则:模型无响应(LLM 异常/超时/503)时**等 10 分钟**再试,**最多 3 次**;
    3 次仍失败则抛出,由驱动脚本 `scripts/run_rounds.py` 停止整批,把原因交回用户。
    每次重试前固定等 600s(10 分钟),给上游容量恢复留时间。
    """
    for i in range(attempts):
        try:
            return service.ask(question)
        except Exception as exc:  # noqa: BLE001 - 评测脚本:LLM/网络任何异常都值得整题重试
            if i == attempts - 1:
                raise
            wait = backoff_s * (i + 1)
            print(f"    ! 调用异常({type(exc).__name__}),{wait:.0f}s 后整题重试:{question[:16]}…",
                  flush=True)
            time.sleep(wait)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heal", choices=["on", "off"], required=True)
    parser.add_argument("--chaos", action="store_true",
                        help="故障注入:每题第一次 execute_sql 的表名被强制改错,量恢复能力(非自然准确率)")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题(调试用)")
    parser.add_argument("--only", type=str, default="", help="只跑指定 id(逗号分隔,调试用)")
    parser.add_argument("--no-results-md", action="store_true",
                        help="不往 eval/results.md 追加汇总行(补题/冒烟等小跑批用)")
    args = parser.parse_args()

    import re

    from app import db
    from app.agent import ChatbiAgent
    from app.config import Settings
    from app.db import connect_ro
    from app.llm import LLM
    from app.service import ChatbiService

    settings = Settings(self_heal=args.heal == "on")
    mutator = chaos_mutator if args.chaos else None

    service = ChatbiService(lambda: ChatbiAgent(
        LLM.from_settings(), connect_ro(settings.db_path),
        max_steps=settings.max_tool_steps, cap=settings.sql_row_cap,
        auto_limit=settings.auto_limit, self_heal=settings.self_heal,
        max_sql_retries=settings.max_sql_retries, sql_mutator=mutator,
    ))
    gold_conn = connect_ro(settings.db_path)
    # A1:schema 缓存计数(取增量 = 本轮真实命中率,跨轮/跨进程不串味)
    cache_before = db.schema_cache_info()

    questions = QUESTIONS
    if args.limit:
        questions = questions[: args.limit]
    if args.only:
        wanted = {q.strip() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    if not questions:
        print("没有匹配到题目(--limit/--only 过滤后为空),不跑批")
        return

    records, matched, healed_and_matched, degraded = [], 0, 0, 0
    semantic_matched = 0
    charted = 0
    fidelity_checked, fidelity_ok, fidelity_bad = 0, 0, []
    latencies: list[int] = []
    for q in questions:
        gold = db.run_select(gold_conn, q["gold"], cap=100_000, auto_limit=100_000)
        t0 = time.perf_counter()
        resp = ask_with_retry(service, q["question"])
        ok = (
            resp.error is None
            and table_matches(resp.columns, resp.rows, gold.rows)
        )
        # 宽松口径与严格口径并列记录(只用于报告);严格口径的结果不因此改变
        semantic_ok = resp.error is None and (
            ok or table_matches_semantic(resp.columns, resp.rows, gold.rows)
        )
        chart_type = chart_mark(resp.chart_spec) or ""
        chart_reading = resp.chart_reading or ""
        bad_numbers: list[float] = []
        if chart_type:
            charted += 1
            fidelity_checked += 1
            bad_numbers = check_reading(chart_reading, resp.columns, resp.rows, chart_type)
            if bad_numbers:
                fidelity_bad.append({"id": q["id"], "numbers": bad_numbers, "reading": chart_reading[:200]})
            else:
                fidelity_ok += 1
        if ok:
            matched += 1
        if semantic_ok:
            semantic_matched += 1
        if resp.error:
            degraded += 1
        if resp.stats.get("sql_failures", 0) > 0 and ok:
            healed_and_matched += 1
        latencies.append(resp.latency_ms)
        records.append(dict(
            id=q["id"], tags=q["tags"], question=q["question"], match=ok,
            semantic_match=semantic_ok,
            chart=chart_type, chart_reading=chart_reading, fidelity_violations=bad_numbers,
            error=resp.error, stats=resp.stats, latency_ms=resp.latency_ms,
            steps=[s.tool for s in resp.steps], sql=resp.sql,
            columns=resp.columns, rows=resp.rows[:20],
            gold_rows=gold.rows[:20],
        ))
        flag = "✓" if ok else ("≈" if semantic_ok else "✗")
        print(f"{flag} {q['id']} [{q['tags']}] {resp.latency_ms}ms chart={chart_type or '-'} "
              f"attempts={resp.stats.get('sql_attempts', 0)} "
              f"fail={resp.stats.get('sql_failures', 0)} refl={resp.stats.get('reflections', 0)}"
              + (f" ERROR={resp.error[:60]}" if resp.error else ""), flush=True)

    cache_after = db.schema_cache_info()
    schema_cache_hits = cache_after["hits"] - cache_before["hits"]
    schema_cache_misses = cache_after["misses"] - cache_before["misses"]

    total = len(questions)
    acc = matched / total if total else 0
    semantic_acc = semantic_matched / total if total else 0
    injection_hits = sum((r["stats"] or {}).get("injection_hits", 0) for r in records)
    injection_valid = (injection_hits == total) if args.chaos else None
    # 严格失配拆两类:内容缺失(宽松口径也救不回,必须为零) vs 形状差异(多返回行/百分比/标签)
    content_misses, shape_misses = classify_misses(records)
    chart = chart_accuracy(records, CHART_EXPECTATIONS)
    lat = latency_stats(latencies)
    summary = dict(
        heal=args.heal, chaos=args.chaos, llm_model=settings.llm_model,
        date=datetime.now().strftime("%Y-%m-%d %H:%M"), total=total,
        matched=matched, accuracy=round(acc, 4),
        semantic_matched=semantic_matched, semantic_accuracy=round(semantic_acc, 4),
        injection_hits=injection_hits, injection_valid=injection_valid,
        content_misses=content_misses, shape_misses=shape_misses,
        fidelity_checked=fidelity_checked, fidelity_ok=fidelity_ok,
        fidelity_violations=fidelity_bad,
        degraded=degraded,
        healed_and_matched=healed_and_matched, charted=charted,
        avg_latency_ms=lat["mean_ms"], p50_latency_ms=lat["p50_ms"], p90_latency_ms=lat["p90_ms"],
        chart_matched=chart["matched"], chart_expected=chart["expected_charts"],
        chart_accuracy=chart["accuracy"], chart_mismatches=chart["mismatches"],
        no_chart_ok=chart["no_chart_ok"], no_chart_expected=chart["no_chart_expected"],
        extra_charts=chart["extra_charts"], chart_by_type=chart["by_type"],
        schema_cache_hits=schema_cache_hits, schema_cache_misses=schema_cache_misses,
    )

    runs_dir = ROOT / "eval" / "runs"
    runs_dir.mkdir(exist_ok=True)
    tag = f"heal-{args.heal}" + ("-chaos" if args.chaos else "")
    detail = runs_dir / f"{tag}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    detail.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")

    mode = ("注入⚡" if args.chaos else "自然") + ("/自愈" + ("开" if args.heal == "on" else "关"))
    print(f"\n=== {mode} === 准确率 {matched}/{total} = {acc:.1%}"
          f"(宽松口径 {semantic_matched}/{total} = {semantic_acc:.1%}),降级 {degraded},"
          f"出错后自愈成功 {healed_and_matched},出图 {charted}/{total},平均延迟 {summary['avg_latency_ms']}ms")
    if args.chaos:
        print(f"注入命中 {injection_hits}/{total}" + ("" if injection_valid else " ⚠️ 未全命中,该配置不可比"))
    print("内容缺失 " + (f"{len(content_misses)}:{','.join(content_misses)}" if content_misses else "0")
          + " | 形状差异 " + (f"{len(shape_misses)}:{','.join(shape_misses)}" if shape_misses else "0"))
    print(f"图表选型 {chart['matched']}/{chart['expected_charts']} = {chart['accuracy']:.1%}"
          + (f",不符 {chart['mismatches']}" if chart["mismatches"] else ",全部符合预期")
          + (f";榜单扩展出图 {chart['extra_charts']}(合规,不计错)" if chart["extra_charts"] else "")
          + f";延迟 p50={lat['p50_ms']}ms p90={lat['p90_ms']}ms")
    print(f"解读忠实性 {fidelity_ok}/{fidelity_checked} 条解读数字全部可追溯"
          + (f";违规 {fidelity_bad}" if fidelity_bad else ""))
    cache_total = schema_cache_hits + schema_cache_misses
    print(f"schema 缓存命中 {schema_cache_hits}/{cache_total}"
          + ("" if cache_total else "(本题集没有 get_schema 调用)"))
    print(f"明细:{detail}")

    results = ROOT / "eval" / "results.md"
    if not args.no_results_md:  # 补题/冒烟等小跑批不污染正式汇总表
        with results.open("a", encoding="utf-8") as f:
            f.write(
                f"| {summary['date']} | {mode} | {matched}/{total} "
                f"| {acc:.1%} | {degraded} | {healed_and_matched} | {charted}/{total} | {summary['avg_latency_ms']} |\n"
            )


if __name__ == "__main__":
    main()
