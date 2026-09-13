"""评估问题集(Day 17-18 建 25 题;Day 21 扩到 50 题:脏数据/聚合边界/图表问法/更多枚举与多表)。

每题:question(用户中文提问)+ gold(标准答案 SQL,本地执行得期望表格)。
判定:agent 最终表格与 gold 表格在"值集合"层面一致(浮点圆整 2 位、行序无关、列子集投影)。
tags 里 枚举陷阱/脏数据/空结果 类问题最可能触发自愈路径。
"""

from __future__ import annotations

QUESTIONS: list[dict] = [
    dict(id="q01", tags="单表/计数", question="订单明细一共有多少行?",
         gold="SELECT COUNT(*) FROM order_items"),
    dict(id="q02", tags="单表/计数", question="数据库里一共有多少个客户?",
         gold="SELECT COUNT(*) FROM customers"),
    dict(id="q03", tags="单表/时间", question="2014 年一共下了多少张订单?",
         gold="SELECT COUNT(*) FROM orders WHERE order_date >= '2014-01-01' AND order_date < '2015-01-01'"),
    dict(id="q04", tags="多表/聚合/排序", question="2014 年销售额最高的 5 个国家是哪些?",
         gold="SELECT c.country, SUM(i.sales) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "WHERE o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' "
              "GROUP BY c.country ORDER BY 2 DESC LIMIT 5"),
    dict(id="q05", tags="多表/聚合", question="三个商品大类各自的销售额和总利润是多少?",
         gold="SELECT p.category, SUM(i.sales), SUM(i.profit) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.category"),
    dict(id="q06", tags="多表/聚合/时间/枚举陷阱", question="亚太市场按月的销售额趋势是怎样的?",
         gold="SELECT strftime('%Y-%m', o.order_date), SUM(i.sales) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region "
              "WHERE g.market = 'Asia Pacific' GROUP BY 1 ORDER BY 1"),
    dict(id="q07", tags="单表/过滤", question="Consumer 类型的客户有多少个?",
         gold="SELECT COUNT(*) FROM customers WHERE segment = 'Consumer'"),
    dict(id="q08", tags="多表/聚合/排序", question="平均折扣最高的 3 个商品子类是哪些?",
         gold="SELECT p.sub_category, AVG(i.discount) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id "
              "GROUP BY p.sub_category ORDER BY 2 DESC LIMIT 3"),
    dict(id="q09", tags="单表/过滤", question="利润为负的亏损明细有多少行?",
         gold="SELECT COUNT(*) FROM order_items WHERE profit < 0"),
    dict(id="q10", tags="单表/排序", question="运费最高的 5 行明细,列出行号和运费。",
         gold="SELECT row_id, shipping_cost FROM order_items ORDER BY shipping_cost DESC, row_id LIMIT 5"),
    dict(id="q11", tags="多表/过滤", question="美国的客户有多少个?",
         gold="SELECT COUNT(*) FROM customers WHERE country = 'United States'"),
    dict(id="q12", tags="多表/聚合/时间", question="2013 年 12 月的总销售额是多少?",
         gold="SELECT SUM(i.sales) FROM order_items i JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2013-12-01' AND o.order_date < '2014-01-01'"),
    dict(id="q13", tags="多表/聚合/排序", question="下单次数最多的 3 个客户,列出客户编号和订单数。",
         gold="SELECT c.customer_id, COUNT(DISTINCT o.order_id) FROM orders o "
              "JOIN customers c ON c.customer_id = o.customer_id "
              "GROUP BY c.customer_id ORDER BY 2 DESC, c.customer_id LIMIT 3"),
    dict(id="q14", tags="多表/聚合", question="Technology 大类平均每行明细的销售额是多少?",
         gold="SELECT AVG(i.sales) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id WHERE p.category = 'Technology'"),
    dict(id="q15", tags="单表/过滤", question="折扣不低于 0.3 的明细有多少行?",
         gold="SELECT COUNT(*) FROM order_items WHERE discount >= 0.3"),
    dict(id="q16", tags="单表/聚合", question="每种配送方式各有多少张订单?",
         gold="SELECT ship_mode, COUNT(*) FROM orders GROUP BY ship_mode"),
    dict(id="q17", tags="单表/脏数据", question="数量小于等于 0 的异常明细有哪些行号?",
         gold="SELECT row_id FROM order_items WHERE quantity <= 0"),
    dict(id="q18", tags="多表/聚合", question="各市场的总利润分别是多少?",
         gold="SELECT g.market, SUM(i.profit) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region GROUP BY g.market"),
    dict(id="q19", tags="多表/时间/枚举陷阱/空结果", question="2013 年 3 月亚太市场有多少订单?",
         gold="SELECT COUNT(DISTINCT o.order_id) FROM orders o "
              "JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region "
              "WHERE g.market = 'Asia Pacific' AND o.order_date >= '2013-03-01' AND o.order_date < '2013-04-01'"),
    # ---- Day 17-18 追加:方言陷阱与高难度题(诱导 MySQL 方言/嵌套聚合,触发自愈路径)----
    dict(id="q20", tags="时间/方言陷阱", question="2014 年每个季度的销售额分别是多少?",
         gold="SELECT (CAST(strftime('%m', o.order_date) AS INTEGER) - 1) / 3 + 1, SUM(i.sales) "
              "FROM order_items i JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' GROUP BY 1"),
    dict(id="q21", tags="时间/聚合/方言陷阱", question="2013 和 2014 两年各自的总销售额是多少?",
         gold="SELECT strftime('%Y', o.order_date), SUM(i.sales) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2013-01-01' AND o.order_date < '2015-01-01' GROUP BY 1"),
    dict(id="q22", tags="多表/聚合/排序", question="利润率(总利润除以总销售额)最高的 3 个商品子类是哪些?",
         gold="SELECT p.sub_category, SUM(i.profit) * 1.0 / SUM(i.sales) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.sub_category "
              "HAVING SUM(i.sales) > 0 ORDER BY 2 DESC LIMIT 3"),
    dict(id="q23", tags="多表/聚合/排序", question="哪个商品子类的利润率(总利润除以总销售额)最低?",
         gold="SELECT p.sub_category, SUM(i.profit) * 1.0 / SUM(i.sales) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.sub_category "
              "HAVING SUM(i.sales) > 0 ORDER BY 2 ASC LIMIT 1"),
    dict(id="q24", tags="多表/嵌套聚合", question="Corporate 客户在 2014 年下了多少张订单,平均每张订单金额是多少?",
         gold="SELECT COUNT(*), AVG(t.amt) FROM (SELECT o.order_id, SUM(i.sales) AS amt "
              "FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN order_items i ON i.order_id = o.order_id "
              "WHERE c.segment = 'Corporate' AND o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' "
              "GROUP BY o.order_id) t"),
    dict(id="q25", tags="聚合/方言陷阱", question="所有明细的销售额中位数是多少?",
         gold="SELECT AVG(sales) FROM (SELECT sales FROM order_items WHERE sales IS NOT NULL ORDER BY sales "
              "LIMIT 2 - (SELECT COUNT(*) FROM order_items WHERE sales IS NOT NULL) % 2 "
              "OFFSET (SELECT (COUNT(*) - 1) / 2 FROM order_items WHERE sales IS NOT NULL))"),
    # ---- Day 21 追加:脏数据明细 / 聚合边界 / 图表问法 / 更多枚举与多表(q26~q50)----
    dict(id="q26", tags="单表/聚合", question="每种订单优先级各有多少张订单?",
         gold="SELECT order_priority, COUNT(*) FROM orders GROUP BY order_priority"),
    dict(id="q27", tags="多表/聚合/排序", question="总利润最高的 5 个商品子类是哪些?",
         gold="SELECT p.sub_category, SUM(i.profit) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.sub_category "
              "ORDER BY 2 DESC, p.sub_category LIMIT 5"),
    dict(id="q28", tags="多表/时间/聚合", question="2015 年 7 月到 12 月的总销售额是多少?",
         gold="SELECT SUM(i.sales) FROM order_items i JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2015-07-01' AND o.order_date < '2016-01-01'"),
    dict(id="q29", tags="多表/聚合/枚举陷阱", question="First Class 配送方式的平均运费是多少?",
         gold="SELECT AVG(i.shipping_cost) FROM order_items i JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.ship_mode = 'First Class'"),
    dict(id="q30", tags="单表/脏数据", question="销售额缺失(sales 为空)的明细有哪些行号?",
         gold="SELECT row_id FROM order_items WHERE sales IS NULL"),
    dict(id="q31", tags="单表/脏数据", question="哪些订单的发货日期早于下单日期?列出订单号。",
         gold="SELECT order_id FROM orders WHERE ship_date < order_date"),
    dict(id="q32", tags="单表/脏数据", question="region 为空的客户有哪些客户编号?",
         gold="SELECT customer_id FROM customers WHERE region IS NULL"),
    dict(id="q33", tags="单表/脏数据/聚合", question="剔除数量为 0 或负数、销售额为空的异常明细后,总销售额是多少?",
         gold="SELECT SUM(sales) FROM order_items WHERE quantity > 0 AND sales IS NOT NULL"),
    dict(id="q34", tags="单表/聚合", question="每种客户类型(segment)各有多少个客户?",
         gold="SELECT segment, COUNT(*) FROM customers GROUP BY segment"),
    dict(id="q35", tags="多表/聚合", question="各市场分别有多少个客户?",
         gold="SELECT g.market, COUNT(*) FROM customers c "
              "JOIN geography g ON c.country = g.country AND c.region = g.region GROUP BY g.market"),
    dict(id="q36", tags="单表/时间/聚合", question="2012 年每个月各有多少张订单?",
         gold="SELECT strftime('%Y-%m', order_date), COUNT(*) FROM orders "
              "WHERE order_date >= '2012-01-01' AND order_date < '2013-01-01' GROUP BY 1 ORDER BY 1"),
    dict(id="q37", tags="单表/排序", question="销售额最高的 5 行明细,列出行号和销售额。",
         gold="SELECT row_id, sales FROM order_items ORDER BY sales DESC, row_id LIMIT 5"),
    dict(id="q38", tags="单表/聚合/排序", question="客户数量最多的 5 个国家是哪些?",
         gold="SELECT country, COUNT(*) FROM customers GROUP BY country ORDER BY 2 DESC, country LIMIT 5"),
    dict(id="q39", tags="多表/聚合/图表", question="三个商品大类各有多少张订单(按订单号去重)?",
         gold="SELECT p.category, COUNT(DISTINCT o.order_id) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id JOIN orders o ON i.order_id = o.order_id "
              "GROUP BY p.category"),
    dict(id="q40", tags="多表/时间/聚合/图表", question="2014 年按月的利润趋势是怎样的?",
         gold="SELECT strftime('%Y-%m', o.order_date), SUM(i.profit) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' GROUP BY 1 ORDER BY 1"),
    dict(id="q41", tags="多表/聚合/图表", question="按配送方式统计总销售额。",
         gold="SELECT o.ship_mode, SUM(i.sales) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id GROUP BY o.ship_mode"),
    dict(id="q42", tags="聚合边界/空结果", question="没有任何商品明细的订单有几张?",
         gold="SELECT COUNT(*) FROM orders o LEFT JOIN order_items i ON i.order_id = o.order_id "
              "WHERE i.row_id IS NULL"),
    dict(id="q43", tags="单表/过滤", question="折扣正好为 0 的明细有多少行?",
         gold="SELECT COUNT(*) FROM order_items WHERE discount = 0"),
    dict(id="q44", tags="单表/时间/边界", question="库里最早和最晚的订单日期分别是哪天?",
         gold="SELECT MIN(order_date), MAX(order_date) FROM orders"),
    dict(id="q45", tags="多表/聚合/排序", question="累计消费总额最高的 3 个客户,列出客户编号和消费总额。",
         gold="SELECT c.customer_id, SUM(i.sales) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "GROUP BY c.customer_id ORDER BY 2 DESC, c.customer_id LIMIT 3"),
    dict(id="q46", tags="多表/聚合", question="各国家的总利润分别是多少?",
         gold="SELECT c.country, SUM(i.profit) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "GROUP BY c.country"),
    dict(id="q47", tags="多表/聚合/排序", question="利润率(总利润除以总销售额)最高的市场是哪个?",
         gold="SELECT g.market, SUM(i.profit) * 1.0 / SUM(i.sales) FROM order_items i "
              "JOIN orders o ON i.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region GROUP BY g.market "
              "HAVING SUM(i.sales) > 0 ORDER BY 2 DESC LIMIT 1"),
    dict(id="q48", tags="多表/时间/聚合", question="Technology 大类 2014 年的总销售额是多少?",
         gold="SELECT SUM(i.sales) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id JOIN orders o ON i.order_id = o.order_id "
              "WHERE p.category = 'Technology' AND o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01'"),
    dict(id="q49", tags="多表/聚合", question="平均利润为负的商品子类有哪些?列出子类和平均利润。",
         gold="SELECT p.sub_category, AVG(i.profit) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.sub_category "
              "HAVING AVG(i.profit) < 0"),
    dict(id="q50", tags="多表/时间/聚合/排序", question="2014 年总利润为负(亏损)的商品子类,按亏损金额从小到大列出子类和总利润。",
         gold="SELECT p.sub_category, SUM(i.profit) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' GROUP BY p.sub_category "
              "HAVING SUM(i.profit) < 0 ORDER BY 2 ASC"),
]
