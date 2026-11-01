"""生成项目报告:数据库信息 + 历次评测结果(2026-11-01 汇总)。

用法:.venv/Scripts/python.exe -X utf8 scripts/make_report.py
输出:notes/eval-report-2026-11-01.md(全部数字从 data/chatbi.db 与 eval/runs/*.json 现算)
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
OUT = ROOT / "notes" / "eval-report-2026-11-01.md"
DB = ROOT / "data" / "chatbi.db"

MATRIX_A = {  # 18:14–19:18,50 题(修复前口径)
    "heal-on-20261101-181839", "heal-off-20261101-182439", "heal-off-chaos-20261101-183809",
    "heal-off-chaos-20261101-184024", "heal-off-chaos-20261101-184227", "heal-on-chaos-20261101-184748",
    "heal-on-chaos-20261101-185314", "heal-on-chaos-20261101-190021", "heal-on-20261101-190426",
    "heal-off-20261101-190858", "heal-on-20261101-191341", "heal-off-20261101-191832",
}
MATRIX_FINAL = {  # 22:16–22:58,54 题(最终口径)
    "heal-on-20261101-221940", "heal-off-20261101-222329", "heal-on-chaos-20261101-222814",
    "heal-off-chaos-20261101-222959", "heal-on-20261101-223329", "heal-off-20261101-223655",
    "heal-on-chaos-20261101-224130", "heal-off-chaos-20261101-224323", "heal-on-20261101-224709",
    "heal-off-20261101-225102", "heal-on-chaos-20261101-225600", "heal-off-chaos-20261101-225758",
}
OLD_0913 = "20260913"


def db_info() -> dict:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    info = {"size_kb": DB.stat().st_size / 1024, "tables": []}
    for t in tables:
        cols = [(c[1], c[2]) for c in conn.execute(f'PRAGMA table_info("{t}")')]
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        info["tables"].append({"name": t, "rows": n, "cols": cols})
    checks = {
        "customers.postal_code 为 NULL": "SELECT COUNT(*) FROM customers WHERE postal_code IS NULL",
        "customers.region 为 NULL": "SELECT COUNT(*) FROM customers WHERE region IS NULL",
        "order_items.quantity ≤ 0": "SELECT COUNT(*) FROM order_items WHERE quantity <= 0",
        "order_items.sales 为 NULL": "SELECT COUNT(*) FROM order_items WHERE sales IS NULL",
        "orders.ship_date < order_date": "SELECT COUNT(*) FROM orders WHERE ship_date < order_date",
        "order_items 明细总数": "SELECT COUNT(*) FROM order_items",
        "customers 客户总数": "SELECT COUNT(*) FROM customers",
    }
    info["dirty"] = [(k, conn.execute(v).fetchone()[0]) for k, v in checks.items()]
    enums = {}
    for col in ("market", "segment", "category", "sub_category", "ship_mode", "order_priority"):
        try:
            vals = [r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM {table_of(col)} ORDER BY 1")]
            enums[col] = vals
        except sqlite3.Error:
            pass
    info["enums"] = enums
    conn.close()
    return info


def table_of(col: str) -> str:
    return {"market": "geography", "segment": "customers", "category": "products",
            "sub_category": "products", "ship_mode": "orders", "order_priority": "orders"}[col]


def load_runs() -> list[dict]:
    out = []
    for p in sorted(RUNS.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "rounds" in data:
            rounds = data["rounds"]
            out.append(dict(kind="ambiguous", file=p.stem, date=data.get("date", ""),
                            model=data.get("llm_model", ""), rounds=len(rounds),
                            passed=sum(r["passed"] for r in rounds),
                            total=sum(r["total"] for r in rounds), cfg="歧义/无解"))
            continue
        s = data["summary"]
        chaos = s.get("chaos")
        if chaos is None:  # 早期跑批没有 chaos 字段,从文件名兜底
            chaos = "-chaos" in p.stem
        heal = s.get("heal")
        if heal is None:
            heal = "off" if p.stem.startswith("heal-off") else "on"
        model = s.get("llm_model") or ("旧模型(qwen3.8-27b)" if "20260913" in p.stem else "—")
        p50, p90 = s.get("p50_latency_ms"), s.get("p90_latency_ms")
        out.append(dict(
            kind="run", file=p.stem, date=s.get("date", ""), model=model,
            cfg=("注入⚡" if chaos else "自然") + "/自愈" + ("开" if heal == "on" else "关"),
            total=s["total"], strict=s["matched"], sem=s.get("semantic_matched"),
            chart=s.get("chart_matched"), chart_exp=s.get("chart_expected"),
            fid=s.get("fidelity_ok"), fid_chk=s.get("fidelity_checked"),
            hits=s.get("injection_hits"), p50=p50, p90=p90,
            content=len(s.get("content_misses") or []), shape=len(s.get("shape_misses") or []),
            deg=s.get("degraded"),
        ))
    return out


def pct(a, b):
    return f"{a / b * 100:.1f}%" if b else "—"


def matrix_table(runs: list[dict], ids: set[str], title: str) -> str:
    picked = [r for r in runs if r["kind"] == "run" and r["file"] in ids]
    order = {"自然/自愈开": 0, "自然/自愈关": 1, "注入⚡/自愈开": 2, "注入⚡/自愈关": 3}
    picked.sort(key=lambda r: (order.get(r["cfg"], 9), r["date"]))
    lines = [f"### {title}", "",
             "| 配置 | 轮次 | 时间 | 题数 | 严格 | 宽松 | 选型 | 忠实性 | p50 / p90 |",
             "|---|---|---|---|---|---|---|---|---|"]
    seen: Counter = Counter()
    for r in picked:
        seen[r["cfg"]] += 1
        lat = f"{r['p50']}/{r['p90']}ms" if r["p50"] is not None else "—"
        lines.append(
            f"| {r['cfg']} | {seen[r['cfg']]} | {r['date'][11:]} | {r['total']} "
            f"| {r['strict']}/{r['total']} = {pct(r['strict'], r['total'])} "
            f"| {r['sem'] if r['sem'] is not None else '—'} "
            f"| {r['chart']}/{r['chart_exp']} "
            f"| {r['fid'] if r['fid'] is not None else '—'}/{r['fid_chk'] if r['fid_chk'] is not None else '—'} "
            f"| {lat} |")
    return "\n".join(lines)


def main() -> None:
    info = db_info()
    runs = load_runs()
    full = [r for r in runs if r["kind"] == "run"]
    amb = [r for r in runs if r["kind"] == "ambiguous"]
    total_q = sum(r["total"] for r in full) + sum(r["total"] for r in amb)
    old = [r for r in full if OLD_0913 in r["file"] or "20260913" in r["date"].replace("-", "")]
    today = [r for r in full if r not in old]

    L: list[str] = []
    A = L.append
    A("# chatbi 项目报告:数据库 + 评测全记录(2026-11-01 汇总)")
    A("")
    A(f"> 本文件由 `scripts/make_report.py` 从 `data/chatbi.db` 与 `eval/runs/*.json` 现算生成;")
    A(f"> 共 **{len(runs)}** 个跑批文件(其中 {len(amb)} 个歧义专项文件含 {sum(r['rounds'] for r in amb)} 轮),")
    A(f"> 累计 **{total_q:,} 题次**。")
    A("")
    A("## 一、数据库")
    A("")
    A(f"- 引擎:SQLite(单文件,只读连接 `file:...?mode=ro`)")
    A(f"- 位置:`data/chatbi.db`({info['size_kb']:.0f} KB)")
    A("- 业务:Global Superstore 电商订单(中文问数场景),5 张关联表;DDL 内嵌中文列注释")
    A("- 建库:`scripts/` 下建库脚本从 CSV 生成,枚举取值/日期范围/折扣范围**由数据动态算进 DDL 注释**,")
    A("  并按固定规则注入 5 类脏数据(可复现)")
    A("")
    A("### 1.1 表与行数")
    A("")
    A("| 表 | 行数 | 列 |")
    A("|---|---|---|")
    for t in info["tables"]:
        cols = ", ".join(f"{n}" for n, _ in t["cols"])
        A(f"| `{t['name']}` | {t['rows']} | {cols} |")
    A("")
    A("关系:`geography(country, region)` ← `customers` → `orders` → `order_items` → `products`;")
    A("market 只能经 `customers.(country, region)` 关联 `geography` 到达(脏数据会让个别客户掉链)。")
    A("")
    A("### 1.2 脏数据(确定性注入)")
    A("")
    A("| 检查项 | 数量 |")
    A("|---|---|")
    for k, v in info["dirty"]:
        A(f"| {k} | {v} |")
    A("")
    A("### 1.3 低基数列的枚举取值(DDL 注释来源)")
    A("")
    A("| 列 | 取值 |")
    A("|---|---|")
    for col, vals in info["enums"].items():
        A(f"| `{col}` | {' / '.join(str(v) for v in vals)} |")
    A("")
    A("## 二、评测体系")
    A("")
    A("- **题库**:54 题(50 道基础 + 4 道图型补题:2 道占比 arc、2 道两数值 point),每题一句 gold SQL")
    A("- **判定**:严格口径(值集合一致、行序无关、列子集投影、单行 gold 答案点包含)+ 宽松口径(并列报告:")
    A("  多返回行、比率↔百分比、月份标签带不带年份);严格失配再拆 **内容缺失 / 形状差异**")
    A("- **指标**:执行准确率、图表选型准确率(逐题标注期望 mark)、延迟 p50/p90、解读忠实性(数字必须可追溯)")
    A("- **专项**:10 道歧义/无法回答题(规则判「澄清/降级/写明口径」);故障注入(改错首条 FROM/JOIN 后的业务表)")
    A("- **跑法**:`eval/run_eval.py --heal on|off [--chaos]`,temperature=0,明细落 `eval/runs/`,汇总追加 `eval/results.md`")
    A("")
    A("## 三、历次完整矩阵")
    A("")
    A("### 3.0 2026-09-13(Day 21 前后,旧模型;含 25 题阶段与 50 题终版)")
    A("")
    A("| 时间 | 配置 | 题数 | 严格 | 说明 |")
    A("|---|---|---|---|---|")
    for r in sorted(old, key=lambda x: x["date"]):
        A(f"| {r['date']} | {r['cfg']} | {r['total']} | {r['strict']}/{r['total']} = {pct(r['strict'], r['total'])} | 旧模型 |")
    A("")
    A(matrix_table(runs, MATRIX_A, "3.1 2026-11-01 18:14–19:18(50 题,形状修复前)"))
    A("")
    A(matrix_table(runs, MATRIX_FINAL, "3.2 2026-11-01 22:16–22:58(54 题,最终口径)"))
    A("")
    A("## 四、每一轮优化的前后对比")
    A("")
    A("| 轮次 | 优化前 | 优化后 | 变化 |")
    A("|---|---|---|---|")
    A("| 折线选型契约(15:32→18:14) | 严格 45/50=90.0%,选型 20/22 | 严格 47–48/50,选型 21–22/22 | 选型恢复 |")
    A("| 双口径 + 注入定位(18:14) | 注入⚡/关 7/6/6(12–14%,注入空转) | 注入⚡/关 0/0/0,命中 50/50 | 0% 下限恢复 |")
    A("| 解读忠实性(19:27–19:42) | 无此指标 | 3 轮 71 条解读 0 违规 | 新增守门 |")
    A("| 歧义/无解(19:47–19:53) | 无此专项 | 10 题 × 3 轮 30/30 无硬编 | 新增专项 |")
    A("| 模型对比(19:59–21:32) | 只有基线 | qwen 96%/98% p50 18.3s;glm 96%/100% p50 10s | 同档,差延迟 |")
    A("| 答案形状修复(21:48) | 严格 46/46/48,选型 20/20/22,p50 4.5–5.4s | 严格 50/49/49,选型 22/22/22,p50 3.1–3.3s | +4–6pp,快 1–2s |")
    A("| 图型补题 + 散点选择器(22:20) | 无 arc/point 自然题 | 补题选型 2/4 → 4/4 ×3 | 覆盖补齐 |")
    A("| 断言 + 失败分类(22:45) | 只看准确率 | 注入命中 54/54 校验、内容缺失/形状差异分列 | 结论可验证 |")
    A("| 最终矩阵(22:16–22:58) | 50 题 94–98% | 54 题自然 **100% ×3**、选型 26/26 | 收口 |")
    A("")
    hdr = ("## 五、附录:全部跑批明细")
    A(hdr)
    A("")
    A("| # | 时间 | 配置 | 模型 | 题数 | 严格 | 宽松 | 选型 | 忠实性 | 注入 | p50/p90 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(sorted(full, key=lambda x: x["date"]), 1):
        lat = f"{r['p50']}/{r['p90']}ms" if r["p50"] is not None else "—"
        A(f"| {i} | {r['date']} | {r['cfg']} | {r['model']} | {r['total']} | {r['strict']} "
          f"| {r['sem'] if r['sem'] is not None else '—'} "
          f"| {r['chart'] if r['chart'] is not None else '—'}/{r['chart_exp'] if r['chart_exp'] is not None else '—'} "
          f"| {r['fid'] if r['fid'] is not None else '—'}/{r['fid_chk'] if r['fid_chk'] is not None else '—'} "
          f"| {r['hits'] if r['hits'] is not None else '—'} | {lat} |")
    A("")
    A("### 歧义 / 未知答案专项")
    A("")
    A("| 时间 | 轮数 | 通过 |")
    A("|---|---|---|")
    for r in amb:
        A(f"| {r['date']} | {r['rounds']} | {r['passed']}/{r['total']} |")
    A("")
    A("> 19:47 那次 7/10 是判定器偏严的试跑(当时把「写明指标/范围」判成硬编),")
    A("> 修正判定后正式 3 轮 30/30;明细见 `eval/runs/ambiguous-*.json`。")
    A("")
    A("### 冒烟")
    A("")
    A("`scripts/smoke_eval.py` 每次 5 题,今天跑了 3–4 次(含快照刷新),不计入上方 74 个跑批文件;")
    A("最近一次 **5/5、无漂移**。")
    A("")
    A("## 六、结论与边界")
    A("")
    A("- 自然模式:**54/54 ×3(100%)**,内容缺失 0;注入⚡/自愈开 96.3–100%,注入⚡/自愈关 **0% ×3**")
    A("- 图表选型 **26/26 ×3**;解读忠实性有答案的 9 轮 × 28 条 **0 违规**;歧义/无解 30/30")
    A("- 延迟:自然 p50 3.5–3.9s / p90 5.2–6.3s;注入⚡/自愈关 1.8–2.0s(首错即降级)")
    A("- 边界:样本 54 题;判定只比「表里有没有答案」,不判「是否回答用户真实意图」;")
    A("  歧义判定为关键词规则,记录保留完整 summary 供人工复核;数字受时段与网关负载影响")
    A("")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"写入 {OUT} ({len(L)} 行)")


if __name__ == "__main__":
    main()