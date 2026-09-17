"use client";

import type { ToolStep } from "@/lib/types";

// agent 执行轨迹可视化:每个 tool_call 一站(编号 → 工具名 → 参数 → 结果摘要)
// live=true 时在流式过程中展示(最新步骤高亮脉冲 + 尾部等待态);done 后静态呈现

const TOOL_LABELS: Record<string, string> = {
  get_schema: "查表结构",
  execute_sql: "执行 SQL",
  final_answer: "得出结论",
};

const TOOL_STYLE: Record<string, string> = {
  get_schema: "bg-[#e8f0fb] text-[#1d4e89]",
  execute_sql: "bg-[var(--acc-soft)] text-[#0b6e64]",
  final_answer: "bg-[#e3f7e9] text-[#177245]",
};

function StepArgs({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <div className="mt-1 font-mono text-[11px] leading-relaxed text-[#4a5b66]">
      {entries.map(([k, v]) => (
        <div key={k} className="break-all">
          <span className="text-[#7d8f9a]">{k}:</span> {String(v)}
        </div>
      ))}
    </div>
  );
}

export default function Timeline({ steps, live = false }: { steps: ToolStep[]; live?: boolean }) {
  if (steps.length === 0) return null;
  return (
    <ol className="relative ml-1 border-l-2 border-[#d5e3e0] pl-0">
      {steps.map((s, i) => {
        const isLast = i === steps.length - 1;
        return (
          <li key={s.step} className="relative py-1.5 pl-5">
            {/* 编号圆点压在竖线上 */}
            <span
              className={`absolute -left-[13px] top-2.5 flex h-[22px] w-[22px] items-center justify-center rounded-full text-[11px] font-bold ${
                s.ok ? "bg-[var(--acc)] text-white" : "bg-[#dc2626] text-white"
              } ${live && isLast ? "step-live" : ""}`}
            >
              {s.step}
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={`rounded-full px-2 py-[2px] text-[11px] font-semibold ${
                  TOOL_STYLE[s.tool] ?? "bg-[#eef2f5] text-[#4a5b66]"
                }`}
              >
                {TOOL_LABELS[s.tool] ?? s.tool}
              </span>
              <code className="text-[11px] text-[#8aa09b]">{s.tool}</code>
              {!s.ok && <span className="text-[11px] font-semibold text-[#dc2626]">✗ 失败(已回传模型修正)</span>}
            </div>
            <StepArgs args={s.args} />
            {s.detail && (
              <div className="mt-0.5 line-clamp-3 whitespace-pre-wrap text-[11.5px] leading-relaxed text-[#7d8f9a]">
                {s.detail}
              </div>
            )}
          </li>
        );
      })}
      {live && (
        <li className="relative py-1.5 pl-5">
          <span className="absolute -left-[9px] top-3 inline-block h-2 w-2 rounded-full bg-[#b8ccc8]" />
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted)]">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--acc)] border-t-transparent" />
            规划下一步…
          </div>
        </li>
      )}
    </ol>
  );
}
