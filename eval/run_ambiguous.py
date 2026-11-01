"""歧义/无法回答题跑批(评测 2.0 第 3 项):10 题 × 3 轮,判"优雅降级/澄清 vs 硬编"。

用法:
    .venv/Scripts/python.exe -X utf8 eval/run_ambiguous.py          # 3 轮
    .venv/Scripts/python.exe -X utf8 eval/run_ambiguous.py --rounds 1

产出:控制台逐题结果 + 明细 JSON(`eval/runs/ambiguous-<时间>.json`),不写 results.md(手工整理)。
判定规则见 `eval/ambiguous.py`,复用 `run_eval.ask_with_retry` 的整题重试。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.ambiguous import QUESTIONS, judge  # noqa: E402
from eval.run_eval import ask_with_retry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    from app.agent import ChatbiAgent
    from app.config import Settings
    from app.db import connect_ro
    from app.llm import LLM
    from app.service import ChatbiService

    settings = Settings()
    service = ChatbiService(lambda: ChatbiAgent(
        LLM.from_settings(), connect_ro(settings.db_path),
        max_steps=settings.max_tool_steps, cap=settings.sql_row_cap,
        auto_limit=settings.auto_limit, self_heal=settings.self_heal,
        max_sql_retries=settings.max_sql_retries,
    ))

    rounds, all_pass = [], 0
    for r in range(1, args.rounds + 1):
        records = []
        print(f"\n===== 第 {r} 轮 =====")
        for q in QUESTIONS:
            resp = ask_with_retry(service, q["question"])
            ok, reason = judge(q["kind"], resp.error, resp.summary, resp.row_count)
            records.append(dict(
                id=q["id"], kind=q["kind"], question=q["question"], why=q["why"],
                ok=ok, reason=reason, error=resp.error, summary=resp.summary,
                columns=resp.columns, row_count=resp.row_count, chart=bool(resp.chart_spec),
                sql=resp.sql, latency_ms=resp.latency_ms, stats=resp.stats,
            ))
            flag = "✓" if ok else "✗"
            print(f"{flag} {q['id']} [{q['kind']}] {resp.latency_ms}ms rows={resp.row_count} | {reason}")
        n_ok = sum(r_["ok"] for r_ in records)
        by_kind = {
            k: (sum(1 for r_ in records if r_["kind"] == k and r_["ok"]),
                sum(1 for r_ in records if r_["kind"] == k))
            for k in ("unanswerable", "ambiguous")
        }
        print(f"第 {r} 轮通过 {n_ok}/{len(records)}｜无解 {by_kind['unanswerable'][0]}/{by_kind['unanswerable'][1]}"
              f"、歧义 {by_kind['ambiguous'][0]}/{by_kind['ambiguous'][1]}")
        rounds.append(dict(round=r, passed=n_ok, total=len(records), records=records))
        all_pass += n_ok

    runs_dir = ROOT / "eval" / "runs"
    runs_dir.mkdir(exist_ok=True)
    detail = runs_dir / f"ambiguous-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    detail.write_text(json.dumps(dict(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        llm_model=settings.llm_model,
        rounds=rounds,
    ), ensure_ascii=False, indent=1), encoding="utf-8")
    total_q = len(QUESTIONS) * args.rounds
    print(f"\n合计 {all_pass}/{total_q} 通过;明细:{detail}")


if __name__ == "__main__":
    main()