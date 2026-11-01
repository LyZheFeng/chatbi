"""解读忠实性校验(评测 2.0 第 2 项):模板化解读里的每个数字都必须能追溯到最终结果表。

不引入新 LLM 调用:解读由 `app/charts.py` 的模板生成,这里做**规则校验**——
把解读文本里的数字抽出来,再从结果表独立重算"允许出现的数字集合"
(单元格、列和、按分组求和、占比、首末变化率、最高/最低比、相关系数、行数/期数),
出现集合外的数字即判违规(模板漂移/写死常量)。

口径边界:
- 只校验"数字从哪来",不校验措辞、因果与统计解释是否合理;
- 日期/期间标签(`2014-01`、`2014Q1`、`2014年`)先遮掉,不当作待校验数字;
- 允许集合里的"计数"覆盖 `0..行数`(解读里的"N 项/期/行/个点"),所以个别小整数可能被合法计数掩盖,
  这是已知的宽松边界(宁可漏报,不制造假阳性)。

用法(离线回放):
    python -X utf8 eval/fidelity.py            # 用 50 题 gold 表跑一遍,应 0 违规
"""

from __future__ import annotations

import re
from statistics import StatisticsError, correlation

_DATE_LIKE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?|\d{4}Q[1-4]|\d{4}年")
_YEAR_LIKE = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def extract_numbers(text: str) -> list[float]:
    """抽数字:去掉日期/期间标签与千分位;百分比按数值抽取(46.72% → 46.72)。"""
    masked = _DATE_LIKE.sub(" ", text)
    out: list[float] = []
    for m in _NUMBER.finditer(masked):
        raw = m.group(0).replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _mask_labels(text: str, columns: list[str], rows: list[list]) -> str:
    """把维度标签(客户号/年份等)遮蔽掉:它们不是"解读里的数字",却含数字。"""
    for j in range(len(columns)):
        for r in rows:
            v = r[j]
            if isinstance(v, str) and len(v) >= 2:
                text = text.replace(v, " ")
    return _YEAR_LIKE.sub(" ", text)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _add(allowed: set[float], v: float) -> None:
    for digits in (0, 1, 2):
        allowed.add(round(float(v), digits))


def allowed_numbers(columns: list[str], rows: list[list], mark: str | None = None) -> set[float]:
    """从最终表格独立重算"解读里可以出现的数字"。"""
    allowed: set[float] = set()
    n = len(rows)
    for i in range(n + 1):  # 计数类:共 N 期/N 项/另有 N 行/0 项为负
        _add(allowed, i)

    measure_cols = [j for j in range(len(columns)) if all(_is_num(r[j]) for r in rows)]

    for j in measure_cols:
        vals = [float(r[j]) for r in rows]
        for v in vals:
            _add(allowed, v)
        total = sum(vals)
        _add(allowed, total)
        for v in vals:  # 占比(饼图)/份额
            if total:
                _add(allowed, v / total * 100)
        if len(vals) >= 2:
            first, last = vals[0], vals[-1]
            if first:
                _add(allowed, (last - first) / abs(first) * 100)  # 趋势变化率
                _add(allowed, (first - last) / abs(last) * 100 if last else 0.0)
            lo, hi = min(vals), max(vals)
            if lo > 0:
                _add(allowed, hi / lo)  # "最高约为最低的 N 倍"
            for a_i, a in enumerate(vals):  # 两项比值(两柱对比)/成对比率
                for b in vals[a_i + 1:]:
                    if b:
                        _add(allowed, a / b)
                    if a:
                        _add(allowed, b / a)
        if len(vals) >= 3:  # 饼图"前三合计 P%"
            top3 = sum(sorted(vals, reverse=True)[:3])
            if total:
                _add(allowed, top3 / total * 100)

    # 按任意一列分组求和(折线多系列"按 X 合计"、按期间的合计与首末变化率)
    for j in range(len(columns)):
        if j in measure_cols:
            continue
        groups: dict[object, list[float]] = {}
        order: list[object] = []
        for r in rows:
            key = r[j]
            groups.setdefault(key, [0.0] * len(measure_cols))
            if key not in order:
                order.append(key)
            for k, m_j in enumerate(measure_cols):
                groups[key][k] += float(r[m_j])
        for sums in groups.values():
            for s in sums:
                _add(allowed, s)
        for k in range(len(measure_cols)):
            series = [groups[key][k] for key in order]
            if len(series) >= 2:
                first, last = series[0], series[-1]
                if first:
                    _add(allowed, (last - first) / abs(first) * 100)
                if last:
                    _add(allowed, (first - last) / abs(last) * 100)

    # 散点相关系数(与 charts.py 同用 statistics.correlation)
    if mark == "point" and len(measure_cols) >= 2:
        xs = [float(r[measure_cols[0]]) for r in rows]
        ys = [float(r[measure_cols[1]]) for r in rows]
        try:
            r = correlation(xs, ys)
        except StatisticsError:
            r = None
        if r is not None:
            _add(allowed, r)
            _add(allowed, abs(r))
    return allowed


def check_reading(reading: str, columns: list[str], rows: list[list], mark: str | None = None) -> list[float]:
    """返回解读文本里"无法追溯到结果表"的数字列表;空列表 = 忠实。"""
    if not reading:
        return []
    allowed = allowed_numbers(columns, rows, mark)
    exact = {round(a, 2) for a in allowed}
    coarse = {round(a, 1) for a in allowed}
    bad: list[float] = []
    for num in extract_numbers(_mask_labels(reading, columns, rows)):
        if round(num, 2) in exact or round(num, 1) in coarse:
            continue
        bad.append(num)
    return bad


def main() -> int:
    """自检:用 50 题 gold 表生成解读并校验,应 0 违规(不需要 LLM/网络)。"""
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from app import db
    from app.charts import build_chart
    from app.config import Settings
    from app.db import connect_ro
    from eval.questions import QUESTIONS

    conn = connect_ro(Settings().db_path)
    bad_total, checked = 0, 0
    for q in QUESTIONS:
        gold = db.run_select(conn, q["gold"], cap=100_000, auto_limit=100_000)
        spec, reading = build_chart(q["question"], gold.columns, gold.rows)
        if not reading:
            continue
        checked += 1
        mark = spec.get("mark", {}).get("type") if isinstance(spec.get("mark"), dict) else spec.get("mark")
        if mark is None and spec.get("layer"):
            mark = spec["layer"][0].get("mark", {}).get("type")
        bad = check_reading(reading, gold.columns, gold.rows, mark)
        if bad:
            bad_total += len(bad)
            print(f"✗ {q['id']} 违规数字 {bad[:8]}:{reading[:80]}")
    print(f"gold 表自检:{checked} 条解读,违规 {bad_total} 个数字")
    return 1 if bad_total else 0


if __name__ == "__main__":
    raise SystemExit(main())