import { Hono } from "hono";
import { ResumeDataSchema, StreamEventSchema } from "@cococv/schema";

export interface ProxyAppOptions {
  /**
   * 上游 FastAPI 目标服务基础 URL，默认 http://127.0.0.1:9000
   */
  targetUrl?: string;
  /**
   * 自定义 fetch 函数，便于测试注入
   */
  fetchFn?: typeof fetch;
}

/**
 * 创建 CocoCV Strangler Fig TypeScript 契约与反向代理服务
 */
export function createProxyApp(options: ProxyAppOptions = {}) {
  const targetUrl = options.targetUrl || "http://127.0.0.1:9000";
  const fetchFn = options.fetchFn || fetch;
  const app = new Hono();

  // 1. 健康检查探针 (Health Check)
  app.get("/health", (c) => {
    return c.json({
      status: "ok",
      service: "cococv-strangler-proxy",
      wave: 0,
      timestamp: Date.now(),
      upstream: targetUrl,
    });
  });

  app.get("/api/health", (c) => {
    return c.json({
      status: "ok",
      service: "cococv-strangler-proxy",
      wave: 0,
      timestamp: Date.now(),
      upstream: targetUrl,
    });
  });

  // 2. 契约校验端点: 简历数据验证
  app.post("/api/schema/validate-resume", async (c) => {
    try {
      const body = await c.req.json();
      const result = ResumeDataSchema.safeParse(body);
      if (!result.success) {
        return c.json(
          {
            valid: false,
            errors: result.error.issues,
          },
          400
        );
      }
      return c.json({
        valid: true,
        data: result.data,
      });
    } catch (err: any) {
      return c.json(
        {
          valid: false,
          error: "Invalid JSON payload",
          message: err?.message || String(err),
        },
        400
      );
    }
  });

  // 3. 契约校验端点: SSE 流式事件验证
  app.post("/api/schema/validate-event", async (c) => {
    try {
      const body = await c.req.json();
      const result = StreamEventSchema.safeParse(body);
      if (!result.success) {
        return c.json(
          {
            valid: false,
            errors: result.error.issues,
          },
          400
        );
      }
      return c.json({
        valid: true,
        data: result.data,
      });
    } catch (err: any) {
      return c.json(
        {
          valid: false,
          error: "Invalid JSON payload",
          message: err?.message || String(err),
        },
        400
      );
    }
  });

  // 4. 绞杀反向代理: 将所有 /api/* 请求透传至上游 FastAPI
  app.all("/api/*", async (c) => {
    const incomingUrl = new URL(c.req.url);
    const upstreamTarget = new URL(
      incomingUrl.pathname + incomingUrl.search,
      targetUrl
    );

    // 复制请求头并移除 host 等冲突头
    const headers = new Headers(c.req.raw.headers);
    headers.delete("host");

    const reqMethod = c.req.method.toUpperCase();
    const hasBody = !["GET", "HEAD"].includes(reqMethod);

    try {
      const upstreamResponse = await fetchFn(upstreamTarget.toString(), {
        method: reqMethod,
        headers,
        body: hasBody ? c.req.raw.body : undefined,
        // @ts-expect-error duplex required for streaming in Node fetch
        duplex: hasBody ? "half" : undefined,
      });

      // 组装并转发上游响应
      const resHeaders = new Headers(upstreamResponse.headers);
      return new Response(upstreamResponse.body, {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: resHeaders,
      });
    } catch (err: any) {
      return c.json(
        {
          error: "Bad Gateway",
          message: `Failed to proxy request to upstream: ${err?.message || String(err)}`,
          upstream: upstreamTarget.toString(),
        },
        502
      );
    }
  });

  return app;
}

export default createProxyApp();
