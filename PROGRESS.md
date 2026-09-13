# PROGRESS · 当前进度

> 每阶段收口更新本文件。新会话从这里接力。

## 状态:Day 15-18 完成(2026-09-13)→ 新会话从 Day 19 Schema 管理起步

## 已定决策(开工即沿用,免重复讨论)

| 项 | 决定 |
|---|---|
| 生成模型 | 内网 vLLM `http://10.14.6.55:30561/v1`,`Qwen3.8-27B`,key=1234(与项目 1 相同,已验证可用) |
| 工具协议 | 原生 function calling(已探测可用,`enable_thinking: False`,temperature=0) |
| 数据库 | SQLite `data/chatbi.db`,5 张关联表:geography/customers/products/orders/order_items;DDL 内嵌中文注释 |
| 数据源 | Global Superstore 公开镜像(1000 行,2013-01~2014-09),下载源见 `scripts/build_db.py` 头注释 |
| 脏数据 | 确定性注入 5 类(region 缺失 2 客户/quantity 0×2 与 -2×1/sales NULL×2/发货早于下单×2/邮编 80% 空) |
| 框架 | Python 3.13 + FastAPI + Streamlit;所有 tool_call 参数 pydantic 严格校验(纪律沿袭项目 1) |
| 自愈 | `self_heal` 配置项(默认开):错误回传+分类提示重试(连续失败上限 3)+ 空/异常结果反思提示;off = 首错即降级。评估用 `--chaos` 故障注入模式量恢复能力 |
| 评估 | 判定口径:gold 值集合一致(圆整 2 位、行序无关、允许多带上下文列投影比对、单行 gold 答案点包含);gold SQL 不圆整,容差只在判定器一处 |
| 仓库 | 独立私有仓库 LyZheFeng/chatbi,终稿后视情况公开 |
| 环境 | `.venv/`(D:\python 建的 3.13.9),HF/缓存如需一律指 D 盘 |

## Day 15-16 完成情况(2026-09-13)

- 建库:`scripts/build_db.py`(重建即同结果);表行数 96/800/529/867/1000
- 链路:`app/` 下 agent(function calling 循环,8 步上限)→ tools(三工具+参数校验)→ db(只读连接+SELECT 护栏+自动 LIMIT)→ service/api/ui
- 端到端实测 4 题全对(8~20s/题);其中"亚太月度趋势"题模型自发完成了 枚举值探查→修正SQL 的自愈雏形(5 步)
- 测试:`pytest tests` 28 例全绿(不依赖网络,FakeLLM 脚本驱动 agent)
- 已知限制(留给后续 Day):SQL 白名单只有正则级+只读连接,无超时(Day 21);无重试上限细分与结果反思(Day 17-18)

## Day 17-18 完成情况(2026-09-13,数字全量真实跑出,temperature=0)

- 自愈三件套:SQL 连续失败上限 3 次即降级(错误分类提示:表名/列名/语法/函数/只读);空结果或单列全 0/NULL 触发反思提示(模型判断"SQL 错还是数据如此");超限/不调工具优雅降级,error 写明原因
- 修复关键 bug:final_answer 自报 SQL 本地重执行,展示表格与结论锚定同一条 SQL(此前探查查询会遮蔽最终结果)
- 25 题评估(`eval/`,四组条件):自然/自愈关 92.0% ≈ 自然/自愈开 92.0%(该模型在注释 DDL 上首错率为 0,自然无差异);**注入⚡(每题首条 SQL 强制改错表名):自愈关 0% → 自愈开 88%**,22/25 题一次修正恢复,1 题叠加枚举探查触步数上限
- 边界结论(写进了 results.md 解读):q20(问季度答按月)/q25(中位数取上中位值)是"跑通但答非所问"的语义错误,自愈不覆盖;枚举探查消耗步数,Day 19 注入枚举值示例应能消掉
- 测试 40 例全绿(自愈逻辑全部 FakeLLM 脚本化,不依赖网络)

## 范围(按计划)

Day 15-16 ✅ 数据+基础链路 → Day 17-18 ✅ 自愈循环(四组对比数字见 `eval/results.md`)→
Day 19 Schema 管理 → Day 20 图表+解读 → Day 21 安全(只读/SELECT 白名单/LIMIT/超时)+ 50 题评估 → tag `v0.1-chatbi`。

## 下一步(新会话)

按 Day 19 开工:
1. 枚举值示例直接写进 DDL 注释(market/segment/category/ship_mode 等低基数列),消掉 q06/q19 类"探查枚举"的步数消耗;
2. 多表选择:get_schema 支持"先选相关表"两段式(或 system prompt 带表关系图),只注入相关表的 DDL+列说明;
3. 每列业务含义注释补全(建库脚本里已有一版,查漏);
4. 重跑 25 题自然评估,与 92.0% 对比看 Day 19 的增量(尤其 q20 季度题:可在 order_date 注释里写季度口径示例)。

## 环境备忘(沿袭项目 1 的坑)

- Git Bash 中文一律走 Python + UTF-8,不用 curl 发中文
- 评估跑分 temperature=0;进 README 的数字必须全量真实跑出
- 踩坑笔记记 `notes/pitfalls.md`(问题→尝试→结论,3 行)
- GitHub 直连慢,下载用 `curl -C -` 断点续传加重试循环
