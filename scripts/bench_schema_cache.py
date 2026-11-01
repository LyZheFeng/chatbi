"""A1 收益量化:同一进程里 get_schema 冷(无缓存)/ 热(命中)各 N 次,给 µs/次。

为什么单独量:整题延迟被 LLM 往返主导(单题 p50 3–4s),schema 读取只有毫秒级,
跑批的 p50/p90 **测不出**这层收益——直接量单次调用,再折算"每轮 54 题省多少"才诚实。

用法:
    .venv/Scripts/python.exe -X utf8 scripts/bench_schema_cache.py          # 默认 200 次
    .venv/Scripts/python.exe -X utf8 scripts/bench_schema_cache.py --n 500
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import clear_schema_cache, connect_ro, schema_cache_info, schema_text  # noqa: E402


def _p90(values: list[float]) -> float:
    s = sorted(values)
    return s[int(round(0.9 * (len(s) - 1)))]


def main() -> int:
    ap = argparse.ArgumentParser(description="量化 schema 缓存单次收益")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    db_path = get_settings().db_path
    conn = connect_ro(db_path)
    try:
        clear_schema_cache()
        cold: list[float] = []
        for _ in range(args.n):
            clear_schema_cache()  # 每次都当"没缓存"来取,量的是无缓存成本
            t0 = time.perf_counter()
            schema_text(conn)
            cold.append((time.perf_counter() - t0) * 1e6)

        schema_text(conn)  # 预热条目
        warm: list[float] = []
        for _ in range(args.n):
            t0 = time.perf_counter()
            schema_text(conn)
            warm.append((time.perf_counter() - t0) * 1e6)
        info = schema_cache_info()
    finally:
        conn.close()

    c, w = statistics.median(cold), statistics.median(warm)
    saved_us = c - w
    per_round_ms = saved_us * 54 / 1000  # 54 题,每题 1 次 get_schema
    print(f"库:{db_path}")
    print(f"冷(无缓存)  中位 {c:8.1f} µs   p90 {_p90(cold):8.1f} µs  n={len(cold)}")
    print(f"热(缓存命中)中位 {w:8.1f} µs   p90 {_p90(warm):8.1f} µs  n={len(warm)}")
    print(f"单次节省 {saved_us:.1f} µs({c / w:.1f}×)")
    print(f"折算每轮 54 题共省 {per_round_ms:.1f} ms ≈ 单题 p50 3500ms 的 {per_round_ms / 3500 * 100:.2f}%")
    print(f"本次基准的缓存计数(冷热交替,命中率仅示意):{info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())