"""端到端演示:真实 LLM + 真实库,问几个中文问题看全链路。

用法:.venv/Scripts/python.exe -X utf8 scripts/demo_ask.py [问题...]
不带参数时跑内置 4 题。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.service import get_service  # noqa: E402

DEFAULT_QUESTIONS = [
    "2014 年销售额最高的 5 个国家是哪些?",
    "三个商品大类(Furniture/Office Supplies/Technology)的销售额和利润对比",
    "亚太市场 2013-2014 按月销售额趋势",
    "order_items 里有没有异常数据?比如数量为负、为 0 或销售额缺失的行",
]


def main() -> None:
    questions = sys.argv[1:] or DEFAULT_QUESTIONS
    service = get_service()
    for q in questions:
        print("=" * 70)
        print("问:", q)
        resp = service.ask(q)
        print(f"[{resp.latency_ms} ms, {len(resp.steps)} 步] " + (f"error={resp.error}" if resp.error else "ok"))
        print("结论:", resp.summary)
        if resp.sql:
            print("SQL:", resp.sql.replace("\n", " ")[:160])
        if resp.columns:
            print("表头:", resp.columns)
            for row in resp.rows[:5]:
                print("  ", row)
            if resp.row_count > 5:
                print(f"   ... 共 {resp.row_count} 行")
        if resp.chart_spec:
            print(f"[图表] {resp.chart_spec['mark']['type']} | {resp.chart_reading}")
        for s in resp.steps:
            mark = "✓" if s.ok else "✗"
            print(f"  {mark} 步骤{s.step} {s.tool}: {s.detail[:90]}")


if __name__ == "__main__":
    main()
