"""把最终矩阵的跑批 JSON 画成一张概览图(纯标准库,输出 SVG;README 直接引用)。

用法:.venv/Scripts/python.exe -X utf8 scripts/plot_overview.py
输入:eval/runs/*20261101-22*.json(最终矩阵 12 次跑批)
输出:eval/overview.svg(准确率 strict/semantic + 延迟 p50/p90,按配置分组)
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [("nat", "on", "自然/自愈开"), ("nat", "off", "自然/自愈关"),
           ("chaos", "on", "注入/自愈开"), ("chaos", "off", "注入/自愈关")]
W, H = 820, 360
C_STRICT, C_SEM = "#2563eb", "#93c5fd"
C_P50, C_P90 = "#0f766e", "#5eead4"
INK, MUTED, GRID = "#111827", "#6b7280", "#e5e7eb"


def load() -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for path in sorted((ROOT / "eval" / "runs").glob("*20261101-22*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        s = data["summary"]
        if s.get("total") != 54:
            continue
        key = ("chaos" if s.get("chaos") else "nat", s.get("heal"))
        groups.setdefault(key, []).append(s)
    return groups


def stats(runs: list[dict]) -> dict:
    n = len(runs)
    mean = lambda f: sum(f(r) for r in runs) / n  # noqa: E731
    return dict(
        strict=mean(lambda r: r["matched"] / r["total"]) * 100,
        sem=mean(lambda r: r["semantic_matched"] / r["total"]) * 100,
        p50=mean(lambda r: r["p50_latency_ms"]),
        p90=mean(lambda r: r["p90_latency_ms"]),
    )


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    groups = load()
    data = {cfg: stats(groups[(kind, heal)]) for kind, heal, cfg in CONFIGS if (kind, heal) in groups}
    assert len(data) == 4, f"缺少配置:{data.keys()}"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
        f'<rect width="{W}" height="{H}" fill="white"/>',
        f'<text x="20" y="28" font-size="15" font-weight="600" fill="{INK}">最终矩阵:54 题 × 4 配置 × 3 轮(平均)</text>',
    ]

    # ---- 左:准确率 ----
    x0, y0, pw, ph = 40, 60, 320, 220
    parts.append(f'<text x="{x0}" y="{y0 - 8}" font-size="12" fill="{MUTED}">执行准确率(%)</text>')
    for g in range(0, 101, 25):
        y = y0 + ph - ph * g / 100
        parts.append(f'<line x1="{x0}" y1="{y}" x2="{x0 + pw}" y2="{y}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x0 - 8}" y="{y + 4}" font-size="10" fill="{MUTED}" text-anchor="end">{g}</text>')
    slot = pw / len(data)
    for i, (cfg, st) in enumerate(data.items()):
        for j, (val, color) in enumerate(((st["strict"], C_STRICT), (st["sem"], C_SEM))):
            bw = slot * 0.30
            bx = x0 + slot * i + slot * 0.12 + j * (bw + 6)
            bh = ph * val / 100
            parts.append(f'<rect x="{bx:.1f}" y="{y0 + ph - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" rx="2"/>')
            parts.append(f'<text x="{bx + bw / 2:.1f}" y="{y0 + ph - bh - 4:.1f}" font-size="9" fill="{INK}" text-anchor="middle">{val:.0f}</text>')
        parts.append(f'<text x="{x0 + slot * i + slot / 2:.1f}" y="{y0 + ph + 16}" font-size="10" fill="{INK}" text-anchor="middle">{esc(cfg)}</text>')
    parts.append(f'<rect x="{x0}" y="{y0 + ph + 26}" width="10" height="10" fill="{C_STRICT}"/>')
    parts.append(f'<text x="{x0 + 14}" y="{y0 + ph + 35}" font-size="10" fill="{MUTED}">严格</text>')
    parts.append(f'<rect x="{x0 + 54}" y="{y0 + ph + 26}" width="10" height="10" fill="{C_SEM}"/>')
    parts.append(f'<text x="{x0 + 68}" y="{y0 + ph + 35}" font-size="10" fill="{MUTED}">宽松</text>')

    # ---- 右:延迟 ----
    rx, rw = 440, 340
    parts.append(f'<text x="{rx}" y="{y0 - 8}" font-size="12" fill="{MUTED}">延迟(ms)</text>')
    vmax = max(st["p90"] for st in data.values()) * 1.2
    for g in (0, 0.5, 1.0):
        y = y0 + ph - ph * g
        parts.append(f'<line x1="{rx}" y1="{y:.1f}" x2="{rx + rw}" y2="{y:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{rx - 8}" y="{y + 4:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">{int(vmax * g)}</text>')
    slot2 = rw / len(data)
    for i, (cfg, st) in enumerate(data.items()):
        for j, (val, color) in enumerate(((st["p50"], C_P50), (st["p90"], C_P90))):
            bw = slot2 * 0.30
            bx = rx + slot2 * i + slot2 * 0.12 + j * (bw + 6)
            bh = ph * val / vmax
            parts.append(f'<rect x="{bx:.1f}" y="{y0 + ph - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" rx="2"/>')
            parts.append(f'<text x="{bx + bw / 2:.1f}" y="{y0 + ph - bh - 4:.1f}" font-size="9" fill="{INK}" text-anchor="middle">{val / 1000:.1f}s</text>')
        parts.append(f'<text x="{rx + slot2 * i + slot2 / 2:.1f}" y="{y0 + ph + 16}" font-size="10" fill="{INK}" text-anchor="middle">{esc(cfg)}</text>')
    parts.append(f'<rect x="{rx}" y="{y0 + ph + 26}" width="10" height="10" fill="{C_P50}"/>')
    parts.append(f'<text x="{rx + 14}" y="{y0 + ph + 35}" font-size="10" fill="{MUTED}">p50</text>')
    parts.append(f'<rect x="{rx + 54}" y="{y0 + ph + 26}" width="10" height="10" fill="{C_P90}"/>')
    parts.append(f'<text x="{rx + 68}" y="{y0 + ph + 35}" font-size="10" fill="{MUTED}">p90</text>')
    parts.append("</svg>")

    out = ROOT / "eval" / "overview.svg"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"写入 {out}")
    for cfg, st in data.items():
        print(f"  {cfg}: 严格 {st['strict']:.1f}% 宽松 {st['sem']:.1f}% p50 {st['p50']:.0f} p90 {st['p90']:.0f}")


if __name__ == "__main__":
    main()