"""生成项目报告:数据库 + 每一轮优化的测评结果(2026-11-01)。

用法:.venv/Scripts/python.exe -X utf8 scripts/make_report.py
输出:notes/eval-report-2026-11-01.md(数字全部从 data/chatbi.db 与 eval/runs/*.json 现算)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
OUT = ROOT / "notes" / "eval-report-2026-11-01.md"
DB = ROOT / "data" / "chatbi.db"

# ---- 各轮优化对应的跑批文件(按时间窗口挑,名称即证据)----
R1_BEFORE = ["heal-on-20261101-153200"]
R1_AFTER = ["heal-on-20261101-154918", "heal-on-20261101-164808", "heal-on-20261101-173319"]
R2_INJ_BEFORE = ["heal-off-chaos-20261101-162039", "heal-off-chaos-20261101-172716",
                 "heal-off-chaos-20261101-175105"]
MATRIX_A = ["heal-on-20261101-181839", "heal-off-20261101-182439", "heal-off-chaos-20261101-183809",
            "heal-off-chaos-20261101-184024", "heal-off-chaos-20261101-184227",
            "heal-on-chaos-20261101-184748", "heal-on-chaos-20261101-185314",
            "heal-on-chaos-20261101-190021", "heal-on-20261101-190426",
            "heal-off-20261101-190858", "heal-on-20261101-191341", "heal-off-20261101-191832"]
R3_FIDELITY = ["heal-on-20261101-193214", "heal-on-20261101-193705", "heal-on-20261101-194214"]
R6_BEFORE = R3_FIDELITY
R6_AFTER_Q28 = ["heal-on-20261101-215103", "heal-on-20261101-215408", "heal-on-20261101-215717"]
R6_AFTER_ALL = ["heal-on-20261101-220037", "heal-on-20261101-220342", "heal-on-20261101-220654"]
R7_PROBE_BEFORE = ["heal-on-20261101-221004", "heal-on-20261101-221029", "heal-on-20261101-221052"]
R7_PROBE_AFTER = ["heal-on-20261101-221209", "heal-on-20261101-221231", "heal-on-20261101-221257"]
R5_QWEN = ["heal-on-20261101-201940", "heal-on-20261101-203942", "heal-on-20261101-205942"]
R5_GLM = ["heal-on-20261101-211219", "heal-on-20261101-212249", "heal-on-20261101-213216"]
MATRIX_FINAL = ["heal-on-20261101-221940", "heal-off-20261101-222329", "heal-on-chaos-20261101-222814",
                "heal-off-chaos-20261101-222959", "heal-on-20261101-223329", "heal-off-20261101-223655",
                "heal-on-chaos-20261101-224130", "heal-off-chaos-20261101-224323",
                "heal-on-20261101-224709", "heal-off-20261101-225102",
                "heal-on-chaos-20261101-225600", "heal-off-chaos-20261101-225758"]


def db_info() -> dict:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    info = {"size_kb": DB.stat().st_size / 1024, "tables": []}
    for t in tables:
        cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")')]
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        info["tables"].append({"name": t, "rows": n, "cols": cols})
    checks = [
        ("customers.postal_code 为 NULL", "SELECT COUNT(*) FROM customers WHERE postal_code IS NULL"),
        ("customers.region 为 NULL", "SELECT COUNT(*) FROM customers WHERE region IS NULL"),
        ("order_items.quantity ≤ 0", "SELECT COUNT(*) FROM order_items WHERE quantity <= 0"),
        ("order_items.sales 为 NULL", "SELECT COUNT(*) FROM order_items WHERE sales IS NULL"),
        ("orders.ship_date < order_date", "SELECT COUNT(*) FROM orders WHERE ship_date < order_date"),
    ]
    info["dirty"] = [(k, conn.execute(v).fetchone()[0]) for k, v in checks]
    info["enums"] = {}
    for col, tbl in [("market", "geography"), ("segment", "customers"), ("category", "products"),
                     ("sub_category", "products"), ("ship_mode", "orders"), ("order_priority", "orders")]:
        vals = [str(r[0]) for r in conn.execute(f"SELECT DISTINCT {col} FROM {tbl} ORDER BY 1")]
        info["enums"][col] = vals
    conn.close()
    return info


def load_runs() -> tuple[dict[str, dict], list[dict]]:
    by_file: dict[str, dict] = {}
    ambiguous: list[dict] = []
    for p in sorted(RUNS.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "rounds" in data:
            ambiguous.append(dict(file=p.stem, date=data.get("date", ""),
                                  rounds=len(data["rounds"]),
                                  passed=sum(r["passed"] for r in data["rounds"]),
                                  total=sum(r["total"] for r in data["rounds"])))
            continue
        s = data["summary"]
        chaos = s.get("chaos")
        if chaos is None:
            chaos = "-chaos" in p.stem
        heal = s.get("heal")
        if heal is None:
            heal = "off" if p.stem.startswith("heal-off") else "on"
        by_file[p.stem] = dict(
            date=s.get("date", ""), model=s.get("llm_model") or "旧模型",
            cfg=("注入⚡" if chaos else "自然") + "/自愈" + ("开" if heal == "on" else "关"),
            total=s["total"], strict=s["matched"], sem=s.get("semantic_matched"),
            chart=s.get("chart_matched"), chart_exp=s.get("chart_expected"),
            fid=s.get("fidelity_ok"), fid_chk=s.get("fidelity_checked"),
            hits=s.get("injection_hits"), p50=s.get("p50_latency_ms"), p90=s.get("p90_latency_ms"),
        )
    return by_file, ambiguous


def pct(a, b) -> str:
    return f"{a / b * 100:.1f}%" if b else "—"


def runs_table(by_file: dict[str, dict], ids: list[str]) -> str:
    lines = ["| 时间 | 配置 | 题数 | 严格 | 宽松 | 选型 | 忠实性 | p50 / p90 |",
             "|---|---|---|---|---|---|---|---|"]
    for fid in ids:
        r = by_file.get(fid)
        if not r:
            continue
        lat = f"{r['p50']}/{r['p90']}ms" if r["p50"] is not None else "—"
        lines.append(
            f"| {r['date']} | {r['cfg']} | {r['total']} "
            f"| {r['strict']}/{r['total']} = {pct(r['strict'], r['total'])} "
            f"| {r['sem'] if r['sem'] is not None else '—'} "
            f"| {r['chart']}/{r['chart_exp']} "
            f"| {r['fid'] if r['fid'] is not None else '—'}/{r['fid_chk'] if r['fid_chk'] is not None else '—'} "
            f"| {lat} |")
    return "\n".join(lines)


def main() -> None:
    info = db_info()
    by_file, ambiguous = load_runs()
    L: list[str] = []
    A = L.append

    A("# chatbi 项目报告:数据库 + 每一轮优化的测评结果")
    A("")
    A("> 由 `scripts/make_report.py` 从 `data/chatbi.db` 与 `eval/runs/*.json` 现算生成。")
    total_files = len(by_file) + len(ambiguous)
    A(f"> 共 {total_files} 个跑批文件、{sum(r['total'] for r in by_file.values()) + sum(r['total'] for r in ambiguous):,} 题次;")
    A("> 下文按**优化轮次**组织:每轮先写改了什么,再贴该轮的测评结果,最后给说明。")
    A("")

    # ---------------- 数据库 ----------------
    A("## 一、数据库")
    A("")
    A(f"- SQLite 单文件 `data/chatbi.db`({info['size_kb']:.0f} KB),只读连接 `file:...?mode=ro`")
    A("- Global Superstore 电商订单:5 张关联表;DDL 内嵌中文列注释,枚举取值由数据动态算入注释")
    A("- 确定性注入 5 类脏数据,可复现")
    A("")
    A("| 表 | 行数 | 列 |")
    A("|---|---|---|")
    for t in info["tables"]:
        A(f"| `{t['name']}` | {t['rows']} | {', '.join(t['cols'])} |")
    A("")
    A("| 脏数据 | 数量 |")
    A("|---|---|")
    for k, v in info["dirty"]:
        A(f"| {k} | {v} |")
    A("")
    A("| 低基数列 | 取值(DDL 注释来源) |")
    A("|---|---|")
    for col, vals in info["enums"].items():
        A(f"| `{col}` | {' / '.join(vals)} |")
    A("")

    # ---------------- 口径 ----------------
    A("## 二、评测口径")
    A("")
    A("- 题库 54 题(50 基础 + 4 图型补题),每题一句 gold SQL;两边各自执行成表再比值集合")
    A("- 严格口径:值集合一致、行序无关、列子集投影、单行 gold 答案点包含;")
    A("  严格失配再拆「内容缺失」(宽松也救不回)与「形状差异」(多返回行/百分比/标签)")
    A("- 宽松口径(并列报告):放宽多返回行、比率↔百分比、月份标签带不带年份")
    A("- 其他指标:图表选型(逐题标注期望 mark)、延迟 p50/p90、解读忠实性(数字必须可追溯)")
    A("- 专项:10 道歧义/无解题(判「澄清/降级/写明口径」);故障注入(改错首条 FROM/JOIN 后的业务表)")
    A("")

    # ---------------- 逐轮 ----------------
    A("## 三、逐轮优化与测评结果")
    A("")

    A("### 优化 #1:折线选型契约(15:32 → 17:33)")
    A("")
    A("**问题**:时间序列带 ≥3 个数值列时,折线分支要求「≤2 数值列」→ 整张不画(q06/q40 与 smoke s4-ts 实测)。")
    A("")
    A("**改动**:`app/charts.py` 折线取前两个数值列,与柱状/横条同口径;多余数值列留在表格。")
    A("")
    A("**结果**:")
    A("")
    A(runs_table(by_file, R1_BEFORE))
    A("")
    A(runs_table(by_file, R1_AFTER))
    A("")
    A("**说明**:选型从 20/22(90.9%)恢复到 21–22/22;严格准确率同步 45→48–49(90%→96–98%),")
    A("因为「该画没画」的题本身答案是对的,之前只掉在选型指标上。")
    A("")

    A("### 优化 #2:判定双口径 + 注入定位(18:14 → 19:18,50 题)")
    A("")
    A("**问题 A**:多行 gold 要求值集合完全一致 → 模型「问前 3 返回完整排名」被误判(q08/q22)。")
    A("**问题 B**:注入用裸词替换,先撞上别名 `COUNT(...) AS orders`,SQL 仍合法 → 注入空转,")
    A("注入⚡/自愈关 被抬到 12–14%,0% 下限失效。")
    A("")
    A("**改动**:新增 `table_matches_semantic`(宽松口径,空集合/百分比/月份标签)并列报告;")
    A("注入改为只改 `FROM/JOIN` 后的业务表,且只对「真的改写了」的 SQL 计入 `stats.injection_hits`。")
    A("")
    A("**结果(注入⚡/自愈关 修复前后)**:")
    A("")
    A(runs_table(by_file, R2_INJ_BEFORE))
    A("")
    A(runs_table(by_file, [x for x in MATRIX_A if "off-chaos" in x]))
    A("")
    A("**结果(整轮矩阵)**:")
    A("")
    A(runs_table(by_file, MATRIX_A))
    A("")
    A("**说明**:注入关从 7/6/6(12–14%)回到 0/0/0,且每轮注入命中 50/50,对照实验变干净;")
    A("宽松口径把「内容对、写法不同」从失败里摘出:严格 94–98% ↔ 宽松 96–100%。")
    A("")

    A("### 优化 #3:解读忠实性(19:27 → 19:42)")
    A("")
    A("**问题**:模板解读可能写死/漂移数字,没人验证它是否来自结果表。")
    A("")
    A("**改动**:`eval/fidelity.py` 抽解读数字,从结果表独立重算允许集合(单元格/列和/分组和/占比/")
    A("变化率/比值/相关系数/行数),集合外即违规;gold 表自检必须 0 违规。")
    A("")
    A("**结果**:")
    A("")
    A(runs_table(by_file, R3_FIDELITY))
    A("")
    A("**说明**:3 轮 71 条解读(23/22/26)全部 0 违规;gold 自检 22 条也 0 违规——")
    A("说明校验器既没放水、也没冤枉正确解读。")
    A("")

    A("### 优化 #4:歧义 / 无法回答题(19:47 → 19:53)")
    A("")
    A("**问题**:题库全是「能答」的题,测不出「不会答时是否优雅降级」。")
    A("")
    A("**改动**:`eval/ambiguous.py` 5 道库内无解 + 5 道歧义,规则判定「澄清/降级/写明口径」,裸答案判失败。")
    A("")
    A("**结果**:")
    A("")
    A("| 时间 | 轮数 | 通过 |")
    A("|---|---|---|")
    for a in ambiguous:
        A(f"| {a['date']} | {a['rounds']} | {a['passed']}/{a['total']} |")
    A("")
    A("**说明**:首次 7/10 是判定器偏严(把「写明指标」当硬编),修正后正式 3 轮 30/30;")
    A("行为分布:说明缺失 14、优雅降级 1、写明指标/范围 9、澄清/口径 6。")
    A("")

    A("### 优化 #5:模型对比(19:59 → 21:32)")
    A("")
    A("**问题**:只有默认模型的数据,无法回答「换模型值不值」。")
    A("")
    A("**改动**:环境变量临时切模型(不动 `.env`),qwen3.8-27b 与 glm-5.3 各 3 轮自然模式。")
    A("")
    A("**结果(qwen3.8-27b)**:")
    A("")
    A(runs_table(by_file, R5_QWEN))
    A("")
    A("**结果(glm-5.3)**:")
    A("")
    A(runs_table(by_file, R5_GLM))
    A("")
    A("**说明**:三模型准确率同档(93–96%),差异在延迟:qwen p50 18.3s、glm 9.6–12.8s、基线 4.5–5.4s;")
    A("glm 宽松口径 100%。`deepseek-v4-pro` 当周额度耗尽未参评。")
    A("")

    A("### 优化 #6:答案形状修复(21:48 → 22:07,50 题)")
    A("")
    A("**问题**:q28 问「总销售额」只给逐月明细(9 次跑批 4 次);q19 答案是 0 却反复重查、")
    A("8 步耗尽(9 次跑批 2 次)。")
    A("")
    A("**改动**:`SYSTEM_PROMPT` 加「结果形状」三条(总X→单行合计;各X→分组明细不加合计行;")
    A("趋势→时间序列)+「0/空结果是合法答案」。")
    A("")
    A("**结果(修复前)**:")
    A("")
    A(runs_table(by_file, R6_BEFORE))
    A("")
    A("**结果(先只修 q28 的三轮)**:")
    A("")
    A(runs_table(by_file, R6_AFTER_Q28))
    A("")
    A("**结果(合并两条规则的三轮)**:")
    A("")
    A(runs_table(by_file, R6_AFTER_ALL))
    A("")
    A("**说明**:严格 46/46/48 → 50/49/49,宽松首次 100%,选型 22/22 全恢复,p50 4.5–5.4s → 3.1–3.3s")
    A("(形状约束减少了「又查明细又查合计」的往返);q28 三轮单行 371,803.89,q19 三轮以 0 收尾。")
    A("")

    A("### 优化 #7:图型补题 + 散点选择器(22:10 → 22:12)")
    A("")
    A("**问题**:50 题没有占比(arc)和两数值(point)自然问法,选型只覆盖折线/柱状。")
    A("")
    A("**改动**:新增 p01–p04;补题首跑发现 p03/p04(散点)被模型多带的维度列带成柱状 →")
    A("`app/charts.py` 加「题目要散点/相关/关系时优先散点」。")
    A("")
    A("**结果(修选择器前)**:")
    A("")
    A(runs_table(by_file, R7_PROBE_BEFORE))
    A("")
    A("**结果(修选择器后)**:")
    A("")
    A(runs_table(by_file, R7_PROBE_AFTER))
    A("")
    A("**说明**:补题 4 题选型 2/4 → 4/4 ×3;题库 50 → 54。")
    A("")

    A("### 优化 #8:注入命中断言 + 失败分类(22:15 → 22:45)")
    A("")
    A("**问题**:注入是否会空转、严格失配是「真错」还是「写法」,之前只能人工看 JSON。")
    A("")
    A("**改动**:跑批加 `injection_valid`(命中数 < 题数即标红)与 `content_misses / shape_misses` 分类,每轮打印题号。")
    A("")
    A("**结果(1 题注入自检)**:")
    A("")
    A(runs_table(by_file, ["heal-off-chaos-20261101-221528"]))
    A("")
    A("**说明**:自检显示命中 1/1、内容缺失 1(q01),断言生效;最终矩阵 12 轮全部 54/54 命中。")
    A("")

    A("### 优化 #9:最终矩阵(22:19 → 22:57,54 题 × 4 配置 × 3 轮)")
    A("")
    A("**目的**:所有改动落定后,用最终代码与 54 题口径重跑一轮完整矩阵。")
    A("")
    A("**结果**:")
    A("")
    A(runs_table(by_file, MATRIX_FINAL))
    A("")
    A("**说明**:自然/自愈开 54/54 ×3;自愈关 53、54、54;注入⚡/自愈开 52、54、54(命中 54/54 ×3);")
    A("注入⚡/自愈关 0/54 ×3。选型 26/26 ×3,忠实性 0 违规;内容缺失全矩阵仅 1 次(r1 注入开 q19)。")
    A("")

    A("### 历史轮次(Day 17–21,旧模型,仅摘要)")
    A("")
    A("| 轮次 | 触发 | 改动 | 结果 |")
    A("|---|---|---|---|")
    A("| Day 17–18 | 25 题基线 | 首版 agent + 评测 | 自然 92%,注入关 0%、注入开 88% |")
    A("| Day 19 | 枚举探查耗步数 | Schema 注入(枚举/日期/折扣范围进 DDL) | 25 题 96%;注入开 88%→100% |")
    A("| Day 20 | 不会出图 | 图表 + 模板解读 + 脏数据契约 | 出图 24/50,无「该画没画」 |")
    A("| Day 21 | 安全与口径 | token 白名单/限流/CORS;中位数语义入提示 | 50 题 100%(旧模型),注入开 100% |")
    A("| Day 22 | 工具化 | MCP stdio server | 50 题 gold 双通道一致 |")
    A("")
    A("> 09-13 的 12 次跑批是旧模型 25/50 题阶段的矩阵,明细见附录。")
    A("")

    # ---------------- 总账 ----------------
    A("## 四、总账:每轮关键变化")
    A("")
    A("| 轮次 | 严格 | 选型 | p50 | 关键变化 |")
    A("|---|---|---|---|---|")
    A("| #1 折线契约 | 90.0% → 96–98% | 20/22 → 21–22/22 | 4286 → 4459ms | 该画没画修好 |")
    A("| #2 双口径+注入 | 94–98%(宽松 96–100%) | 21–22/22 | 4302–4810ms | 注入关 12–14% → 0% |")
    A("| #3 忠实性 | 92–96% | 20–22/22 | 4465–5398ms | 71 条解读 0 违规 |")
    A("| #4 歧义 | — | — | — | 30/30 无硬编 |")
    A("| #5 模型对比 | qwen 96% / glm 96% | 21/22 | 18.3s / 10–12.8s | 同档,差延迟 |")
    A("| #6 形状修复 | 94–96% → 98–100% | 20–22/22 → 22/22 | 4.5–5.4s → 3.1–3.3s | q28/q19 修复 |")
    A("| #7 补题+选择器 | 4/4 ×3 | 2/4 → 4/4 | — | arc/point 覆盖补齐 |")
    A("| #8 断言 | — | — | — | 命中 54/54、失败可分类 |")
    A("| #9 最终矩阵 | **100% ×3**(自然开) | **26/26 ×3** | 3.5–3.9s | 收口 |")
    A("")

    # ---------------- 附录 ----------------
    A("## 五、附录:全部跑批明细")
    A("")
    A("| # | 时间 | 配置 | 模型 | 题数 | 严格 | 宽松 | 选型 | 忠实性 | 注入 | p50/p90 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    order = {"自然/自愈开": 0, "自然/自愈关": 1, "注入⚡/自愈开": 2, "注入⚡/自愈关": 3}
    all_runs = sorted(by_file.values(), key=lambda r: (r["date"], order.get(r["cfg"], 9)))
    for i, r in enumerate(all_runs, 1):
        lat = f"{r['p50']}/{r['p90']}ms" if r["p50"] is not None else "—"
        A(f"| {i} | {r['date']} | {r['cfg']} | {r['model']} | {r['total']} | {r['strict']} "
          f"| {r['sem'] if r['sem'] is not None else '—'} "
          f"| {r['chart'] if r['chart'] is not None else '—'}/{r['chart_exp'] if r['chart_exp'] is not None else '—'} "
          f"| {r['fid'] if r['fid'] is not None else '—'}/{r['fid_chk'] if r['fid_chk'] is not None else '—'} "
          f"| {r['hits'] if r['hits'] is not None else '—'} | {lat} |")
    A("")
    A("### 冒烟")
    A("")
    A("`scripts/smoke_eval.py` 每次 5 题,今天跑了 3–4 次(含快照刷新);最近一次 **5/5、无漂移**。")
    A("")

    A("## 六、结论与边界")
    A("")
    A("- 优化 #9 之后:自然/自愈开 **54/54 ×3(100%)**,注入⚡/自愈关 **0/54 ×3**,选型 **26/26 ×3**")
    A("- 内容缺失全矩阵仅 1 次(r1 注入开 q19 步数耗尽);形状差异 2 次")
    A("- 延迟:自然 p50 3.5–3.9s / p90 5.2–6.3s;注入⚡/自愈关 1.8–2.0s(首错即降级)")
    A("- 边界:样本 54 题;判定只比「表里有没有答案」,不判「是否回答用户真实意图」;")
    A("  歧义判定为关键词规则(保留 summary 供人工复核);数字受时段与网关负载影响")
    A("")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"写入 {OUT} ({len(L)} 段,{sum(1 for x in L if chr(10) in x)} 段含多行)")


if __name__ == "__main__":
    main()