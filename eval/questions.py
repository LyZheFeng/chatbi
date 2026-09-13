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
         gold="SELECT c.country, ROUND(SUM(i.sales),2) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "WHERE o.order_date >= '2014-01-01' AND o.order_date < '2015-01-01' "
              "GROUP BY c.country ORDER BY 2 DESC LIMIT 5"),
    dict(id="q05", tags="多表/聚合", question="三个商品大类各自的销售额和总利润是多少?",
         gold="SELECT p.category, ROUND(SUM(i.sales),2), ROUND(SUM(i.profit),2) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id GROUP BY p.category"),
    dict(id="q06", tags="多表/聚合/时间/枚举陷阱", question="亚太市场按月的销售额趋势是怎样的?",
         gold="SELECT strftime('%Y-%m', o.order_date), ROUND(SUM(i.sales),2) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region "
              "WHERE g.market = 'Asia Pacific' GROUP BY 1 ORDER BY 1"),
    dict(id="q07", tags="单表/过滤", question="Consumer 类型的客户有多少个?",
         gold="SELECT COUNT(*) FROM customers WHERE segment = 'Consumer'"),
    dict(id="q08", tags="多表/聚合/排序", question="平均折扣最高的 3 个商品子类是哪些?",
         gold="SELECT p.sub_category, ROUND(AVG(i.discount),4) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id "
              "GROUP BY p.sub_category ORDER BY 2 DESC LIMIT 3"),
    dict(id="q09", tags="单表/过滤", question="利润为负的亏损明细有多少行?",
         gold="SELECT COUNT(*) FROM order_items WHERE profit < 0"),
    dict(id="q10", tags="单表/排序", question="运费最高的 5 行明细,列出行号和运费。",
         gold="SELECT row_id, shipping_cost FROM order_items ORDER BY shipping_cost DESC, row_id LIMIT 5"),
    dict(id="q11", tags="多表/过滤", question="美国的客户有多少个?",
         gold="SELECT COUNT(*) FROM customers WHERE country = 'United States'"),
    dict(id="q12", tags="多表/聚合/时间", question="2013 年 12 月的总销售额是多少?",
         gold="SELECT ROUND(SUM(i.sales),2) FROM order_items i JOIN orders o ON i.order_id = o.order_id "
              "WHERE o.order_date >= '2013-12-01' AND o.order_date < '2014-01-01'"),
    dict(id="q13", tags="多表/聚合/排序", question="下单次数最多的 3 个客户,列出客户编号和订单数。",
         gold="SELECT c.customer_id, COUNT(DISTINCT o.order_id) FROM orders o "
              "JOIN customers c ON c.customer_id = o.customer_id "
              "GROUP BY c.customer_id ORDER BY 2 DESC, c.customer_id LIMIT 3"),
    dict(id="q14", tags="多表/聚合", question="Technology 大类平均每行明细的销售额是多少?",
         gold="SELECT ROUND(AVG(i.sales),2) FROM order_items i "
              "JOIN products p ON p.product_id = i.product_id WHERE p.category = 'Technology'"),
    dict(id="q15", tags="单表/过滤", question="折扣不低于 0.3 的明细有多少行?",
         gold="SELECT COUNT(*) FROM order_items WHERE discount >= 0.3"),
    dict(id="q16", tags="单表/聚合", question="每种配送方式各有多少张订单?",
         gold="SELECT ship_mode, COUNT(*) FROM orders GROUP BY ship_mode"),
    dict(id="q17", tags="单表/脏数据", question="数量小于等于 0 的异常明细有哪些行号?",
         gold="SELECT row_id FROM order_items WHERE quantity <= 0"),
    dict(id="q18", tags="多表/聚合", question="各市场的总利润分别是多少?",
         gold="SELECT g.market, ROUND(SUM(i.profit),2) FROM order_items i "
              "JOIN orders o ON o.order_id = i.order_id JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region GROUP BY g.market"),
    dict(id="q19", tags="多表/时间/枚举陷阱/空结果", question="2013 年 3 月亚太市场有多少订单?",
         gold="SELECT COUNT(DISTINCT o.order_id) FROM orders o "
              "JOIN customers c ON c.customer_id = o.customer_id "
              "JOIN geography g ON c.country = g.country AND c.region = g.region "
              "WHERE g.market = 'Asia Pacific' AND o.order_date >= '2013-03-01' AND o.order_date < '2013-04-01'"),
]
