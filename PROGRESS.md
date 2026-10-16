# PROGRESS · 当前进度

> 每阶段收口更新本文件。新会话从这里接力。

## 状态:优化计划阶段 0+1 完成(2026-09-17,`optimization-plan.md` 第一部分:快赢 + 评测守护;CI 顺带复绿)→ 下一步 Day 27-28 求职材料

## 阶段 0+1 · 优化计划第一部分完成情况(2026-09-17,`optimization-plan.md`;rag-qa 侧改动见其仓 PROGRESS)

- **阶段 0 快赢**:
  - `ChartCard` 开 vega-embed 导出菜单(`actions: {export: true, source/compiled/editor: false}`)——用户可存 PNG/SVG;source/compiled/editor 是看源码/跳外网编辑器,离线演示无意义故关(浏览器实测菜单恰为 Save as SVG / Save as PNG 两项)
  - `_short_args` 的 sql 截断 80→200(80 连 SELECT+FROM 都看不全,Timeline 失去排查价值;其余字段保持 80,detail 另有 300 兜底)
  - 对话历史 localStorage 持久化(key `chatbi.chat.turns.v1`,与 rag-qa 复制对齐)——刷新不丢(浏览器实测:结论 + 图表 vega-embed 重渲染 + 表格全恢复)、「清空对话」即清存储、刷新时在途轮转可重试错误态、损坏即弃、超配额(done 态含 200 行表格)退化存最近 20 条;96 例全绿、`npm run build` 过
- **CI 复绿(阶段五遗留实锤)**:①requirements.lock 的 pywin32 补 `sys_platform=="win32"` 平台标记——阶段五在 Windows 重生 lock 后 ubuntu 装不上,**CI 连续三次红**(pip freeze 不带 marker 的坑,与 rag-qa lock 同款处理);②`test_protocol_surface` 补 skipif(CI 无真实 data/chatbi.db 时 get_schema 报 Error;MCP 的 DB_PATH 被锁在项目 data/ 内,conftest 的 tmp mini 库过不了启动校验,故与另两个 stdio 测试同口径跳过);双平台复绿(1m17s)
- **阶段 1 评测守护**:`scripts/smoke_eval.py` 固定 5 题(计数/聚合/占比/时间序列/脏数据点名),断言 agent 无 error、SQL 已执行(row_count≥1)、结论非空,加各题专项:计数单值=1000、图表 mark 符合预期(bar/arc/line)、脏数据行号集合={58,62,220};与 `eval/smoke_baseline.json` 快照对比输出一页漂移报告
  - **当次跑批(2026-09-17 15:11,vLLM Qwen3.8-27B):5/5 通过、零漂移**(连续三跑同表现;占比 arc 5 行、时间序列 line 47 个月、脏数据点名连 quantity 值都对:58=0、62=-2、220)
- 用法:`.venv/Scripts/python.exe -X utf8 scripts/smoke_eval.py`;纪律:演示前、报任何评估数字前必跑,结果带日期记本文件(口径「当次跑批」)

## 阶段五 · 统一与收尾完成情况(2026-09-17,`frontend-upgrade-workflow.md` 阶段 5)

