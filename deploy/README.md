# CocoCV 蓝绿部署运维说明（Host PM2 + Nginx）

本目录提供宿主机 `pm2` + `Nginx` 双槽位零中断发布与秒级回滚方案（对应 Issue #108）。

## 架构概览

```
Client -> Nginx (cococv.cn)
             ├─ 静态资源 -> frontend/dist (原子软链 -> dist_releases/<release>)
             └─ /api/*   -> upstream cococv_backend (cococv-upstream.conf)
                              ├─ [blue ] 127.0.0.1:9001 (pm2: cococv-backend-blue)
                              └─ [green] 127.0.0.1:9002 (pm2: cococv-backend-green)
```

## 首次启用前置准备（一次性）

1. 在 Nginx 主配置加载的目录生成初始 upstream 文件（例如 `/etc/nginx/conf.d/cococv-upstream.conf`），先指向现有后端端口（如 `9000`）：
   ```nginx
   upstream cococv_backend {
       server 127.0.0.1:9000;
       keepalive 32;
   }
   ```
2. 参考 `deploy/nginx/cococv-site.snippet.conf`，把站点配置中的 `proxy_pass http://127.0.0.1:9000;` 改为 `proxy_pass http://cococv_backend;`。
3. 执行 `nginx -t && nginx -s reload` 确认原站点流量正常。

## 常用命令

```bash
# 查看当前生效槽位、端口、Commit SHA 与发布目录
./scripts/deploy-blue-green.sh status

# 预览将执行的蓝绿步骤（不改动任何文件或进程）
./scripts/deploy-blue-green.sh deploy --dry-run

# 执行蓝绿发布（自动拉取 main、构建前端、拉起备用槽位、探活校验、原子切流、排空停旧）
./scripts/deploy-blue-green.sh deploy

# 若当前工作区已手动 checkout 目标版本，可跳过 git fetch/reset：
./scripts/deploy-blue-green.sh deploy --skip-git

# 一键回滚至上一个健康槽位与前端构建产物
./scripts/deploy-blue-green.sh rollback
```

## 关键环境变量（可选覆盖）

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `COCOCV_BLUE_PORT` | `9001` | Blue 槽位监听端口 |
| `COCOCV_GREEN_PORT` | `9002` | Green 槽位监听端口 |
| `COCOCV_NGINX_UPSTREAM_FILE` | `/etc/nginx/conf.d/cococv-upstream.conf` | Nginx upstream 配置文件路径 |
| `COCOCV_DRAIN_SECONDS` | `15` | 切流后等待旧槽位排空的时间（秒） |
| `COCOCV_HEALTH_TIMEOUT` | `45` | 备用槽位 `/api/health/ready` 就绪超时（秒） |
| `COCOCV_KEEP_RELEASES` | `5` | `frontend/dist_releases` 保留的历史版本数量 |
| `COCOCV_UVICORN_WORKERS` | `2` | 每个后端槽位的 uvicorn worker 数量 |
