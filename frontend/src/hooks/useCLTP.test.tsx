// @vitest-environment jsdom

import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCLTP, type UseCLTPResult } from "./useCLTP";
import {
  streamAgent,
  type AgentStreamHandlers,
} from "@/services/agentStream";

vi.mock("@/lib/runtimeEnv", () => ({
  getApiBaseUrl: () => "http://test.local",
  isAgentEnabled: () => true,
  isLocalDevAuthEnabled: () => false,
}));

vi.mock("@/services/agentStream", () => ({
  streamAgent: vi.fn(),
}));

(globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT: boolean;
}).IS_REACT_ACT_ENVIRONMENT = true;

function Harness({ onChange }: { onChange: (value: UseCLTPResult) => void }) {
  const value = useCLTP({ conversationId: "conv-test" });
  useEffect(() => onChange(value), [onChange, value]);
  return null;
}

describe("useCLTP presentation handoff", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("keeps a completed response mounted until presentation explicitly finalizes", async () => {
    vi.mocked(streamAgent).mockImplementation(async (_payload, handlers) => {
      handlers!.onEvent?.({
        id: "answer-1",
        type: "answer",
        data: { content: "嘿～我是 coco。", is_complete: true },
        timestamp: "test",
        runId: "conv-test:run-1",
        seq: 1,
      });
      handlers!.onEvent?.({
        id: "done-1",
        type: "done",
        data: {},
        timestamp: "test",
        runId: "conv-test:run-1",
        seq: 2,
      });
      handlers!.onEvent?.({
        id: "done-synthetic",
        type: "done",
        data: {},
        timestamp: "test",
        runId: "conv-test:run-1",
        seq: 3,
      });
      handlers!.onDone?.();
    });

    let latest: UseCLTPResult | null = null;
    const onChange = (value: UseCLTPResult) => {
      latest = value;
    };
    act(() => root.render(<Harness onChange={onChange} />));

    await act(async () => {
      await latest!.sendMessage("你好");
    });

    expect(latest!.currentRunState.response.sourceText).toBe("嘿～我是 coco。");
    expect(latest!.answerCompleteCount).toBe(1);
    expect(latest!.isProcessing).toBe(true);

    act(() => latest!.finalizeStream());
    expect(latest!.isProcessing).toBe(false);
    expect(latest!.currentRunState.response.sourceText).toBe("");
  });

  it("does not let an aborted stale request clear a newer active request", async () => {
    const pending: Array<{
      handlers: AgentStreamHandlers;
      resolve: () => void;
    }> = [];
    vi.mocked(streamAgent).mockImplementation(
      (_payload, handlers) =>
        new Promise<void>((resolve) => {
          pending.push({ handlers: handlers ?? {}, resolve });
        }),
    );

    let latest: UseCLTPResult | null = null;
    const onChange = (value: UseCLTPResult) => {
      latest = value;
    };
    act(() => root.render(<Harness onChange={onChange} />));

    let firstRequest!: Promise<void>;
    await act(async () => {
      firstRequest = latest!.sendMessage("第一条");
      await Promise.resolve();
    });
    let secondRequest!: Promise<void>;
    await act(async () => {
      secondRequest = latest!.sendMessage("第二条");
      await Promise.resolve();
    });
    expect(pending).toHaveLength(2);

    await act(async () => {
      pending[0].resolve();
      await firstRequest;
    });
    expect(latest!.isProcessing).toBe(true);

    await act(async () => {
      pending[1].handlers.onEvent?.({
        id: "answer-2",
        type: "answer",
        data: { content: "第二条回复", is_complete: true },
        timestamp: "test",
        runId: "conv-test:run-2",
        seq: 1,
      });
      pending[1].handlers.onEvent?.({
        id: "done-2",
        type: "done",
        data: {},
        timestamp: "test",
        runId: "conv-test:run-2",
        seq: 2,
      });
      pending[1].handlers.onDone?.();
      pending[1].resolve();
      await secondRequest;
    });
    expect(latest!.currentRunState.response.sourceText).toBe("第二条回复");
    expect(latest!.isProcessing).toBe(true);
  });

  it("exposes structured business results from the same canonical run", async () => {
    vi.mocked(streamAgent).mockImplementation(async (_payload, handlers) => {
      handlers!.onEvent?.({
        id: "tool-result-diagnosis",
        type: "tool_result",
        data: {
          tool: "cv_analyzer_agent",
          tool_call_id: "call-diagnosis",
          step_id: 2,
          result: "diagnosis ready",
          structured_data: {
            type: "resume_diagnosis",
            overall_score: 82,
          },
        },
        timestamp: "test",
        runId: "conv-test:run-1",
        seq: 1,
      });
      handlers!.onEvent?.({
        id: "done-diagnosis",
        type: "done",
        data: {},
        timestamp: "test",
        runId: "conv-test:run-1",
        seq: 2,
      });
      handlers!.onDone?.();
    });

    let latest: UseCLTPResult | null = null;
    act(() =>
      root.render(
        <Harness
          onChange={(value) => {
            latest = value;
          }}
        />,
      ),
    );
    await act(async () => {
      await latest!.sendMessage("诊断简历");
    });

    expect(latest!.currentRunState.artifacts).toEqual([
      expect.objectContaining({
        kind: "resume_diagnosis",
        payload: expect.objectContaining({ overall_score: 82 }),
      }),
    ]);
  });

  it("records transport failures in the canonical run", async () => {
    vi.mocked(streamAgent).mockImplementation(async (_payload, handlers) => {
      const error = new Error("SSE request failed: 404 Not Found");
      handlers?.onError?.(error);
      throw error;
    });

    let latest: UseCLTPResult | null = null;
    act(() =>
      root.render(
        <Harness
          onChange={(value) => {
            latest = value;
          }}
        />,
      ),
    );

    await act(async () => {
      await latest!.sendMessage("你好");
    });

    expect(latest!.currentRunState).toEqual(
      expect.objectContaining({
        sourceStatus: "failed",
        error: "SSE request failed: 404 Not Found",
      }),
    );
    expect(latest!.isProcessing).toBe(false);
  });

  it("preserves a typed user cancellation instead of resetting the run", () => {
    let latest: UseCLTPResult | null = null;
    act(() =>
      root.render(
        <Harness
          onChange={(value) => {
            latest = value;
          }}
        />,
      ),
    );

    act(() => latest!.cancelStream("user_stop", "已停止生成。"));

    expect(latest!.currentRunState).toEqual(
      expect.objectContaining({
        sourceStatus: "cancelled",
        cancelReason: "user_stop",
        error: "已停止生成。",
      }),
    );
  });
});
