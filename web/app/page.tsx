"use client";

import { useEffect, useRef, useState } from "react";
import AssistantMessage, { type AssistantState } from "@/components/AssistantMessage";
import Sidebar from "@/components/Sidebar";
import { streamSse } from "@/lib/sse";
import type { AskResponse, DeltaPayload, ErrorPayload, SourcesPayload } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? ""; // 后端 Settings.api_key 非空时必填

const SAMPLE_QUESTIONS = [
  "2014 年销售额最高的 5 个国家是哪些?",
  "各大类(Furniture/Office Supplies/Technology)的销售额和利润对比",
  "亚太市场按月销售额趋势",
  "各市场销售额占比",
  "哪些明细的数量为负或为 0?",
];

type Turn =
  | { id: number; role: "user"; content: string }
  | { id: number; role: "assistant"; state: AssistantState };

let nextId = 1;

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const hasHistory = turns.length > 0;
  const history = turns.flatMap((t) => (t.role === "assistant" && t.state.phase === "done" ? [t.state.resp] : []));

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const patchLast = (updater: (s: AssistantState) => AssistantState) => {
    setTurns((prev) => {
      const last = prev[prev.length - 1];
      if (!last || last.role !== "assistant") return prev;
      return [...prev.slice(0, -1), { ...last, state: updater(last.state) }];
    });
  };

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setInput("");
    const assistantId = nextId++;
    setTurns((prev) => [
      ...prev,
      { id: nextId++, role: "user", content: q },
      { id: assistantId, role: "assistant", state: { phase: "running", steps: [] } },
    ]);

    const abort = new AbortController();
    abortRef.current = abort;
    const headers = API_KEY ? { "X-API-Key": API_KEY } : undefined;
    const url = `${API_BASE}/ask/stream?q=${encodeURIComponent(q)}`;
    try {
      await streamSse(
        url,
        (event, data) => {
          if (event === "sources") {
            // 累计轨迹整体替换(漏帧自愈)
            const { steps } = data as SourcesPayload;
            patchLast((s) =>
              s.phase === "running"
                ? { phase: "running", steps }
                : s.phase === "summary"
                  ? { ...s, steps }
                  : s,
            );
          } else if (event === "delta") {
            const { text } = data as DeltaPayload;
            patchLast((s) =>
              s.phase === "running"
                ? { phase: "summary", steps: s.steps, text }
                : s.phase === "summary"
                  ? { ...s, text: s.text + text }
                  : s,
            );
          } else if (event === "done") {
            patchLast(() => ({ phase: "done", resp: data as AskResponse }));
          } else if (event === "error") {
            const { message } = data as ErrorPayload;
            patchLast(() => ({ phase: "error", message, retryQuestion: q }));
          }
        },
        abort.signal,
        headers,
      );
      // 流正常结束但没有 done(异常截断):标错,不留卡在流式态的消息
      patchLast((s) =>
        s.phase === "done" || s.phase === "error"
          ? s
          : { phase: "error", message: "连接中断,分析结果不完整。", retryQuestion: q },
      );
    } catch (e) {
      const msg = e instanceof Error && e.name === "AbortError"
        ? "已中断本次提问。"
        : `分析失败:agent 或数据库服务不可用(${e instanceof Error ? e.message : "未知错误"}),请稍后重试。`;
      patchLast((s) => ({ phase: "error", message: msg, retryQuestion: q }));
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  const clearAll = () => {
    abortRef.current?.abort();
    setTurns([]);
  };

  return (
    <div className="flex h-dvh">
      <Sidebar apiBase={API_BASE} history={history} onClear={clearAll} canClear={turns.length > 0} />
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="mx-auto w-full max-w-[860px] flex-1 overflow-y-auto px-4 pb-6">
          {/* hero */}
          <div className={`pt-5 text-center ${hasHistory ? "pb-1" : "pb-2"}`}>
            <div className="mb-1.5 inline-block rounded-full border border-[#bcd9ec] bg-[#eaf4fb] px-3 py-[3px] text-[11px] font-bold tracking-[2px] text-[#1d4e89]">
              GLOBAL SUPERSTORE · 中文问数 · AGENT
            </div>
            <h1
              className={`bg-gradient-to-r from-[#1d4e89] from-10% to-[#009687] to-95% bg-clip-text font-extrabold tracking-wide text-transparent ${
                hasHistory ? "text-xl" : "text-[2.05rem]"
              }`}
            >
              ChatBI · 电商订单分析
            </h1>
            <p className={`mt-1 text-[var(--muted)] ${hasHistory ? "text-[13px]" : "text-sm"}`}>
              中文提问 → 生成 SQL → 自愈执行 → 图表 + 解读 + 结论 · 数字全部来自本地执行 · 过程轨迹全程可见
            </p>
          </div>

          {!hasHistory && (
            <>
              <div className="mt-3 rounded-2xl border border-dashed border-[#c9d6d3] bg-white/80 px-5 py-4 text-sm leading-relaxed text-[#3f5753]">
                👋 我是 <b>ChatBI 数据分析 agent</b>。我会先看表结构、写 SQLite 查询、自检修正,再给你图表和结论——每个数字都来自本地执行,不编造;查询失败会如实降级说明。
              </div>
              <p className="mt-4 text-sm text-[var(--muted)]">不妨从这些问题开始:</p>
              <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {SAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => ask(q)}
                    className="rounded-xl border border-[#cfe0dc] bg-white px-3.5 py-2 text-left text-sm text-[#0b6e64] transition-colors hover:border-[var(--acc)] hover:bg-[var(--acc-soft)]"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </>
          )}

          {/* 对话流 */}
          <div className="mt-4">
            {turns.map((turn) =>
              turn.role === "user" ? (
                <div
                  key={turn.id}
                  className="mb-4 rounded-2xl border border-[#cfe4f0] bg-gradient-to-br from-[#eef5fb] to-[#f0f8f6] px-4 py-3 shadow-[0_1px_3px_rgba(18,51,46,.05)]"
                >
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-[#1d4e89]">
                    <span className="inline-block h-4 w-4 rounded-full bg-[#1d4e89] text-center text-[10px] leading-4 text-white">我</span>
                    提问
                  </div>
                  <div className="text-[15px] leading-relaxed">{turn.content}</div>
                </div>
              ) : (
                <div
                  key={turn.id}
                  className="mb-4 rounded-2xl border border-[var(--line)] bg-white px-4 py-3 shadow-[0_1px_3px_rgba(18,51,46,.05)]"
                >
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-[var(--acc)]">
                    <span className="inline-block h-4 w-4 rounded-full bg-[var(--acc)] text-center text-[10px] leading-4 text-white">📊</span>
                    助手
                  </div>
                  <AssistantMessage
                    state={turn.state}
                    onRetry={(q) => {
                      // 重试:去掉本轮的 user+assistant,重新提问
                      setTurns((prev) => prev.slice(0, Math.max(0, prev.length - 2)));
                      void ask(q);
                    }}
                  />
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* 输入区 */}
        <div className="sticky bottom-0 border-t border-[var(--line)] bg-[linear-gradient(180deg,rgba(251,253,253,.85),#fbfdfd)] px-4 py-3 backdrop-blur">
          <div className="mx-auto flex w-full max-w-[860px] items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void ask(input);
              }}
              placeholder="用中文问一个数据问题,例如:亚太市场按月销售额趋势"
              disabled={busy}
              maxLength={500}
              className="min-w-0 flex-1 rounded-xl border border-[#cfe0dc] bg-white px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-[var(--acc)] disabled:opacity-60"
            />
            <button
              type="button"
              onClick={() => void ask(input)}
              disabled={busy || !input.trim()}
              className="rounded-xl bg-[var(--acc)] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#007a6d] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "分析中…" : "提问"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
