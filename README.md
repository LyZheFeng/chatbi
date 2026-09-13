# chatbi · 数据分析 Agent(项目 2)

中文自然语言 → 生成 SQL → 自愈执行(报错回传/结果反思)→ 图表 + 解读。
备考项目 2,对应 `../agent-internship-plan.md` Week 3(Day 15~21)。

## 当前进度:Day 20 完成(基础链路 + 自愈循环 + Schema 管理 + 图表解读,均有真实跑分)

**链路**:中文提问 → function calling(`get_schema` / `execute_sql` / `final_answer`)→ SQLite 只读执行 → 自动选型图表 + 模板化解读 + 表格 + 中文结论 + 执行轨迹。

**自愈循环(Day 17-18)**:SQL 报错 → 错误分类提示回传 → 修正重试(连续失败上限 3 次即优雅降级);空结果/全 0 触发反思提示,由模型判断"SQL 写错还是数据如此";`self_heal` 可关。25 题评估(temperature=0,`eval/results.md`):

| 条件 | 执行准确率 |
|---|---|
| 自然 · 自愈关(Day 17-18 基线) | 92.0% |
| 自然 · 自愈开(Day 17-18 基线) | 92.0%(该模型在注释 DDL 上首错率为 0,自然无差异) |
| 自然 · 自愈开(Day 19 Schema 注入后) | **96.0%**(24/25,唯一失手为偶数行中位数语义盲区) |
| 故障注入⚡ · 自愈关 | **0%**(首错即降级,不编造) |
| 故障注入⚡ · 自愈开 | **88%**(22/25 一次修正恢复) |

- 数据:Global Superstore(公开电商订单数据集,1000 行明细)整理成 5 张关联表
  (geography / customers / products / orders / order_items),DDL 内嵌中文列注释;
  确定性注入 5 类脏数据(region 缺失 / 数量 0 与负数 / 销售额缺失 / 发货早于下单 / 邮编大面积空)。
- **Schema 管理(Day 19)**:低基数码列(market/segment/category/sub_category/ship_mode/order_priority)
  的枚举取值、日期覆盖范围、折扣范围由建库脚本**从数据动态计算**写进 DDL 注释
  (杜绝"注释写 APAC、库里存 Asia Pacific"式人手不一致);get_schema 输出头部固定带表关系图;
  order_date 注释带按月/按季度分组口径。效果:季度题(q20)一枪修复,枚举陷阱题(q06)从 5 步探查降为 1 枪。
- **图表 + 解读(Day 20)**:按最终表格的列结构确定性选型——时间列 → 折线(年+季度/年+月两列
  自动合成 "2014Q1"/"2014-03" 横轴;带分组列画多系列)、单维度 + 数值 → 柱/横条(问占比且全正
  ≤6 类 → 饼图)、两数值列 → 散点;`chart_spec` 是标准 Vega-Lite JSON(`AskResponse.chart_spec`,
  UI 与接口共用一份,`st.vega_lite_chart` 直接渲染)。图表下配模板化"怎么读这张图"(最值/趋势方向/
  峰值低点/相关性,数字全部来自本地执行结果,一个不新造)。脏数据呈现约定:只剔除"画不了"的行
  (字段 NULL,剔除行数写进解读),负值/0 照画并在解读中点名,表格始终全量——图表与结论同口径。
- 纪律:所有 tool_call 参数过 pydantic 严格校验;表格数据一律来自本地执行
  (final_answer 自报 SQL 本地重执行,保证展示表格与结论锚定同一条 SQL);
  步数耗尽/拒绝调用工具时优雅降级,error 字段说明原因,绝不编造。
- 接口:FastAPI `POST /ask`;界面:Streamlit(`app/ui.py`)。
- 测试:`pytest tests` 63 例(工具校验、SQL 护栏、agent 循环与自愈逻辑 FakeLLM 脚本驱动、
  图表选型/解读/脏数据约定、API、DDL 注释↔数据一致性回归),不依赖网络。

## 界面

![折线图:亚太市场按月销售额趋势](docs/ui-line.png)

![饼图:各市场销售额占比](docs/ui-pie.png)

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

Day 19 ✅ Schema 管理(枚举值入 DDL/表关系图)→ Day 20 ✅ 图表 + 解读 →
Day 21 安全(白名单/LIMIT/超时)+ 50 题评估 → tag `v0.1-chatbi`。
