import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 本机用 127.0.0.1 访问 dev server 时,Next 默认拦截跨源 dev 资源(HMR/chunk),
  // 页面停在未水合状态(按钮无响应);放行本机两种主机名写法
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
