"use client";

import { useEffect, useRef } from "react";
import type { VisualizationSpec } from "vega-embed";

// Vega-Lite 图表卡:vega-embed 动态导入(首屏不打包 ~1MB 的 vega);
// 白底卡片是刻意的——spec 已钉死深色文字(#262730),深色主题下 Vega 黑字不可读的教训

const CHART_LABEL: Record<string, string> = {
  bar: "柱状图",
  hbar: "条形图",
  line: "折线图",
  arc: "饼图",
  point: "散点图",
};

function chartTypeLabel(spec: Record<string, unknown>): string {
  const mark = (spec.mark as { type?: string } | undefined)?.type
    ?? ((spec.layer as { mark?: { type?: string } }[] | undefined)?.[0]?.mark?.type);
  return CHART_LABEL[mark ?? ""] ?? "图表";
}

export default function ChartCard({
  spec,
  reading,
}: {
  spec: Record<string, unknown>;
  reading: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let disposed = false;
    let view: { finalize: () => void } | null = null;
    (async () => {
      const vegaEmbed = (await import("vega-embed")).default;
      if (disposed || !ref.current) return;
      // 后端 spec 不带 width(历史原因沿袭 Streamlit 的 use_container_width),
      // 前端注入 container 宽度自适应;顶部 padding 加大——vega-lite 6 运行时下
      // config.padding=22 不足以容纳标题,顶部会被 viewBox 裁掉一截(其余原样渲染)
      const result = await vegaEmbed(
        ref.current,
        {
          ...spec,
          width: "container",
          padding: { top: 46, left: 22, right: 22, bottom: 22 },
        } as VisualizationSpec,
        {
          actions: false,
          renderer: "svg",
        },
      );
      view = result.view ?? null;
    })();
    return () => {
      disposed = true;
      view?.finalize();
    };
  }, [spec]);

  return (
    <div className="mt-2">
      <div className="mb-1 text-[12px] text-[var(--muted)]">
        📈 自动选型:<b className="text-[#33534d]">{chartTypeLabel(spec)}</b>(选型与数字全部来自本地执行结果)
      </div>
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-white p-1 shadow-[0_1px_3px_rgba(18,51,46,.05)]">
        <div ref={ref} />
      </div>
      {reading && (
        <div className="mt-1.5 rounded-xl border border-[#d7e6f4] bg-[#f2f8fd] px-3.5 py-2.5 text-[13px] leading-relaxed text-[#2c4a63]">
          <b>📖 怎么读这张图</b>:{reading}
        </div>
      )}
    </div>
  );
}
