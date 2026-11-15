import { afterEach, describe, expect, it, vi } from "vitest";

import { parseAgentStreamBlock, streamAgent } from "./agentStream";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseAgentStreamBlock", () => {
  it("rejects legacy frames that do not contain the canonical envelope", () => {
    expect(
      parseAgentStreamBlock(
        'id: legacy\ndata: {"type":"thought","content":"legacy"}',
      ),
    ).toBeNull();
  });

  it("unwraps the SSE transport frame and exposes one canonical event envelope", () => {
    const event = parseAgentStreamBlock(
      [
        "id: transport-id",
        "event: tool_progress",
        'data: {"data":{"id":"event-id","type":"tool_progress","run_id":"run-1","seq":7,"data":{"tool":"cv_analyzer_agent","stage":"evidence","progress":50}}}',
      ].join("\n"),
    );

    expect(event).toEqual({
      id: "event-id",
      type: "tool_progress",
      data: {
        tool: "cv_analyzer_agent",
        stage: "evidence",
        progress: 50,
      },
      timestamp: expect.any(String),
      runId: "run-1",
      seq: 7,
    });
  });

  it("parses the final buffered event even without a trailing SSE blank line", async () => {
    const frame = [
      "id: transport-done",
      "event: done",
      'data: {"data":{"id":"event-done","type":"done","run_id":"run-1","seq":8,"data":{}}}',
    ].join("\n");
    const bytes = new TextEncoder().encode(frame);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];

    await streamAgent(
      { message: "测试", run_id: "run-1" },
      { onEvent: (event) => events.push(event.type) },
    );

    expect(events).toEqual(["done"]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/agent/stream"),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("fails a truncated stream instead of fabricating a canonical done event", async () => {
    const frame = [
      "id: transport-answer",
      "event: answer",
      'data: {"data":{"id":"event-answer","type":"answer","run_id":"run-1","seq":1,"data":{"content":"未完成"}}}',
      "",
      "",
    ].join("\n");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    const events: string[] = [];
    const onError = vi.fn();

    await expect(
      streamAgent(
        { message: "测试", run_id: "run-1" },
        { onEvent: (event) => events.push(event.type), onError },
      ),
    ).rejects.toThrow("收到真实 done 事件前结束");

    expect(events).toEqual(["answer"]);
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
