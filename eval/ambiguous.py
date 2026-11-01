"""评测 2.0 第 3 项:无法回答 / 歧义题(10 道)。

目的:测**优雅降级 / 澄清**,而不是硬编 SQL 糊一个答案。两类题:
- `unanswerable`:库里没有这个字段/表(退货率、满意度、库存、供应商、支付方式);
  合格回答 = 明确说明"数据里没有"或以降级报错说明原因;不合格 = 静默给出一张表(硬编/偷换指标)。
- `ambiguous`:问题缺限定或指标未定义(哪一年、什么算"最好"、增长指哪个指标、平均订单金额口径);
  合格回答 = 先澄清,或明确写出假设口径(如"按 2014 年全期销售额口径");不合格 = 不作任何说明直接给答案。

判定是**规则式**(关键词 + 是否返回表格 + 是否降级),不调 LLM:
- 通过:① 优雅降级(error 非空,带原因);或 ② 文本里明确"缺失/没有/无法"或"假设/口径/请明确"或直接反问;
- 失败:error 为空、给出了结果表,且文本里既没说明缺失也没说明假设(静默硬编)。
关键词判定天然有噪声,所以记录里保留完整 summary,供人工复核;报告里注明这一边界。
"""

from __future__ import annotations

# 说明缺失/无效的表述
MISSING_HINTS = (
    "没有", "无此", "无该", "不存在", "缺少", "缺失", "未包含", "不包含", "查不到", "无法",
    "未提供", "不可用", "不在数据", "未收录", "未记录", "没有该字段", "不涉及",
)
# 澄清/假设口径的表述(含问号:直接反问用户)
CLARIFY_HINTS = (
    "假设", "假定", "默认", "口径", "如果", "请明确", "请补充", "您指", "是指",
    "哪一年", "哪一项", "哪个指标", "?", "？",
)
# 歧义题"说明了自己用了什么指标/范围"的表述(不是硬编,是把解释写清楚)
METRIC_HINTS = (
    "销售额", "销售", "利润", "订单", "客户", "数量", "折扣", "金额", "占比", "利润率", "均值", "总额",
)
SCOPE_HINTS = (
    "全库", "全期", "整体", "全年", "年度", "同比", "环比", "2012", "2013", "2014", "2015",
)

QUESTIONS: list[dict] = [
    dict(id="a01", kind="unanswerable", question="2013 年的退货率是多少?", why="库无退货表/退货字段"),
    dict(id="a02", kind="unanswerable", question="每个客户的满意度评分是多少?", why="库无满意度字段"),
    dict(id="a03", kind="unanswerable", question="2012 年每个月的库存周转率是多少?", why="库无库存表"),
    dict(id="a04", kind="unanswerable", question="各商品的供应商名称和联系方式是什么?", why="库无供应商字段"),
    dict(id="a05", kind="unanswerable", question="订单的平均支付方式是什么?", why="库无支付方式字段"),
    dict(id="b01", kind="ambiguous", question="销售额最高的市场是哪个?", why="缺时间范围/口径(全期?某年?)"),
    dict(id="b02", kind="ambiguous", question="哪个客户最好?", why="'最好'指标未定义(消费额/单量/利润?)"),
    dict(id="b03", kind="ambiguous", question="2014 年的增长情况如何?", why="增长指标未定义(销售额/订单数/利润)"),
    dict(id="b04", kind="ambiguous", question="平均订单金额是多少?", why="口径未定:每单 vs 每明细;含不含脏数据"),
    dict(id="b05", kind="ambiguous", question="各市场表现如何?", why="多指标未指定(销售额/利润/客户数)"),
]


def _hits(text: str, hints: tuple[str, ...]) -> list[str]:
    return [h for h in hints if h in text]


def judge(kind: str, error: str | None, summary: str, row_count: int) -> tuple[bool, str]:
    """规则式判定:返回 (是否通过, 判据)。

    歧义题的关键不是"必须反问",而是**有没有把解释写清楚**:
    给出多指标/整表并说明范围(如"全库/全期/2014 年")同样算透明;只有"裸答案"才算硬编。
    """
    summary = summary or ""
    if error:
        return True, "优雅降级:" + error[:60]
    missing = _hits(summary, MISSING_HINTS)
    clarifying = _hits(summary, CLARIFY_HINTS)
    if kind == "unanswerable":
        if missing:
            return True, "说明缺失:" + "、".join(missing[:3])
        if clarifying:
            return True, "澄清/给出口径:" + "、".join(clarifying[:3])
        return False, "静默给出结果(未说明数据缺失)"
    stated = _hits(summary, METRIC_HINTS) + _hits(summary, SCOPE_HINTS)
    if clarifying:
        return True, "澄清/假设口径:" + "、".join(clarifying[:3])
    if stated:
        return True, "写明指标/范围:" + "、".join(stated[:3])
    if row_count == 0:
        return True, "未产出结果表"
    return False, "静默给出结果(未说明指标/口径/范围)"