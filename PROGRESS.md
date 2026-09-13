# PROGRESS · 当前进度

> 每阶段收口更新本文件。新会话从这里接力。

## 状态:Day 15-16 完成(2026-09-13)→ 新会话从 Day 17-18 自愈循环起步

## 已定决策(开工即沿用,免重复讨论)

| 项 | 决定 |
|---|---|
| 生成模型 | 内网 vLLM `http://10.14.6.55:30561/v1`,`Qwen3.8-27B`,key=1234(与项目 1 相同,已验证可用) |
| 工具协议 | 原生 function calling(已探测可用,`enable_thinking: False`,temperature=0) |
| 数据库 | SQLite `data/chatbi.db`,5 张关联表:geography/customers/products/orders/order_items;DDL 内嵌中文注释 |
| 数据源 | Global Superstore 公开镜像(1000 行,2013-01~2014-09),下载源见 `scripts/build_db.py` 头注释 |
| 脏数据 | 确定性注入 5 类(region 缺失 2 客户/quantity 0×2 与 -2×1/sales NULL×2/发货早于下单×2/邮编 80% 空) |
| 框架 | Python 3.13 + FastAPI + Streamlit;所有 tool_call 参数 pydantic 严格校验(纪律沿袭项目 1) |
| 仓库 | 独立私有仓库 LyZheFeng/chatbi,终稿后视情况公开 |
| 环境 | `.venv/`(D:\python 建的 3.13.9),HF/缓存如需一律指 D 盘 |

## Day 15-16 完成情况(2026-09-13)

- 建库:`scripts/build_db.py`(重建即同结果);表行数 96/800/529/867/1000
- 链路:`app/` 下 agent(function calling 循环,8 步上限)→ tools(三工具+参数校验)→ db(只读连接+SELECT 护栏+自动 LIMIT)→ service/api/ui
- 端到端实测 4 题全对(8~20s/题);其中"亚太月度趋势"题模型自发完成了 枚举值探查→修正SQL 的自愈雏形(5 步)
- 测试:`pytest tests` 28 例全绿(不依赖网络,FakeLLM 脚本驱动 agent)
- 已知限制(留给后续 Day):SQL 白名单只有正则级+只读连接,无超时(Day 21);无重试上限细分与结果反思(Day 17-18)

## 范围(按计划)

Day 15-16 ✅ 数据+基础链路 → Day 17-18 自愈循环(核心亮点,记录开关对比数字)→
Day 19 Schema 管理 → Day 20 图表+解读 → Day 21 安全(只读/SELECT 白名单/LIMIT/超时)+ 50 题评估 → tag `v0.1-chatbi`。

## 下一步(新会话)

按 Day 17-18 开工:
1. `app/agent.py` 加显式重试策略:execute_sql 连续失败上限 3 次、失败原因分类(语法/无此表/无此列/空结果);
2. 结果反思:空结果/异常值时让 agent 判断"SQL 写错还是数据本身如此"(可加 reflect 工具或复用 execute_sql 错误回传);
3. 超限优雅降级文案;**准备开关对比实验(自愈 on/off 各跑一遍问题集,数字进 eval/results.md)——这是简历量化数字**。

## 环境备忘(沿袭项目 1 的坑)

- Git Bash 中文一律走 Python + UTF-8,不用 curl 发中文
- 评估跑分 temperature=0;进 README 的数字必须全量真实跑出
- 踩坑笔记记 `notes/pitfalls.md`(问题→尝试→结论,3 行)
- GitHub 直连慢,下载用 `curl -C -` 断点续传加重试循环
