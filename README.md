# chatbi · 数据分析 Agent(项目 2)

中文自然语言 → 生成 SQL → 自愈执行(报错回传/结果反思)→ 图表 + 解读。
备考项目 2,对应 `../agent-internship-plan.md` Week 3(Day 15~21)。

## 当前进度:Day 15-18 完成(基础链路 + 自愈循环,均有真实跑分)

**链路**:中文提问 → function calling(`get_schema` / `execute_sql` / `final_answer`)→ SQLite 只读执行 → 表格 + 中文结论 + 执行轨迹。

**自愈循环(Day 17-18)**:SQL 报错 → 错误分类提示回传 → 修正重试(连续失败上限 3 次即优雅降级);空结果/全 0 触发反思提示,由模型判断"SQL 写错还是数据如此";`self_heal` 可关。25 题评估(temperature=0,`eval/results.md`):

| 条件 | 执行准确率 |
|---|---|
| 自然 · 自愈关 | 92.0% |
| 自然 · 自愈开 | 92.0%(该模型在注释 DDL 上首错率为 0,自然无差异) |
| 故障注入⚡ · 自愈关 | **0%**(首错即降级,不编造) |
| 故障注入⚡ · 自愈开 | **88%**(22/25 一次修正恢复) |

- 数据:Global Superstore(公开电商订单数据集,1000 行明细)整理成 5 张关联表
  (geography / customers / products / orders / order_items),DDL 内嵌中文列注释;
  确定性注入 5 类脏数据(region 缺失 / 数量 0 与负数 / 销售额缺失 / 发货早于下单 / 邮编大面积空)。
- 纪律:所有 tool_call 参数过 pydantic 严格校验;表格数据一律来自本地执行
  (final_answer 自报 SQL 本地重执行,保证展示表格与结论锚定同一条 SQL);
  步数耗尽/拒绝调用工具时优雅降级,error 字段说明原因,绝不编造。
- 接口:FastAPI `POST /ask`;界面:Streamlit(`app/ui.py`)。
- 测试:`pytest tests` 40 例(工具校验、SQL 护栏、agent 循环与自愈逻辑 FakeLLM 脚本驱动、API),不依赖网络。

## 本地运行

```bash
# 1. 环境(Windows,Python 3.13)
/d/python/python.exe -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env                # 内网 vLLM 配置

# 2. 建库(源数据放 data/raw/,来源见 scripts/build_db.py 头注释)
.venv/Scripts/python.exe -X utf8 scripts/build_db.py

# 3. 演示
.venv/Scripts/python.exe -X utf8 scripts/demo_ask.py       # 命令行端到端
.venv/Scripts/python.exe -X utf8 -m uvicorn app.api:app --port 8000
.venv/Scripts/python.exe -X utf8 -m streamlit run app/ui.py
```

## 计划(详见 PROGRESS.md)

Day 19 Schema 管理(枚举值入 DDL/相关表选择)→ Day 20 图表 + 解读 →
Day 21 安全(白名单/LIMIT/超时)+ 50 题评估 → tag `v0.1-chatbi`。
