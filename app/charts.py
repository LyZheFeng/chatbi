"""图表自动选型 + 模板化解读(Day 20):最终表格 → chart_spec(Vega-Lite)+ 中文解读。

纪律:
- 输入只有最终表格的 columns/rows 和用户问题——不查库、不问 LLM;
- 图上和解读里的每个数字都来自本地已执行的结果,一个都不新造;
- 选型按列结构确定性判定,同表必同图(可回归测试)。

选型(优先级从上到下,不满足则不画图,表格已足够):
- 时间列(列名 month/月份/quarter/季度… 或值形如 YYYY[-MM[-DD]])+ 1~2 个数值列
  → 折线;恰好是 年+季度/年+月 两列时自动合成 "2014Q1"/"2014-03" 一个横轴;
  另带 ≤8 类的分组列时画多系列;
- 恰 1 个维度列 + 数值列 → 柱状(取前两个数值列分组对比;类数 >12 或标签 >8 字改横条);
  问题含 占比/比例/构成/份额 且首个数值全正、类别 ≤6 → 饼图(只画首个数值列,模型附带的
  pct/比率列不重复入图);
- 恰 2 个数值列、无维度 → 散点;
- 其余(≥2 维度、≥3 数值、行 <2、类 >30)→ 不画。

脏数据呈现约定(与结论同口径,别图表剔了结论没剔):
- 只剔除"画不了"的行(维度或数值为 NULL),剔除行数写进解读;表格仍全量展示;
- 负值/0 是数据本身(SQL 没过滤它们,图表也不过滤),照画并在解读中点名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import StatisticsError, correlation
from typing import Any

_PERIOD_EXACT = {"month", "月份", "月", "quarter", "季度", "week", "周", "day", "日", "date", "日期"}
_YEAR_EXACT = {"year", "年份", "年"}
_QUARTER_NAME = re.compile(r"quarter|季度", re.I)
_MONTH_NAME = re.compile(r"month|月份", re.I)
_ID_LIKE = re.compile(r"(^|_)(id|no|编号|邮编|postal|zip|code)$", re.I)
_DATE_VALUE = re.compile(r"\d{4}(-\d{2}){0,2}")
_TEXT = "#262730"  # 图表文字钉死的深灰(白底可读,不随 UI 主题漂移)


@dataclass
class _Col:
    i: int
    name: str
    kind: str  # period | year | num | cat


# ---------- 列分类 ----------


def _classify(columns: list[str], rows: list[list[Any]]) -> list[_Col]:
    cols = []
    for i, name in enumerate(columns):
        vals = [r[i] for r in rows]
        cols.append(_Col(i, name, _kind(name, vals)))
    return cols


def _kind(name: str, vals: list[Any]) -> str:
    n = name.strip().lower()
    non_null = [v for v in vals if v is not None]
    if n in _PERIOD_EXACT or n.endswith(("_date", "日期")):
        return "period"
    if n in _YEAR_EXACT:
        return "year"
    if non_null and all(isinstance(v, str) and _DATE_VALUE.fullmatch(v) for v in non_null):
        return "period"
    if non_null and all(_is_num(v) for v in non_null):
        return "cat" if _ID_LIKE.search(n) else "num"
    return "cat"


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------- 对外入口 ----------


def build_chart(
    question: str, columns: list[str], rows: list[list[Any]]
) -> tuple[dict[str, Any] | None, str]:
    """最终表格 → (Vega-Lite chart_spec | None, 中文解读)。不适合画图时返回 (None, "")。"""
    if len(rows) < 2 or len(columns) < 2 or len(set(columns)) != len(columns):
        return None, ""
    plan = _select(question, _classify(columns, rows), rows)
    if plan is None:
        return None, ""
    return _spec(question, plan), _reading(plan)


# ---------- 选型 ----------


def _select(question: str, cols: list[_Col], rows: list[list[Any]]) -> dict | None:
    nums = [c for c in cols if c.kind == "num"]
    cats = [c for c in cols if c.kind == "cat"]
    periods = [c for c in cols if c.kind in ("period", "year")]

    if not nums:
        return None
    if periods and len(nums) == 1 and len(cats) == 1:
        return _plan_line(rows, periods, nums[0], group=cats[0])
    if periods and len(nums) <= 2 and not cats:
        return _plan_line(rows, periods, nums[0], measures=nums, group=None)
    if not periods and len(cats) == 1 and len(rows) <= 30:
        return _plan_bar(question, rows, cat=cats[0], nums=nums[:2])
    if not periods and not cats and len(nums) == 2:
        return _plan_scatter(rows, nums[0], nums[1])
    return None


def _dim_labels(periods: list[_Col], rows: list[list[Any]]) -> tuple[str, list, list] | None:
    """把时间列整理成 (横轴列名, 每行标签, 每行排序键)。标签为 None 的行随后被剔除。

    年+季度 / 年+月 两列合成一个标签("2014Q1"/"2014-03"),其余多时间列组合不画。
    """
    if len(periods) == 1:
        c = periods[0]
        raw = [r[c.i] for r in rows]
        if all(_is_num(v) for v in raw if v is not None):
            return c.name, [None if v is None else str(int(v)) for v in raw], raw
        return c.name, [None if v is None else str(v) for v in raw], raw
    if len(periods) == 2:
        years = [c for c in periods if c.kind == "year" or all(_is_num(v) and 1900 <= v <= 2100 for v in (r[c.i] for r in rows) if v is not None)]
        if len(years) != 1:
            return None
        ycol = years[0]
        pcol = next((c for c in periods if c is not ycol), None)
        if pcol is None:
            return None
        labels, keys = [], []
        for r in rows:
            y, p = r[ycol.i], r[pcol.i]
            if y is None or p is None or not _is_num(p):
                labels.append(None)
                keys.append(None)
                continue
            if _QUARTER_NAME.search(pcol.name) or (not _MONTH_NAME.search(pcol.name) and all(0 < (r[pcol.i] or 0) <= 4 for r in rows)):
                labels.append(f"{int(y)}Q{int(p)}")
            else:
                labels.append(f"{int(y)}-{int(p):02d}")
            keys.append((int(y), int(p)))
        name = f"{ycol.name}×{pcol.name}"
        return name, labels, keys
    return None


def _plan_line(
    rows: list[list[Any]], periods: list[_Col], m0: _Col,
    *, measures: list[_Col] | None = None, group: _Col | None = None,
) -> dict | None:
    measures = measures if measures is not None else [m0]
    dim = _dim_labels(periods, rows)
    if dim is None:
        return None
    dim_name, labels, keys = dim
    data, excluded = [], 0
    for r, label, key in zip(rows, labels, keys):
        if label is None or (group is not None and r[group.i] is None) or any(
            not _is_num(r[m.i]) for m in measures
        ):
            excluded += 1
            continue
        rec: dict[str, Any] = {dim_name: label}
        for m in measures:
            rec[m.name] = r[m.i]
        if group is not None:
            rec[group.name] = r[group.i]
        data.append((key, rec))
    if len(data) < 2:
        return None
    try:
        data.sort(key=lambda t: t[0])
    except TypeError:
        return None  # 排序键类型混杂(如数字与字符串混列),时间轴不可信,不画
    values = [rec for _, rec in data]
    if group is not None and len({rec[group.name] for rec in values}) > 8:
        return None
    return {
        "type": "multiline" if group is not None else "line",
        "dim": dim_name, "group": group.name if group else None,
        "measures": [m.name for m in measures], "values": values, "excluded": excluded,
    }


def _plan_bar(question: str, rows: list[list[Any]], *, cat: _Col, nums: list[_Col]) -> dict | None:
    data, excluded = [], 0
    for r in rows:
        d, ms = r[cat.i], [r[m.i] for m in nums]
        if d is None or any(not _is_num(v) for v in ms):
            excluded += 1
            continue
        rec = {cat.name: str(d)}
        for m, v in zip(nums, ms):
            rec[m.name] = v
        data.append(rec)
    if len(data) < 2:
        return None
    m0 = nums[0].name
    data.sort(key=lambda rec: rec[m0], reverse=True)  # 柱状从大到小;横条渲染时再反转
    n, max_label = len(data), max(len(rec[cat.name]) for rec in data)
    values = list(data)
    pie = bool(re.search(r"占比|比例|构成|份额|百分", question)) and len(data) <= 6 and all(
        rec[m0] > 0 for rec in data
    )
    chart_type = "pie" if pie else ("hbar" if n > 12 or max_label > 8 else "bar")
    if chart_type == "hbar":
        values = list(reversed(values))  # 横条 y 轴自下而上,反转后最大值在最上
    return {
        "type": chart_type, "dim": cat.name, "group": None,
        "measures": [nums[0].name] if pie else [m.name for m in nums], "values": values,
        "excluded": excluded,
    }


def _plan_scatter(rows: list[list[Any]], x: _Col, y: _Col) -> dict | None:
    pts, excluded = [], 0
    for r in rows:
        xv, yv = r[x.i], r[y.i]
        if not _is_num(xv) or not _is_num(yv):
            excluded += 1
            continue
        pts.append({x.name: xv, y.name: yv})
    if len(pts) < 2:
        return None
    return {
        "type": "scatter", "dim": None, "group": None,
        "measures": [x.name, y.name], "values": pts, "excluded": excluded,
    }


# ---------- Vega-Lite spec ----------


def _spec(question: str, p: dict) -> dict[str, Any]:
    # 自带浅色画布 + 钉死的深色文字:深色 UI 下 Streamlit 的 vega 主题会把标题/轴文字
    # 渲染成浅色,叠在白底上就看不清——文字颜色不交给主题,前端怎么嵌都可读
    s: dict[str, Any] = {
        "title": question if len(question) <= 34 else question[:33] + "…",
        "data": {"values": p["values"]},
        "config": {
            "background": "white",
            "title": {"color": _TEXT},
            "axis": {"labelColor": _TEXT, "titleColor": _TEXT, "gridColor": "#e6e8eb",
                     "domainColor": "#c8ccd0", "tickColor": "#c8ccd0"},
            "legend": {"labelColor": _TEXT, "titleColor": _TEXT},
        },
    }
    t, dim, ms = p["type"], p["dim"], p["measures"]
    if t in ("line", "multiline"):
        s["mark"] = {"type": "line", "point": True}
        s["height"] = 320
        enc: dict[str, Any] = {
            "x": {"field": dim, "type": "ordinal", "sort": None,
                  "axis": {"labelAngle": -45 if len(p["values"]) > 12 else 0}},
        }
        if t == "multiline":
            g = p["group"]
            enc["y"] = {"field": ms[0], "type": "quantitative"}
            enc["color"] = {"field": g, "type": "nominal", "title": None}
            enc["tooltip"] = [{"field": dim, "type": "nominal"}, {"field": g, "type": "nominal"},
                              {"field": ms[0], "type": "quantitative"}]
        elif len(ms) == 2:
            s["transform"] = [{"fold": ms, "as": ["指标", "值"]}]
            enc["y"] = {"field": "值", "type": "quantitative", "title": None}
            enc["color"] = {"field": "指标", "type": "nominal", "title": None}
            enc["tooltip"] = [{"field": dim, "type": "nominal"}, {"field": "指标", "type": "nominal"},
                              {"field": "值", "type": "quantitative"}]
        else:
            enc["y"] = {"field": ms[0], "type": "quantitative"}
            enc["tooltip"] = [{"field": dim, "type": "nominal"}, {"field": ms[0], "type": "quantitative"}]
        s["encoding"] = enc
    elif t in ("bar", "hbar"):
        s["mark"] = {"type": "bar"}
        cat_enc = {"field": dim, "type": "nominal", "sort": None}
        if t == "hbar":
            s["height"] = min(480, max(200, 26 * len(p["values"])))
            s["encoding"] = {
                "y": cat_enc,
                "x": ({"field": ms[0], "type": "quantitative"} if len(ms) == 1 else
                      {"field": "值", "type": "quantitative", "title": None}),
                "color": None if len(ms) == 1 else {"field": "指标", "type": "nominal", "title": None},
                "yOffset": None if len(ms) == 1 else {"field": "指标"},
                "tooltip": None,  # 占位,下面统一覆盖
            }
        else:
            s["height"] = 300
            s["encoding"] = {
                "x": cat_enc,
                "y": ({"field": ms[0], "type": "quantitative"} if len(ms) == 1 else
                      {"field": "值", "type": "quantitative", "title": None}),
                "color": None if len(ms) == 1 else {"field": "指标", "type": "nominal", "title": None},
                "xOffset": None if len(ms) == 1 else {"field": "指标"},
                "tooltip": None,
            }
        tip = [{"field": dim, "type": "nominal"}]
        if len(ms) == 1:
            tip.append({"field": ms[0], "type": "quantitative"})
        else:
            s["transform"] = [{"fold": ms, "as": ["指标", "值"]}]
            tip += [{"field": "指标", "type": "nominal"}, {"field": "值", "type": "quantitative"}]
        s["encoding"]["tooltip"] = tip
        s["encoding"] = {k: v for k, v in s["encoding"].items() if v is not None}
    elif t == "pie":
        s["mark"] = {"type": "arc"}
        s["height"] = 300
        s["encoding"] = {
            "theta": {"field": ms[0], "type": "quantitative"},
            "color": {"field": dim, "type": "nominal", "title": None},
            "tooltip": [{"field": dim, "type": "nominal"}, {"field": ms[0], "type": "quantitative"}],
        }
    else:  # scatter
        s["mark"] = {"type": "point", "filled": True, "opacity": 0.7}
        s["height"] = 320
        s["encoding"] = {
            "x": {"field": ms[0], "type": "quantitative", "scale": {"zero": False}},
            "y": {"field": ms[1], "type": "quantitative", "scale": {"zero": False}},
            "tooltip": [{"field": ms[0], "type": "quantitative"}, {"field": ms[1], "type": "quantitative"}],
        }
    return s


# ---------- 模板化解读(数字一律来自 values,即本地已执行结果) ----------


def _fmt(v: float | int) -> str:
    if isinstance(v, float) and v != int(v):
        return f"{v:,.2f}"
    return f"{int(v):,}"


def _trend(a: float, b: float) -> str:
    """首末两期的方向描述。"""
    if a == 0:
        return f"{_fmt(a)} → {_fmt(b)}" + ("(持平)" if a == b else "")
    pct = (b - a) / abs(a) * 100
    if abs(pct) < 1:
        return f"{_fmt(a)} → {_fmt(b)},整体基本持平"
    if pct > 0:
        return f"{_fmt(a)} → {_fmt(b)},整体上升 {pct:.1f}%"
    return f"{_fmt(a)} → {_fmt(b)},整体下降 {abs(pct):.1f}%"


def _peak(vals: list[dict], field: str, dim: str) -> tuple[str, float, str, float]:
    hi = max(vals, key=lambda r: r[field])
    lo = min(vals, key=lambda r: r[field])
    return hi[dim], hi[field], lo[dim], lo[field]


def _reading(p: dict) -> str:
    t, dim, ms, vals, excluded = p["type"], p["dim"], p["measures"], p["values"], p["excluded"]
    m0 = ms[0]
    parts: list[str] = []

    if t in ("line", "multiline"):
        if t == "multiline":
            g = p["group"]
            totals: dict[str, float] = {}
            for rec in vals:  # vals 已按时间排序,直接累加保序
                totals[rec[dim]] = totals.get(rec[dim], 0) + rec[m0]
            peak = max(vals, key=lambda r: r[m0])
            by_group: dict[str, float] = {}
            for rec in vals:
                by_group[rec[g]] = by_group.get(rec[g], 0) + rec[m0]
            top_g, top_v = max(by_group.items(), key=lambda kv: kv[1])
            parts.append(
                f"共 {len(totals)} 期({vals[0][dim]}~{vals[-1][dim]}),按 {m0} 合计:"
                f"{_trend(totals[vals[0][dim]], totals[vals[-1][dim]])};"
                f"全程峰值在第 {peak[dim]} 期的 {peak[g]}({_fmt(peak[m0])});累计最高的是 {top_g}({_fmt(top_v)})。"
            )
        else:
            parts.append(f"共 {len(vals)} 期({vals[0][dim]}~{vals[-1][dim]});")
            for m in ms:
                first, last = vals[0], vals[-1]  # values 已按时间排序
                hd, hv, ld, lv = _peak(vals, m, dim)
                parts.append(
                    f"{m}:{_trend(first[m], last[m])};峰值在第 {hd} 期({_fmt(hv)}),低点在第 {ld} 期({_fmt(lv)})。"
                )

    elif t in ("bar", "hbar"):
        ordered = sorted(vals, key=lambda r: r[m0], reverse=True)
        neg = sum(1 for rec in ordered if rec[m0] < 0)
        if len(ordered) == 2:
            a, b = ordered
            ratio = f",约 {a[m0] / b[m0]:.1f} 倍" if b[m0] > 0 else ""
            parts.append(f"{a[dim]}({_fmt(a[m0])})高于 {b[dim]}({_fmt(b[m0])}{ratio})。")
        else:
            top, second, low = ordered[0], ordered[1], ordered[-1]
            ratio = f",最高约为最低的 {top[m0] / low[m0]:.1f} 倍" if low[m0] > 0 else ""
            parts.append(
                f"{len(ordered)} 项中最高是 {top[dim]}({_fmt(top[m0])}),其次 {second[dim]}({_fmt(second[m0])}),"
                f"最低 {low[dim]}({_fmt(low[m0])}){ratio}。"
            )
        if len(ms) == 2:
            m1 = ms[1]
            best = max(vals, key=lambda r: r[m1])
            parts.append(f"按 {m1} 计,最高是 {best[dim]}({_fmt(best[m1])})。")
        if neg:
            parts.append(f"其中有 {neg} 项为负值,如实画出。")

    elif t == "pie":
        total = sum(rec[m0] for rec in vals)
        ordered = sorted(vals, key=lambda r: r[m0], reverse=True)
        top = ordered[0]
        seg = (f"{len(ordered)} 类图内合计 {_fmt(total)}:{top[dim]} 占比最大 {top[m0] / total * 100:.1f}%"
               f"({_fmt(top[m0])})")
        if len(ordered) >= 3:
            top3 = sum(rec[m0] for rec in ordered[:3]) / total * 100
            seg += f",前三合计 {top3:.1f}%"
        parts.append(seg + "。")

    else:  # scatter
        xs = [rec[ms[0]] for rec in vals]
        ys = [rec[ms[1]] for rec in vals]
        seg = (f"{len(vals)} 个点:{ms[0]} 取 {_fmt(min(xs))}~{_fmt(max(xs))},{ms[1]} 取 {_fmt(min(ys))}~{_fmt(max(ys))}")
        try:
            r = correlation(xs, ys)
            if r >= 0.3:
                seg += f";{ms[1]} 随 {ms[0]} 增大整体上升"
            elif r <= -0.3:
                seg += f";{ms[1]} 随 {ms[0]} 增大整体下降"
            else:
                seg += ";两者无明显线性关系"
            seg += f"(r={r:.2f})"
        except StatisticsError:
            pass
        parts.append(seg + "。")

    if excluded:
        parts.append(f"另有 {excluded} 行因字段缺失未画入,表格中仍可见。")
    return "".join(parts)
