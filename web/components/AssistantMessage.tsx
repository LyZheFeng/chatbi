"use client";

import { useState } from "react";
import type { AskResponse, ToolStep } from "@/lib/types";
import ChartCard from "./ChartCard";
import Markdown from "./Markdown";
import ResultTable from "./ResultTable";
import Timeline from "./Timeline";

// 单条助手消息的呈现状态机:
//   running(agent 执行中,轨迹逐步亮)→ summary(结论分段打出)
//   → done(权威终态:结论 + 图表 + 解读 + 表格 + SQL/轨迹)| error(传输层失败,可重试)
// done 前的显示都是临时的;agent 优雅降级(error 字段)走 done,不是传输层 error。
export type AssistantState =
  | { phase: "running"; steps: ToolStep[] }
  | { phase: "summary"; steps: ToolStep[]; text: string }
  | { phase: "done"; resp: AskResponse }
  | { phase: "error"; message: string; retryQuestion: string };

function Chip({ tone, children }: { tone?: "acc" | "good" | "warn"; children: React.ReactNode }) {
  const cls =
    tone === "acc"
      ? "bg-[var(--acc-soft)] text-[#0b6e64]"
      : tone === "good"
        ? "bg-[#e3f7e9] text-[#177245]"
        : tone === "warn"
          ? "bg-[#fdf1d8] text-[#9a6700]"
          : "bg-[#eef2f5] text-[#4a5b66]";
  return (
    <span className={`inline-block rounded-full px-2.5 py-[3px] text-xs font-semibold ${cls}`}>{children}</span>
  );
}

function Badges({ resp }: { resp: AskResponse }) {
  const tok = resp.stats.llm_tokens ?? 0;
  const fail = resp.stats.sql_failures ?? 0;
  const refl = resp.stats.reflections ?? 0;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <Chip tone="acc">⏱ {resp.latency_ms.toLocaleString("en-US")} ms</Chip>
      <Chip tone="acc">🪜 {resp.steps.length} 步</Chip>
      {fail > 0 && <Chip tone="warn">🔁 SQL 重试 {fail}</Chip>}
      {refl > 0 && <Chip tone="warn">🤔 反思 {refl}</Chip>}
      {tok > 0 && <Chip>🧮 {tok.toLocaleString("en-US")} tokens</Chip>}
    </div>
  );
}

function fmtNum(v: unknown): string {
  if (typeof v === "number" && !Number.isInteger(v)) return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return Number(v).toLocaleString("en-US");
}

function CollapsibleSqlAndTrace({ resp }: { resp: AskResponse }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 overflow-hidden rounded-[10px] border border-[var(--line)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 bg-[#f6faf9] px-3 py-2 text-left text-[13px] font-semibold text-[#2c4440]"
      >
        <span>🔍 SQL 与执行轨迹</span>
        <span className={`text-[10px] text-[var(--muted)] transition-transform ${open ? "rotate-180" : ""}`}>▼</span>
      </button>
      {open && (
        <div className="border-t border-[var(--line)] bg-[#fcfefe] px-3 py-2.5">
          {resp.sql ? (
            <div className="mb-2">
              <div className="mb-1 text-[12px] font-bold text-[#33534d]">最终 SQL</div>
              <pre className="overflow-x-auto rounded-lg bg-[#0e2226] px-3 py-2.5 font-mono text-[12px] leading-relaxed text-[#d7e7e3]">
                {resp.sql}
              </pre>
            </div>
          ) : null}
          <div className="mb-1 text-[12px] font-bold text-[#33534d]">执行轨迹(共 {resp.steps.length} 步)</div>
          <Timeline steps={resp.steps} />
        </div>
      )}
    </div>
  );
}

export default function AssistantMessage({
  state,
  onRetry,
}: {
  state: AssistantState;
  onRetry: (question: string) => void;
}) {
  if (state.phase === "running") {
    return (
      <div>
        <div className="mb-2 flex items-center gap-2 text-sm text-[var(--muted)]">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--acc)] border-t-transparent" />
          agent 执行中:get_schema → execute_sql → final_answer …
        </div>
        {state.steps.length > 0 && <Timeline steps={state.steps} live />}
      </div>
    );
  }

  if (state.phase === "summary") {
    return (
      <div>
        <div className="rounded-xl border border-[#bfe5d7] bg-[#effaf4] px-3.5 py-2.5 text-[14.5px] leading-relaxed text-[#14532d]">
          <Markdown text={state.text} />
          <span className="stream-cursor" />
        </div>
        <div className="mt-2 mb-1 text-[12.5px] font-semibold text-[#33534d]">🔍 执行轨迹({state.steps.length} 步)</div>
        <Timeline steps={state.steps} />
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <div>
        <div className="rounded-lg border border-[#fecaca] bg-[#fef2f2] px-3.5 py-2.5 text-sm text-[#b91c1c]">
          {state.message}
        </div>
        <button
          type="button"
          onClick={() => onRetry(state.retryQuestion)}
          className="mt-2 rounded-[10px] border border-[#cfe0dc] bg-white px-3 py-1 text-sm text-[#0b6e64] transition-colors hover:border-[var(--acc)] hover:bg-[var(--acc-soft)]"
        >
          重试
        </button>
      </div>
    );
  }

  // done:权威终态,覆盖一切临时显示
  const { resp } = state;
  const single =
    resp.row_count === 1 && resp.columns.length === 1 && typeof resp.rows[0]?.[0] === "number";
  return (
    <div>
      {resp.error && (
        <div className="mb-2 rounded-lg border border-[#fecaca] bg-[#fef2f2] px-3.5 py-2.5 text-sm text-[#b91c1c]">
          未能完成分析:{resp.error}
        </div>
      )}
      {resp.summary && (
        <div className="rounded-xl border border-[#bfe5d7] bg-[#effaf4] px-3.5 py-2.5 text-[14.5px] leading-relaxed text-[#14532d]">
          <Markdown text={resp.summary} />
        </div>
      )}
      {single && (
        <div className="mt-2 flex items-baseline gap-3 rounded-xl border border-[var(--line)] bg-white px-4 py-3">
          <span className="text-[12px] text-[var(--muted)]">{resp.columns[0]}</span>
          <span className="text-2xl font-bold text-[#16303f]">{fmtNum(resp.rows[0][0])}</span>
        </div>
      )}
      {resp.row_count > 0 && !single && resp.chart_spec && (
        <ChartCard spec={resp.chart_spec} reading={resp.chart_reading} />
      )}
      {resp.row_count > 0 && !single && (
        <>
          <ResultTable columns={resp.columns} rows={resp.rows} />
          <div className="mt-1 text-right text-[11.5px] text-[var(--muted)]">{resp.row_count} 行</div>
        </>
      )}
      <Badges resp={resp} />
      <CollapsibleSqlAndTrace resp={resp} />
    </div>
  );
}
