import { describe, it, expect, vi } from "vitest";
import { createProxyApp } from "../src/index";

describe("packages/proxy: Strangler Fig Contract & Proxy Layer", () => {
  it("GET /health returns 200 with service metadata and wave 0", async () => {
    const app = createProxyApp({ targetUrl: "http://127.0.0.1:9000" });
    const res = await app.request("/health");
    expect(res.status).toBe(200);

    const data = await res.json();
    expect(data.status).toBe("ok");
    expect(data.service).toBe("cococv-strangler-proxy");
    expect(data.wave).toBe(0);
    expect(data.upstream).toBe("http://127.0.0.1:9000");
    expect(data.timestamp).toBeGreaterThan(0);
  });

  it("GET /api/health returns 200 with identical health payload", async () => {
    const app = createProxyApp({ targetUrl: "http://127.0.0.1:9000" });
    const res = await app.request("/api/health");
    expect(res.status).toBe(200);

    const data = await res.json();
    expect(data.status).toBe("ok");
    expect(data.wave).toBe(0);
  });

  it("POST /api/schema/validate-resume validates compliant resume data", async () => {
    const app = createProxyApp();
    const validResume = {
      name: "张三",
      contact: { email: "zhangsan@example.com", phone: "13800000000" },
      education: [{ title: "北京大学", date: "2018-2022" }],
      experience: [{ title: "阿里巴巴", date: "2022-2026" }],
    };

    const res = await app.request("/api/schema/validate-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(validResume),
    });

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.valid).toBe(true);
    expect(body.data.name).toBe("张三");
  });

  it("POST /api/schema/validate-resume rejects invalid schema structure", async () => {
    const app = createProxyApp();
    const invalidResume = {
      name: 12345, // 应该是 string
      education: "不是数组",
    };

    const res = await app.request("/api/schema/validate-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(invalidResume),
    });

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.valid).toBe(false);
    expect(Array.isArray(body.errors)).toBe(true);
  });

  it("POST /api/schema/validate-event validates valid SSE StreamEvent", async () => {
    const app = createProxyApp();
    const validEvent = {
      id: "evt_test_1",
      event_type: "text_delta",
      data: { delta: "正在生成简历..." },
      seq: 1,
    };

    const res = await app.request("/api/schema/validate-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(validEvent),
    });

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.valid).toBe(true);
    expect(body.data.event_type).toBe("text_delta");
  });

  it("proxies /api/resumes/list to upstream FastAPI mock", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ id: "res_1", title: "软件工程师" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const app = createProxyApp({
      targetUrl: "http://127.0.0.1:9000",
      fetchFn: mockFetch,
    });

    const res = await app.request("/api/resumes/list?limit=10", {
      method: "GET",
      headers: { Authorization: "Bearer token_abc" },
    });

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual([{ id: "res_1", title: "软件工程师" }]);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [callUrl, callOptions] = mockFetch.mock.calls[0];
    expect(callUrl).toBe("http://127.0.0.1:9000/api/resumes/list?limit=10");
    expect(callOptions.method).toBe("GET");
  });

  it("proxies SSE stream headers and body from upstream", async () => {
    const mockSSEStream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: thought\ndata: {}\n\n"));
        controller.close();
      },
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(mockSSEStream, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        },
      })
    );

    const app = createProxyApp({
      targetUrl: "http://127.0.0.1:9000",
      fetchFn: mockFetch,
    });

    const res = await app.request("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "优化简历" }),
    });

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("text/event-stream");
    const text = await res.text();
    expect(text).toContain("event: thought");
  });

  it("handles upstream connection failures with 502 Bad Gateway", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("Connection refused to 127.0.0.1:9000"));

    const app = createProxyApp({
      targetUrl: "http://127.0.0.1:9000",
      fetchFn: mockFetch,
    });

    const res = await app.request("/api/some-endpoint");
    expect(res.status).toBe(502);

    const body = await res.json();
    expect(body.error).toBe("Bad Gateway");
    expect(body.message).toContain("Connection refused");
  });
});
