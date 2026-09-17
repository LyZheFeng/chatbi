# chatbi 前端(Next.js)

ChatBI 电商订单分析的正式前端:SSE 流式渲染 + agent 轨迹可视化 + Vega-Lite 图表。替代 Streamlit 版(`app/ui.py`)。

## 本地开发

```bash
# 1) 起后端(仓库根;端口 8010,与 rag-qa 的 8000 错开,两前端可同时开)
uvicorn app.api:app --port 8010

# 2) 起前端
cd web
npm install
npm run dev        # http://localhost:3000
```

- 后端地址用 `NEXT_PUBLIC_API_BASE` 覆盖(见 `.env.local`);
- 后端启用鉴权时(`Settings.api_key` 非空),在 `.env.local` 的 `NEXT_PUBLIC_API_KEY` 填同值,前端请求自动带 `X-API-Key` 头(`NEXT_PUBLIC_` 前缀会打进浏览器包,内网演示够用;要隐藏 key 走 Next.js 服务端路由代理,见工作流阶段 5);
- 跨域来源在后端 `.env` 的 `CORS_ORIGINS` 配置。

## 结构

- `app/page.tsx` — 对话页状态机(running → summary → done/error),消费 `/ask/stream`
- `components/AssistantMessage.tsx` — 单条助手消息状态机:轨迹直播 → 结论打字机 → 权威终态(结论/图表/表格/徽章/SQL)
- `components/Timeline.tsx` — agent 执行轨迹可视化(每工具调用一站,失败步骤标红)
- `components/ChartCard.tsx` — vega-embed 渲染 `chart_spec`(动态导入,白底卡片 + 自动选型标签 + 解读)
- `components/ResultTable.tsx` — 结果表格(数字右对齐千分位,口径同后端 `_fmt_num`)
- `components/Sidebar.tsx` — `/health` 轮询、数据概况、会话统计、清空对话
- `lib/types.ts` — 与后端 `app/schemas.py` 逐字段对齐的 TS 契约
- `lib/sse.ts` — fetch + ReadableStream 的 SSE 解析(EventSource 不支持自定义头)

## SSE 事件协议(与后端 `app/api.py` 对齐)

```
event: sources  → {"steps": ToolStep[]}      agent 每执行完一步推一次累计轨迹,前端整体替换
event: delta    → {"text": "..."}            结论分段增量(服务端按句切分),追加显示
event: done     → AskResponse                权威终态,前端以此覆盖显示(含 chart_spec/chart_reading)
event: error    → {"message"}                传输层错误收拢(LLM 繁忙/未预期异常);agent 优雅降级走 done.error
```

## 构建

```bash
npm run build     # 含 TypeScript 严格检查
npm start
```
