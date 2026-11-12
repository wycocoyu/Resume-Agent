# ============================================================
# Resume-Agent 认证服务镜像（Next.js + BetterAuth）
# 基于 Next.js 独立构建（output: "standalone"）的多阶段部署：
# Stage 1: 安装依赖并构建出 .next/standalone 最小运行时
# Stage 2: 仅携带 server.js + 静态资源 + public 运行
#
# 构建上下文为 web/ 目录：
#   docker build -t resume-agent-web web/
# ============================================================

# ---------- Stage 1: 构建 ----------
FROM node:20-alpine AS builder

WORKDIR /app

# 先装依赖再拷源码，充分利用层缓存
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- Stage 2: 独立运行时 ----------
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# 非 root 运行
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs

# standalone 产物不含 .next/static 与 public，需单独拷贝
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
