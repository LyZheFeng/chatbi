"""评估问题集(Day 17-18 自愈对比用,Day 21 扩到 50 题并细化难度标签)。

每题:question(用户中文提问)+ gold_sql(标准答案 SQL,本地执行得期望表格)。
判定:agent 最终表格与 gold 表格在"值集合"层面一致(浮点圆整 4 位、行序无关)。
tags 里 枚举陷阱/脏数据 类问题最可能触发自愈路径。
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
    dict(id="q22", tags="多表/聚合/排序", question="按商品汇总,利润率(总利润除以总销售额)最高的 5 个商品是哪些?",
         gold="SELECT p.product_id, SUM(i.profit) * 1.0 / SUM(i.sales) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.product_id "
              "HAVING SUM(i.sales) > 0 ORDER BY 2 DESC LIMIT 5"),
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
]
