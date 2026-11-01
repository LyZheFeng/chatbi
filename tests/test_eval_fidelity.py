"""解读忠实性校验单测:模板产出的解读必须 0 违规,伪造数字必须被抓。"""

from __future__ import annotations

from app.charts import build_chart
from eval.fidelity import allowed_numbers, check_reading, extract_numbers


def _reading(question, cols, rows):
    spec, reading = build_chart(question, cols, rows)
    assert spec is not None and reading
    mark = spec.get("mark", {}).get("type") if isinstance(spec.get("mark"), dict) else spec.get("mark")
    if mark is None and spec.get("layer"):
        mark = spec["layer"][0]["mark"]["type"]
    return reading, mark


def test_extract_numbers_drops_dates_and_keeps_percent():
    nums = extract_numbers("共 12 期(2014-01~2014-12),上升 29.2%,峰值 455,363.92")
    assert 12 in nums and 29.2 in nums and 455363.92 in nums
    assert 2014 not in nums and 1 not in nums  # 日期标签被遮掉


def test_bar_reading_is_faithful():
    cols = ["market", "total_sales"]
    rows = [["Europe", 503568.21], ["Asia Pacific", 797866.37], ["Africa", 115205.93]]
    reading, mark = _reading("各市场销售额", cols, rows)
    assert check_reading(reading, cols, rows, mark) == []


def test_line_reading_is_faithful():
    cols = ["月份", "sales"]
    rows = [["2014-01", 100.0], ["2014-02", 220.0], ["2014-03", 180.0]]
    reading, mark = _reading("按月销售额趋势", cols, rows)
    assert check_reading(reading, cols, rows, mark) == []


def test_pie_reading_is_faithful():
    cols = ["market", "sales"]
    rows = [["Asia Pacific", 797866.37], ["Europe", 503568.21], ["LATAM", 231207.8]]
    reading, mark = _reading("各市场销售额占比", cols, rows)
    assert "图内合计" in reading
    assert check_reading(reading, cols, rows, mark) == []


def test_scatter_reading_is_faithful():
    cols = ["discount", "profit"]
    rows = [[0.1, 50.0], [0.2, 30.0], [0.3, 80.0], [0.4, 90.0]]
    reading, mark = _reading("折扣和利润的关系", cols, rows)
    assert "r=" in reading
    assert check_reading(reading, cols, rows, mark) == []


def test_fabricated_number_is_flagged():
    cols = ["market", "total_sales"]
    rows = [["Europe", 503568.21], ["Asia Pacific", 797866.37], ["Africa", 115205.93]]
    reading = "3 项中最高是 Asia Pacific(797,866.37),其次 Europe(503,568.21),最低 Africa(115,205.93),最高约为最低的 6.9 倍(凭空多出 12,345.67)。"
    bad = check_reading(reading, cols, rows, "bar")
    assert bad == [12345.67]


def test_dimension_labels_with_digits_are_masked():
    cols = ["customer_id", "total_sales"]
    rows = [["AB-101051402", 12181.6], ["CA-1277558", 9298.98], ["FH-1436582", 8999.06]]
    reading = "3 项中最高是 AB-101051402(12,181.60),其次 CA-1277558(9,298.98),最低 FH-1436582(8,999.06)。"
    assert check_reading(reading, cols, rows, "bar") == []


def test_allowed_numbers_include_share_and_total():
    cols = ["market", "sales"]
    rows = [["A", 60.0], ["B", 40.0]]
    allowed = allowed_numbers(cols, rows, "arc")
    assert 60.0 in allowed and 100.0 in allowed  # 合计与占比
    assert 2.0 in allowed  # 行数计数