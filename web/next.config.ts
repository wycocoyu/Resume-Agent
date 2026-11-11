import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // 独立构建产物（.next/standalone/server.js），供 web/Dockerfile 多阶段镜像使用；
  // 本地 next dev / next start 与 Vercel 部署不受影响
  output: "standalone",
};

export default nextConfig;
