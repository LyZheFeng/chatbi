"use client";

import type { AskResponse } from "@/lib/types";

// 结果表:与 Streamlit st.dataframe 对齐(隐藏索引、全量展示);数字右对齐加千分位
// 数值口径与后端 _fmt_num 一致:整数 ,d;小数 ,.2f

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v)
      ? v.toLocaleString("en-US")
      : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return String(v);
}

const isNum = (v: unknown) => typeof v === "number";

export default function ResultTable({ columns, rows }: Pick<AskResponse, "columns" | "rows">) {
  if (columns.length === 0) return null;
  return (
    <div className="mt-2 max-h-[420px] overflow-auto rounded-xl border border-[var(--line)] bg-white shadow-[0_1px_3px_rgba(18,51,46,.05)]">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-[1] bg-[#f0f6f4]">
          <tr>
            {columns.map((c) => (
              <th key={c} className="border-b border-[var(--line)] px-3 py-2 text-left font-semibold text-[#33534d]">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="odd:bg-white even:bg-[#fafdfc]">
              {row.map((v, j) => (
                <td
                  key={j}
                  className={`border-b border-[#eef3f2] px-3 py-[7px] whitespace-nowrap ${
                    isNum(v) ? "text-right font-mono text-[12px] tabular-nums text-[#16303f]" : "text-[#3b4f4b]"
                  }`}
                >
                  {fmt(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
