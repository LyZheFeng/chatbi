import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ChatBI · 电商订单分析",
  description: "中文提问 → 生成 SQL → 自愈执行 → 图表 + 解读 + 结论,数字全部来自本地执行",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full font-sans">{children}</body>
    </html>
  );
}
