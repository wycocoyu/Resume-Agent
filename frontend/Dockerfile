# ============================================================
# Resume-Agent 前端镜像：多阶段构建
# Stage 1: Node 构建 Vite 生产包
# Stage 2: Nginx 托管静态资源并反代后端 API
#
# 构建上下文为 frontend/ 目录：
#   docker build -t resume-agent-frontend frontend/
# ============================================================

# ---------- Stage 1: 构建静态资源 ----------
FROM node:20-alpine AS builder

WORKDIR /app

# 先装依赖再拷源码，充分利用层缓存
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- Stage 2: Nginx 托管 ----------
FROM nginx:alpine

# 移除默认站点配置，替换为本项目配置（含 /api/ 反代与 SSE 透传）
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Vite 构建产物位于 /app/dist
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
