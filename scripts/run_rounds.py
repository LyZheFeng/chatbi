"""按用户规则连跑 N 轮(默认 3)同一配置,任一轮失败即**停止整批**。

规则(2026-11-02 交接,用户确认,必须遵守):
1. 每次验证跑批必须 **3 轮**(同一配置连跑 3 次,报告里给 3 个值);
2. 模型无响应(`LLM` 异常/超时/503)时,`eval/run_eval.py: ask_with_retry` 等 **10 分钟**
   再试、最多 **3 次**;3 次仍失败 → 本轮以非零退出,本脚本**立即停止整批**,
   不跑后续轮次、不改动已落盘的结果,把失败原因打印出来交回用户决定;
3. 每轮都是独立子进程 + 独立明细 JSON(`eval/runs/`),互不污染;汇总行由
   `run_eval.py` 追加进 `eval/results.md`。

用法:
    .venv/Scripts/python.exe -X utf8 scripts/run_rounds.py --heal on
    .venv/Scripts/python.exe -X utf8 scripts/run_rounds.py --heal off --chaos
    .venv/Scripts/python.exe -X utf8 scripts/run_rounds.py --heal on --rounds 1 --limit 3  # 调试
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_EVAL = ROOT / "eval" / "run_eval.py"


def main() -> int:
    ap = argparse.ArgumentParser(description="连跑 N 轮同一配置(默认 3 轮),失败即停止整批")
    ap.add_argument("--heal", choices=["on", "off"], required=True)
    ap.add_argument("--chaos", action="store_true", help="故障注入(改错首条 FROM/JOIN 的表名)")
    ap.add_argument("--rounds", type=int, default=3, help="轮数,默认 3(用户规则)")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题(调试用)")
    ap.add_argument("--only", default="", help="只跑指定 id(调试用)")
    ap.add_argument("--no-results-md", action="store_true", help="不追加 eval/results.md(调试用)")
    args = ap.parse_args()
    if args.rounds < 1:
        ap.error("--rounds 必须 >= 1")

    cmd = [sys.executable, "-X", "utf8", str(RUN_EVAL), "--heal", args.heal]
    if args.chaos:
        cmd.append("--chaos")
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.only:
        cmd += ["--only", args.only]
    if args.no_results_md:
        cmd.append("--no-results-md")

    mode = ("注入⚡" if args.chaos else "自然") + "/自愈" + ("开" if args.heal == "on" else "关")
    print(f"=== 连跑 {args.rounds} 轮:{mode} | 开始 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)

    for i in range(1, args.rounds + 1):
        print(f"\n----- 第 {i}/{args.rounds} 轮 -----", flush=True)
        t0 = time.perf_counter()
        rc = subprocess.call(cmd, cwd=str(ROOT))
        took = time.perf_counter() - t0
        if rc != 0:
            print(
                f"\n!! 第 {i} 轮失败(exit={rc},{took:.0f}s)。按规则**停止整批**:"
                "不跑后续轮次,也不改动已落盘的结果;请把上面的失败原因交回用户决定。",
                flush=True,
            )
            return rc
        print(f"第 {i} 轮完成:{took:.0f}s", flush=True)

    print(f"\n=== {args.rounds} 轮全部完成:{mode} | 结束 {time.strftime('%H:%M:%S')} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())