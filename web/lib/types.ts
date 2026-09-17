// 与后端 app/schemas.py 逐字段对齐(pydantic ↔ TS 契约)

export interface ToolStep {
  step: number;
  tool: string; // get_schema | execute_sql | final_answer
  args: Record<string, unknown>;
  ok: boolean;
  detail: string; // 结果摘要或错误信息(截断 ~300 字符)
}

export interface AskResponse {
  question: string;
  summary: string; // final_answer 的中文结论
  sql: string | null; // 展示用 SQL
  columns: string[];
  rows: unknown[][];
  row_count: number;
  chart_spec: Record<string, unknown> | null; // Vega-Lite 配置(UI 与接口共用一份)
  chart_reading: string; // "怎么读这张图"的模板化解读
  steps: ToolStep[];
  error: string | null; // 优雅降级时的失败原因(不编造)
  latency_ms: number;
  stats: Record<string, number>; // sql_attempts / sql_failures / reflections / llm_tokens
}

// GET /health 响应(侧栏探活)
export interface HealthInfo {
  status: string;
}

// SSE 事件载荷:sources*(每步累计)→ delta*(结论分段)→ done | error
export interface SourcesPayload {
  steps: ToolStep[]; // 累计轨迹,直接整体替换
}
export interface DeltaPayload {
  text: string;
}
export interface ErrorPayload {
  message: string;
}
