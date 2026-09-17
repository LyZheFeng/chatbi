"use client";

import ReactMarkdown from "react-markdown";

// 结论渲染:纯 Markdown(chatbi 无引用角标,不需要 rehype 插件)
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none prose-p:my-1.5 prose-pre:my-2 prose-code:before:content-none prose-code:after:content-none prose-code:rounded prose-code:bg-[#eef2f5] prose-code:px-1 prose-code:py-0.5 prose-code:text-[0.85em] prose-code:font-normal">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}
