# PROGRESS · 当前进度

> 每阶段收口更新本文件。新会话从这里接力。

## 状态:仓库已初始化(2026-09-13),项目 2 待开工 → 新会话按 Week 3 起步

## 已定决策(开工即沿用,免重复讨论)

| 项 | 决定 |
|---|---|
| 生成模型 | 内网 vLLM `http://10.14.6.55:30561/v1`,`Qwen3.8-27B`,key=1234(与项目 1 相同,已验证可用) |
| 数据库 | SQLite,公开数据集整理成 3~5 张关联表,故意保留少量脏数据(空值/异常值) |
| 框架 | Python + FastAPI + Streamlit;所有模型输出 pydantic 严格校验(纪律沿袭项目 1) |
| 仓库 | 独立私有仓库 LyZheFeng/chatbi,终稿后视情况公开 |
| 环境 | Python 3.13 + venv(参照项目 1:D:\python,HF/缓存如需一律指 D 盘) |

## 范围(按计划)

Day 15-16 数据+基础链路(get_schema/execute_sql/final_answer)→ Day 17-18 自愈循环
(核心亮点,记录开关对比数字)→ Day 19 Schema 管理 → Day 20 图表+解读 →
Day 21 安全(只读/SELECT 白名单/LIMIT/超时)+ 50 题评估 → tag `v0.1-chatbi`。

## 下一步(新会话)

读 `../agent-internship-plan.md` Week 3 + 本文件,从 Day 15-16 开工:
选数据集(电商订单类)→ 建库 → function calling 三工具 → 中文提问到表格的端到端。

## 环境备忘(沿袭项目 1 的坑)

- Git Bash 中文一律走 Python + UTF-8,不用 curl 发中文
- 评估跑分 temperature=0;进 README 的数字必须全量真实跑出
- 踩坑笔记记 `notes/pitfalls.md`(问题→尝试→结论,3 行)
