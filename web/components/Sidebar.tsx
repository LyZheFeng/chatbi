"use client";

import { useEffect, useState } from "react";
import type { AskResponse, HealthInfo } from "@/lib/types";

const TABLES: [string, string][] = [
  ["geography", "国家/区域维表"],
  ["customers", "客户"],
  ["products", "商品"],
  ["orders", "订单"],
  ["order_items", "订单明细"],
];

// 侧栏:/health 轮询(15s)+ 数据概况 + 本次会话统计 + 清空对话
export default function Sidebar({
  apiBase,
  history,
  onClear,
  canClear,
}: {
  apiBase: string;
  history: AskResponse[]; // 已完成的回答(会话统计用)
  onClear: () => void;
  canClear: boolean;
}) {
  const [up, setUp] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const r = await fetch(`${apiBase}/health`, { signal: AbortSignal.timeout(5000) });
        const body = (await r.json()) as HealthInfo;
        if (alive) setUp(body.status === "ok");
      } catch {
        if (alive) setUp(false);
      }
    };
    void poll();
    const t = setInterval(poll, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [apiBase]);

  const done = history.filter((r) => r.error === null);
  const avgMs = done.length ? Math.round(done.reduce((s, r) => s + r.latency_ms, 0) / done.length) : 0;
  const tokens = history.reduce((s, r) => s + (r.stats.llm_tokens ?? 0), 0);

  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-white/[.06] bg-[linear-gradient(180deg,#0f2b46_0%,#0b2226_100%)] p-4 text-[#cfe0df] md:flex">
      <div className="mb-2 flex items-center text-[15px] font-bold text-white">
        <span
          className={`mr-2 inline-block h-2 w-2 rounded-full ${up ? "bg-[#34d399] shadow-[0_0_6px_rgba(52,211,153,.55)]" : "bg-[#f87171]"}`}
        />
        {up ? "服务在线" : "服务离线"}
      </div>

      <div className="mb-1 text-[13px] font-bold text-white">🗄️ 数据概况</div>
      <div className="mb-2">
        {TABLES.map(([t, label]) => (
          <div key={t} className="flex items-baseline justify-between gap-3 border-b border-dashed border-white/[.09] py-1.5 text-[13px]">
            <span className="font-mono text-[12px] text-[#9fc0ba]">{t}</span>
            <span className="text-right text-[12px] text-[#cfe3df]">{label}</span>
          </div>
        ))}
        <div className="pt-1.5 text-[11.5px] leading-relaxed text-[#8fb3ac]">
          Global Superstore · 2012–2015 · 注入 5 类确定性脏数据
        </div>
      </div>

      <div className="my-3 border-t border-white/[.12]" />
      <div className="mb-1 text-[13px] font-bold text-white">📊 本次会话</div>
      {done.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 text-center">
          <div className="rounded-[10px] border border-white/[.12] bg-white/[.05] px-2 py-1.5">
            <div className="text-lg font-bold text-white">{done.length}</div>
            <div className="text-[11px] text-[#8fb3ac]">提问</div>
          </div>
          <div className="rounded-[10px] border border-white/[.12] bg-white/[.05] px-2 py-1.5">
            <div className="text-lg font-bold text-white">{(avgMs / 1000).toFixed(1)}s</div>
            <div className="text-[11px] text-[#8fb3ac]">平均延迟</div>
          </div>
          {tokens > 0 && (
            <div className="col-span-2 text-[11px] text-[#8fb3ac]">累计 {tokens.toLocaleString("en-US")} tokens</div>
          )}
        </div>
      ) : (
        <p className="text-[12px] leading-relaxed text-[#8fb3ac]">还没有提问,从示例问题开始 👆</p>
      )}

      <button
        type="button"
        onClick={onClear}
        disabled={!canClear}
        className="mt-3 w-full rounded-[10px] border border-white/[.18] bg-white/[.07] px-3 py-1.5 text-sm text-[#e2efec] transition-colors hover:border-[var(--acc)] hover:bg-[rgba(0,150,135,.3)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        🗑 清空对话
      </button>

      <div className="mt-auto pt-4 text-[11px] leading-relaxed text-[#6f958d]">
        只读连接 · SQL 护栏 · 超时 5s · 自愈重试上限 3
        <br />
        chatbi · 本地运行
      </div>
    </aside>
  );
}