- **前端统一(复制对齐,非 workspace)**:两仓独立,pnpm workspace 会把共享包置于两仓之外不被任何一仓版本化(CI 也拉不到),故按工作流预留的第二条路「先复制对齐再抽」执行——`lib/sse.ts` 逐字对齐(rag-qa 版补 headers 参数)、版心统一 860px、`next.config.ts` 同步 `allowedDevOrigins`(rag-qa 实测踩了 chatbi 同款 127.0.0.1 不水合坑)、Sidebar/状态机/输入区骨架结构一致;将来抽 npm 私有包或合并仓时零结构改动。两仓 `npm run build` 含 TS 严格检查均过
- **移除 Streamlit(P0-1 纪律执行)**:`app/ui.py` 删除(历史见 git);requirements.txt 去 streamlit,requirements.lock 全量重生(51 项,streamlit 及 altair/pyarrow 等专属传递依赖整体移除);**全新 venv 从 requirements.txt 安装 → 96 例全绿**(证明声明自足、无被 streamlit 掩盖的隐性依赖;pandas 显式保留——build_db.py 直接引用);README 运行说明/接口行/测试数同步
- **验收(= 计划通关标准③)**:chatbi 浏览器实测——轨迹直播 → 结论打字机 → 饼图/折线/分组柱状三图型渲染 → SQL 轨迹面板 → 会话统计,代码/依赖/文档/截图无 Streamlit 痕迹;截图 `docs/web-ui.png` + `docs/web-line.png` + `docs/web-bar.png`(旧 ui-*.png 删除)
- **portfolio 联动**(`D:\LLM_training\portfolio\`):chatbi 三截图换 Next.js 版、rag-qa 卡新增前端截图卡、离线单测 161→190(94+96)、技术栈/页脚 Streamlit→Next.js,静态服务验证图片无坏链
- **简历句子(工作流预定)**:「以 FastAPI + Next.js 重构 agent 产品前端,支持 SSE 流式渲染、引用溯源交互与任务过程可视化」

## 阶段四 · chatbi 前端改造完成情况(2026-09-17)

- **后端只加接口**(零回归,全量 96 例测试绿,新增 10 例 `tests/test_stream.py`):
  - `GET /ask/stream`(SSE,`text/event-stream`):事件序 `sources*`(agent 每执行完一个工具调用推**累计** steps,与 rag-qa 的 hits 同位,前端整体替换可漏帧自愈)→ `delta*`(中文结论分段)→ `done`(权威终态,完整 AskResponse 含 chart_spec/chart_reading);LLM 繁忙/未预期异常收拢为 `error` 事件(与 /ask 降级同口径),agent 内部优雅降级仍走 `done.error` 不混淆传输层
  - **agent 流式化解法**:`run()` 与新 `stream()` 共用同一循环 `_iter_steps`(行为完全一致,仅产出时机不同),`_execute` 改返回 (ToolStep, 是否终止);eval/测试/MCP 链路零改动
  - **delta 是服务端分段的 summary**(final_answer 一次产出,按句切分 ~24 字 + 10ms 间隔营造打字机节奏,内容与 done.summary 严格一致——有测试锁定)
  - CORS:Settings 新增 `cors_origins`(逗号分隔,默认 localhost:3000 两写法);`iterate_in_threadpool` 桥接同步生成器
  - **鉴权/限流保留且覆盖流式**:`/ask/stream` 同样过 X-API-Key 依赖;限流路径口径改为 `/ask` + `/ask/stream`(都触发整轮 agent,成本一致);新增测试:流式鉴权 401、限流 429、CORS 预检、error 事件不泄漏异常类名
- **前端 `web/`**(Next.js 16.3.5 + React 19.2 + Tailwind v4 + vega-embed 7,`npm run build` 含 TS 严格检查通过):
  - 结构见 `web/README.md`;`lib/types.ts` 与 `app/schemas.py` 逐字段对齐;`lib/sse.ts` 沿袭 rag-qa 的 fetch+ReadableStream 方案并加自定义请求头(X-API-Key)
  - 状态机 `running`(轨迹直播)→ `summary`(结论打字机)→ `done`/`error`;复用 rag-qa 布局骨架(深色侧栏 + hero + 示例问题胶囊 + 输入区),品牌色换 chatbi 的深蓝→青绿
  - **Timeline** 新组件:agent 轨迹可视化(编号圆点 + 工具中文标签 + 参数 mono + 结果摘要,失败步骤标红并注明"已回传模型修正",流式期间最新步骤脉冲 + 尾部"规划下一步…"等待态)
  - **ChartCard** 新组件:vega-embed 动态导入(~1MB vega 不进首屏)、白底卡片(spec 已钉死深色文字,沿袭深色主题下 Vega 黑字不可读的教训)+ 自动选型标签 + "怎么读这张图"解读;两处前端注入:width=container 自适应、顶部 padding 46(vega-lite 6 运行时下 config.padding=22 容不下标题会被 viewBox 裁顶,实测修复)
  - API key 走 `.env.local` 的 `NEXT_PUBLIC_API_KEY`(空 = 后端未启用);服务端路由代理隐藏 key 留阶段 5
  - 踩坑:Next dev 默认拦截 `127.0.0.1` 来源的 HMR/dev 资源,页面停在未水合状态(按钮无响应、轮询不走)——`next.config.ts` 加 `allowedDevOrigins: ["127.0.0.1"]` 解决
- **端到端实测**(真实 vLLM Qwen3.8-27B):Python 直连 SSE 冒烟通过(sources 1.1s/3.8s/11.4s 逐步到达,delta 拼接==summary,done 含图表 47 行);浏览器实测:示例点击→轨迹直播(含 47 行结果摘要实时亮出)→结论分段打出→饼图/折线图渲染→SQL 轨迹面板展开→会话统计(提问/平均延迟/累计 tokens);截图 `docs/web-ui.png`;冒烟脚本 `scripts/smoke_stream.py` 留档可复跑
- **Streamlit 版保留**(按工作流约定,阶段五新前端稳定验收后才删);启动:`uvicorn app.api:app --port 8010` + `cd web && npm run dev`(端口 8010 与 rag-qa 的 8000 错开,可同时开)

## 已定决策(开工即沿用,免重复讨论)

| 项 | 决定 |
|---|---|
| 生成模型 | vLLM(自建/内网)`http://<vllm-host>:<port>/v1`,`Qwen3.8-27B`,key 见 .env(与项目 1 相同,已验证可用) |
| 工具协议 | 原生 function calling(已探测可用,`enable_thinking: False`,temperature=0) |
| 数据库 | SQLite `data/chatbi.db`,5 张关联表:geography/customers/products/orders/order_items;DDL 内嵌中文注释 |
| 数据源 | Global Superstore 公开镜像(1000 行,日期实际覆盖 2012-01~2015-12,下载源见 `scripts/build_db.py` 头注释) |
| 脏数据 | 确定性注入 5 类(region 缺失 2 客户/quantity 0×2 与 -2×1/sales NULL×2/发货早于下单×2/邮编 80% 空) |
| 框架 | Python 3.13 + FastAPI + Streamlit;所有 tool_call 参数 pydantic 严格校验(纪律沿袭项目 1) |
| 自愈 | `self_heal` 配置项(默认开):错误回传+分类提示重试(连续失败上限 3)+ 空/异常结果反思提示;off = 首错即降级。评估用 `--chaos` 故障注入模式量恢复能力 |
| 评估 | 判定口径:gold 值集合一致(圆整 2 位、行序无关、允许多带上下文列投影比对、单行 gold 答案点包含);gold SQL 不圆整,容差只在判定器一处 |
| 仓库 | 独立仓库 LyZheFeng/chatbi(2026-10-16 起公开,求职展示) |
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

## Day 19 完成情况(2026-09-13,自然评估全量真实跑出,temperature=0)

- **枚举/统计量入 DDL,且由数据动态生成**:market/segment/category/sub_category/ship_mode/order_priority 全部取值、日期覆盖 2012-01-08~2015-12-31、折扣范围 0~0.8,全部由 `scripts/build_db.py` 建库时从数据算出渲染进 DDL 模板——修掉了三处人手注释错误(注释写 APAC 实为 Asia Pacific、折扣写 0~0.5 实为 0~0.8、文档日期范围 2013-2014 实为 2012-2015);新增回归测试逐值断言"注释包含库中每个实际取值"
- **表关系图**:`db.schema_text()` 输出头部固定带外键指向图 + "geography 须经 customers 关联到达";get_schema 描述更新(支持 tables 子集,5 表建议直接全量);system prompt 写明月/季度分组口径、"枚举照抄注释"约定
- **25 题自然评估:92.0% → 96.0%**(24/25,平均延迟 6036ms 持平):q20 季度题一枪修复(3 步);q06 枚举陷阱从 5 步探查降为 1 枪;q21 假阴性系 gold 未按题意过滤年份,修 gold 后 ✓;唯一失败 q25(偶数行中位数取中间两值之和而非均值)仍是语义盲区,留 Day 21 决定是否提示层处理
- q19(真实答案为 0)仍走 1 反思 + 3 确认探查后如实作答(~14s),"合法的 0"上的设计内行为,保留
- 测试 42 例全绿(新增 ER 图与注释↔数据一致性 2 例;mini CSV 市场值对齐真实取值 Asia Pacific/Europe)

## Day 20 完成情况(2026-09-13,图表+解读,真实链路验证)

- **`app/charts.py` 纯函数选型**:输入只有最终表格 columns/rows + 问题文本,不查库不问 LLM——时间列(列名 month/月份/quarter/季度… 或值形如 YYYY[-MM[-DD]])→折线,年+季度/年+月两列自动合成 "2014Q3"/"2014-03" 横轴(按时间排序非字典序),带 ≤8 类分组列画多系列;单维度+数值→柱(>12 类或标签 >8 字转横条),问"占比/比例/构成/份额"且全正 ≤6 类→饼;两数值列无维度→散点;其余(≥2 维度、≥3 数值、行 <2、类 >30)不画,表格已足够
- **真实链路撞出的两个选型盲区并修复**:模型爱多算一列比率(profit_margin_pct/pct)→ 3 数值列全落空 → 放宽为柱/横条取前两个数值列、饼图只画第一个数值列(share 按图内合计重算,与模型自算的全局占比口径分开,解读写明"图内合计")
- **解读模板**(chart_reading):折线讲首末趋势±%/峰值/低点,多系列讲合计趋势+全程峰值+累计 top;柱状讲最高/其次/最低+倍数+负值点名;饼讲占比最大/前三合计;散点讲取值范围+相关方向(r);**数字全部来自本地执行结果**;NULL 剔除行数如实写进解读("另有 N 行因字段缺失未画入,表格中仍可见")
- **脏数据呈现约定**(写进模块 docstring 与测试):只剔除"画不了"的行(维度/数值 NULL),负值/0 是数据本身照画并点名,表格始终全量——图表与结论同口径,别图表剔了结论没剔
- **UI/接口**:AskResponse 增加 `chart_spec`(标准 Vega-Lite JSON)+ `chart_reading`,Streamlit 用 `st.vega_lite_chart` 渲染同一份 spec;图表固定白底(深色主题下 Vega 默认黑字不可读,真实 UI 截图发现);agent 与评估零改动,呈现层纯增量
- **验证**:63 例测试全绿(新增 21 例:选型确定性/spec 形状/解读数字锚定/NULL 剔除/降级不出图/service 集成);真实 vLLM 端到端验证折线(47 期)/分组柱/饼图出图正确、多列明细按约定不画图,散点与年+季度合并轴由单测确定性覆盖(真实链路上模型对"关系"类问题倾向聚合输出,纯两数值列形态少见);Streamlit 浏览器实测图表+解读渲染正常,截图进 README(docs/ui-line.png、docs/ui-pie.png)

## Day 21 完成情况(2026-09-13,安全加固 + 50 题评估,四组数字全量真实跑出,temperature=0)

- **安全加固(SQL 护栏三层)**:①连接 `mode=ro` 物理只读不变;②SELECT 白名单从正则级升级 **token 级**——词法扫描把字符串/引号标识符/注释各自成 token(关键字伪装不进、字面量里的 'DROP TABLE' 不误杀),首 token 必须 SELECT/WITH、禁分号拼多条、禁 PRAGMA/ATTACH/EXPLAIN/VACUUM 等语句关键字、禁 load_extension/randomblob/pragma_* 等危险函数;③**执行超时**:`progress_handler` 按秒掐断(默认 5s,配置 `sql_timeout_s`),只读连接挡不住的算力攻击(无界 RECURSIVE CTE)被测验证 <3s 中断,超时错误带修正提示回传模型自愈
- **题库 25→50 题**:新增脏数据明细(q30/q31/q32 行号与订单号定位)、脏数据口径(q33 剔除异常后聚合)、聚合边界(q42 合法 0/q44 MIN-MAX/q49/q50 负利润)、图表问法(q39/q40/q41)、更多枚举与多表;50 条 gold 全部本地执行校验
- **尺子修正一次**:q22 原问法(商品利润率前 5)首跑暴露 6 个商品利润率并列 0.5,top-5 无确定答案(并列陷阱在比率题复发)→ 改考"子类利润率前 3"(边界值无并列);**出题前先查边界值多重性**成为固定动作
- **q25 中位数口径入提示**:system prompt 写明"偶数个非空值取中间两值的平均、最终只返回一个数值"后一枪修复(此前模型已取到中间两值但返回两行)——Day 17-18 的两道语义失手至此全部消解
- **四组评估(数字见 `eval/results.md`)**:自然/自愈开 **50/50=100.0%**(平均 5722ms)、自然/自愈关 50/50=100.0%、注入⚡/自愈关 0/50 全降级(不编造)、注入⚡/自愈开 **50/50=100.0% 全恢复**(vs Day 17-18 的 88%;归因:Day 19 消掉枚举探查步数后,注入+重试的 8 步预算不再紧张)。出图率 24/50:不出图 26 题=17 单值答案+4 行号列表+4 单行多列+1 超 30 类国家表,无"该画没画";图型 bar 19 / line 5
- 测试 66 例全绿(新增 token 白名单绕过/误杀、超时掐断 3 例);README/PROGRESS/pitfalls 同步,tag `v0.1-chatbi` 已打并推送

## 外部评审修复(2026-09-13,Codex 评审 P0/P1;v0.1 之后、main 直推)

- **P0-1 依赖**:`pandas` 由 streamlit 传递安装掩盖了未声明(ui/build_db 直接 import)→ 显式入 requirements.txt;`pip freeze` 出 `requirements.lock` 供可复现安装;新增 CI(ubuntu+windows 全新环境装 requirements.txt 跑离线测试)兜住"装不上"这类问题
- **P0-2 连接泄漏**:service.ask 每请求 connect_ro 但从不关闭 → finally 关闭(测试断言 ask 后连接不可再执行)
- **P0-3 LIMIT 误判**:`_HAS_LIMIT` 正则会被 `SELECT 'limit'` / `-- limit` 骗过从而跳过自动行数上限 → LIMIT 子句改由 `_guard_sql` 的词法 token 判定(字符串/引号标识符/注释里的不算),与白名单共用同一个 tokenizer
- **P0-4 API 保护(最小集)**:可选 API Key 鉴权(`api_key` 非空即启用,缺/错 `X-API-Key` 一律 401);service 未预期异常兜底为结构化 error(不抛 500,与优雅降级同口径)。限流/异步队列/Prometheus/熔断属部署层,记路线图
- **P1-5 测试环境**:pytest.ini `--basetemp=.pytest_tmp` 把临时目录固定在仓库内(评审环境 Windows TEMP 权限曾致 44 例 setup 失败);.gitignore 排除
- **P1-6 LLM 重试**:openai SDK 本就内建连接错误/429/5xx 指数退避重试 → 显式化为 `llm_max_retries`(默认 3)配置并传入;熔断/fallback 不做
- **P1-8 建库破坏性**:`unlink()` 直接删旧库 → 先写 `<db>.tmp`、自检无空表后 `replace` 原子替换,旧库自动备份 `.bak`;真实数据重建验证行数一致
- 评审中**未采纳/缓办**:P1-7 结构化查询意图与语义校验(架构级改造,与 function calling 直出 SQL 的既有决策冲突,单独立项再议);P2-9/10/11(观测审计、schema 检索、图表增强)记路线图
- 测试 71 例全绿(新增 LIMIT 误判、连接回收、鉴权 401、异常兜底、原子建库 5 例)

## 外部评审二轮修复(2026-09-13,复评 P1;main 直推)

- **CI 锁版本**:pip 先装 requirements.txt(验证声明自足)再装 requirements.lock(锁死版本防漂移)
- **并发控制(LLM 闸门)**:全局 BoundedSemaphore(按容量共享,LLM 实例每请求新建)限制在途 LLM 调用 `llm_max_concurrency`(默认 8);闸门外排队 `llm_gate_wait_s`(默认 30s)超时抛 LLMBusy → API 层转"LLM 繁忙"降级,不占线程死等;README 补 `--workers 4` 多 worker 说明(限流计数进程内,多 worker 需网关/Redis)
- **观测最小集**:每请求 `X-Request-Id` 响应头 + 结构化访问日志(方法/路径/状态/耗时);token 用量统计(LLM 累加 used_tokens → agent 汇总进 `stats.llm_tokens`,真实链路单题 ~3.9k)
- **限流(可选)**:`rate_limit_per_min` 非 0 时按客户端 IP 固定窗口计数,超限 429(进程内,单 worker 有效)
- **异常信息收敛**:对外只返回"服务内部错误,请稍后重试",完整异常堆栈 `logger.exception` 进服务端日志(不再泄漏异常类名)
- **备份轮换**:建库备份从单份 .bak 滚动为 .bak/.bak.1/.bak.2(最近 3 份),连续误构建也有可恢复版本
- 复评**仍缓办**:异步任务队列/Prometheus 指标(部署层);查询意图结构化层(架构级,P2-5 复现了首轮建议,维持单独立项判断);本地 .pytest_tmp 历史文件锁属环境清理问题,不在代码层修
- 测试 76 例全绿(新增闸门超时/释放、token 累计与 stats 透传、request id+限流 429、通用错误文案、备份轮换 5 例);真实链路冒烟通过(占比题出饼图、llm_tokens 记账正常)

## 外部评审三轮修复(2026-09-13;复评结论"稳定原型,具备内网部署条件")

- **限流状态有界化(三轮 P1-1,唯一代码级缺陷)**:`_RATE_STATE` 到达 10_000 条即惰性清扫过期窗口(锁内完成),伪造/代理 IP 撑不爆内存;测试覆盖清扫路径
- 其余四条维持路线图判断:多 worker 限流/闸门不共享(README 已标注,正式部署走网关/Redis)、请求级取消(需异步化改造)、语义校验/结构化查询意图(架构级,单独立项)、Prometheus/异步队列(部署层)
- 测试 77 例全绿

## Day 22 完成情况(2026-09-14,项目 4:chatbi 查询 MCP server)

- **选型(开工与用户确认)**:官方 `mcp` SDK(装到 2.2.0,注意 FastMCP 已改名 `mcp.server.mcpserver.MCPServer`)、stdio transport;演示客户端走 Inspector + Day 24 自写最小 client
- **`app/mcp_server.py`**:MCP 是传输协议不改工具语义——`get_schema`/`execute_sql` 直接复用 `app/db.py` 三层护栏(mode=ro + token 白名单 + 超时),每次调用独立只读连接;三类原语齐备:tools(上述两个,与 function calling 版同名同义,`final_answer` 编排留客户端)+ resources(`chatbi://schema` 全量、`chatbi://tables/{table}` 模板)+ prompts(`analyze_data` 口径模板:SQL 约定 + 脏数据说明)
- **错误即接口**:护栏/SQL 错误显式转 `ToolError` → `isError=true` + 原始消息完整回传(自愈信号不丢);其他异常由 SDK mask 不泄内部细节
- **验证**:新增 `tests/test_mcp_server.py` 3 例(真实 stdio 子进程,与 Inspector 同入口 `python -m app.mcp_server`),全量 84 例绿;**50 题 gold SQL 经 MCP vs 本地直连逐题一致**(交接单点名的验证资产);Inspector CLI(tools/list、tools/call 成功+护栏错误、resources/read、prompts/get)与 Web UI 均实测通过,中文 UTF-8 落文件验字节无恙(终端乱码纯 Git Bash 渲染)
- **配置**:`scripts/mcp-inspector.json`(Inspector 的 server 配置,绝对路径免 cwd 依赖);requirements.txt + lock 增 `mcp`;README 新增「MCP 工具设计」节 + 本地运行第 4 步;踩坑 4 条进 `notes/pitfalls.md`(2.x 改名 / ToolError 语义 / Inspector CLI 裸拼参数被吞 / 验字节不验肉眼)
- **外部评审修复(codex 评审 7.5/10,同日)**:两个 P1 落地——① 引号形式危险函数绕过:`"randomblob"(..)` / `[zeroblob](..)` / `` `fn`(..) `` 实测可执行且可过词法黑名单,修为"任何 token 后跟 `(` 即按去引号后的真实名字查危险函数"(引号版 `pragma_table_info` 一并拦);② `DB_PATH` env 可指向任意库:修为 resolve+normcase 前缀校验锁死 data/ 目录、`main()` 启动即校验。新增回归 2 例(引号函数 8 形式 / 路径逃逸 3 形式),全量 86 例绿;P2 按评审共识暂不做(错误原样回传是自愈通道、stdio 本地无认证需求,改远程 HTTP 时再补),踩坑 2 条进 pitfalls;**复评 8.5/10(同日)**:两项修复验证通过、无新高危,残余风险三项(P2)与上述暂缓项一致,另建议 data/ 目录存在多用户写入时把 db_path 进一步固定到单一文件——当前单机开发环境不触发,暂不收紧

## Day 24 完成情况(2026-09-14,项目 4:双 server 演示 client;rag-qa server 见其仓库 PROGRESS)

- **`scripts/mcp_client_demo.py`**(chatbi venv,依赖 mcp+openai):一次会话同时拉起 chatbi-db 与 rag-qa-docs 两个 stdio server(各自 venv 绝对路径,免 cwd 依赖),工具按 `server名.工具名` 命名空间去重喂给 vLLM(Qwen3.8-27B function calling,temperature=0,enable_thinking off,8 步上限);错误结果(isError)文本原样回传模型,保留自愈通道
- **实测 3 问全对并核验**:数据库题(2014 top3 国家 Australia/China/France 及金额与直连 SQL 一致)、文档题(请求体模型,编号引用)、混合题(同一循环先 rag-qa-docs.search 查依赖注入、再 chatbi-db.get_schema→execute_sql 得 2013 Consumer 100 张订单,与直连一致);rag-qa 子进程 env 加 TQDM_DISABLE=1 防进度条污染演示输出
- README「MCP 工具设计」节补 client 演示小节

## Day 25-26 完成情况(2026-09-14,统一 Landing 页;demo 录制留给用户)

- **`D:\LLM_training\portfolio\`**(不建仓库):`index.html` 纯静态单文件,内嵌 CSS、零外部依赖(系统字体栈,离线双击即开,日后可直接挂 GitHub Pages);`assets/` 拷贝 chatbi 三张 UI 截图(ui-line/ui-bar/ui-pie)
- **页面结构**:hero(组合定位 + 关键数字带:4.41/5、100%、0%→100% 恢复、2+1 MCP、161 例测试)→ 项目1 rag-qa(链路流程图 + 6 指标 + 版本演进表含两次负结果 + 关键读数 + 工程要点)→ 项目2 chatbi(自愈三条件对比 + SQL 护栏三层 + 图表解读约定 + 3 截图)→ 项目4 MCP(client→双 server 拓扑 + tools/resources/prompts 三原语 + 等价性验证)→ 工程方法论 6 卡(尺子先于优化/尺子也要审/负结果收口/离线测试/踩坑笔记/纪律)→ demo 区
- **数字纪律延续**:页面所有数字逐条取自两仓 README/PROGRESS,无一处新造
- **demo 留位**(用户自录):demo 区写了 2 分钟四段大纲(数据库题/文档题/混合题+自愈纠错/图表收尾),`<video>` 已留 HTML 注释——录好放 `portfolio/assets/demo.mp4` 取消注释即嵌入
- **验收**:本地 `http.server` 起站,浏览器逐区块截图检查(hero/p1/p2/截图网格/p4/方法论/demo/footer),修 statband 第 4 格标签折行 1 处;三张截图加载正常

## 范围(按计划)

Day 15-16 ✅ 数据+基础链路 → Day 17-18 ✅ 自愈循环(四组对比数字见 `eval/results.md`)→
Day 19 ✅ Schema 管理(枚举动态入 DDL/表关系图,92.0%→96.0%)→ Day 20 ✅ 图表+解读(Vega-Lite 选型/模板化解读/脏数据呈现约定)→ Day 21 ✅ 安全加固(token 白名单/超时)+ 50 题评估(自然 100%,注入 100% 恢复)→ **tag `v0.1-chatbi` 已完成** →
Day 22 ✅ MCP 化(数据库查询 server)→ Day 24 ✅ 双 server 演示 client(rag-qa 检索 server 同日完成,见其仓库)→
Day 25-26 ✅ 统一 Landing 页(`D:\LLM_training\portfolio\`,demo 录制留给用户)。

## 下一步(新会话)

> 当前执行文件:`D:\LLM_training\optimization-plan.md`(2026-09-17 制定,推荐路线:第一部分已完成,后续按第二部分 Day 27-28 → 暂缓区)。

Day 25-26 的 Landing 页已完成:统一入口 + demo 大纲与嵌入点就位,视频用户自录。后续:
1. Day 27-28:简历段落 + 面试题(材料从两项目 README/results/pitfalls 提炼;MCP 高频题素材已就位);
2. 用户自录 2 分钟 demo 后放 `portfolio/assets/demo.mp4`,取消 index.html 中 `<video>` 注释即嵌入;
3. 可选:Inspector Web UI 手动走查截图、双仓 README 交叉链接复核。

项目 2 遗留的可选后续(复盘/公开仓库)不变。

## 环境备忘(沿袭项目 1 的坑)

- Git Bash 中文一律走 Python + UTF-8,不用 curl 发中文
- 评估跑分 temperature=0;进 README 的数字必须全量真实跑出
- 踩坑笔记记 `notes/pitfalls.md`(问题→尝试→结论,3 行)
- GitHub 直连慢,下载用 `curl -C -` 断点续传加重试循环
