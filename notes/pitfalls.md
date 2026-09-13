# 踩坑笔记(问题 → 尝试 → 结论)

## 2026-09-13 · Day 15-16

- **GitHub 直连慢且频繁断流** → curl 下载 246KB 数据集断 3 次 → `curl -C -` 断点续传 + 重试循环 3 分钟内补完;HEAD 探测经常被吞,别指望 `-I` 判断大小。
- **Global Superstore 美国拆 4 个 region,country 做主键必撞** → 第一版 geography(country PK)插入报 UNIQUE 冲突 → 改 (country, region) 复合主键,customers 带 country+region 关联;"国家→唯一区域"的直觉在这份数据上不成立。
- **SQLite 没有独立 COMMENT 语法,列注释会丢?** → 不会:DDL 原文(含 `-- 中文注释`)整个存进 sqlite_master.sql,`get_schema` 直接 `SELECT sql FROM sqlite_master` 读回,模型看到的就是带注释的建表语句,零额外元数据表。
- **脏数据注入规则在同一条明细上撞车** → row_id 58 同时命中 quantity=0 / quantity=-2 / sales=NULL 三条规则,5 行预算只脏了 3 行 → 规则改成互相排除已命中行;教训:确定性注入也要断言"victim 不重叠"。
- **Qwen3.8-27B(vLLM)原生 function calling 可用** → 探测脚本确认 tool_calls 正常返回,`enable_thinking: False` 时 content 为空、意图全在 tool_calls 里 → agent 循环用原生协议,不走 JSON 模拟;但要注意"空 content + 无 tool_calls"要和"模型真在说话"区分,前者提醒一次,连续两次才降级。
- **模型第一枪就打偏枚举值(APAC ≠ Asia Pacific)** → 未做约束时它自己查了一遍 market 枚举再改 SQL(5 步完成)→ 错误信息/空结果原样回传就够了,模型的自愈倾向比预想强;Day 17-18 在此基础上做正式的反思与重试上限,并量化开关对比。
