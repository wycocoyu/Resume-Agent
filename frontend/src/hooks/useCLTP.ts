/**
 * useCLTP (Simplified)
 *
 * 彻底移除 CLTP 会话层，改为直接消费 /api/agent/stream SSE。
 * 保持原 Hook 对外返回结构，降低页面改动成本。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { SSEEvent } from "@/transports/SSETransport";
import { getApiBaseUrl, isAgentEnabled } from "@/lib/runtimeEnv";
import { getAuthHeaders } from "@/lib/authHeaders";
import { streamAgent, type AgentStreamEvent } from "@/services/agentStream";
import { createAgentEventAdapter } from "@/agent-presentation/AgentEventAdapter";
import {
  createConversationRunState,
  reduceConversationRun,
} from "@/agent-presentation/ConversationRunReducer";
import type { ConversationRunState } from "@/agent-presentation/model";
import type { RunCancelReason } from "@/agent-presentation/events";

function normalizeText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

function extractStreamErrorMessage(event: AgentStreamEvent): string {
  const direct =
    normalizeText(event.data?.content) ||
    normalizeText(event.data?.error_details) ||
    normalizeText(event.data?.error_message) ||
    normalizeText(event.data?.message);
  if (direct) return direct;

  return "流式请求失败，请稍后重试。";
}

export interface UseCLTPResult {
  currentRunState: ConversationRunState;
  isProcessing: boolean;
  isConnected: boolean;
  lastError: string | null;
  answerCompleteCount: number;
  sendMessage: (message: string, resumeDataOverride?: any) => Promise<void>;
  finalizeStream: () => void;
  cancelStream: (reason: RunCancelReason, message?: string) => void;
  disconnect: () => void;
}

export interface UseCLTPOptions {
  conversationId?: string;
  baseUrl?: string;
  heartbeatTimeout?: number;
  /** 业务静默超时（毫秒）：多久没收到任何可解析的业务事件就主动断开，
   *  独立于 heartbeatTimeout（心跳字节不代表 LLM 真的有产出）。 */
  meaningfulTimeout?: number;
  resumeData?: any;
  onSSEEvent?: (event: SSEEvent) => void;
  /** 本次会话使用的 LLM 模型（前端模型选择器），随请求透传给后端覆盖 */
  model?: string;
}

export function useCLTP(options: UseCLTPOptions = {}): UseCLTPResult {
  const agentEnabled = isAgentEnabled();
  const {
    conversationId,
    baseUrl = getApiBaseUrl(),
    resumeData,
    onSSEEvent,
    heartbeatTimeout = 0,
    meaningfulTimeout = 0,
    model,
  } = options;

  const [currentRunState, setCurrentRunState] = useState(() =>
    createConversationRunState(`${conversationId || "conversation"}:idle-0`),
  );
  const [isProcessing, setIsProcessing] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [answerCompleteCount, setAnswerCompleteCount] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const resumeDataRef = useRef<any>(resumeData);
  const onSSEEventRef = useRef<typeof onSSEEvent>(onSSEEvent);
  const modelRef = useRef<string | undefined>(model);
  const runCounterRef = useRef(0);

  useEffect(() => {
    resumeDataRef.current = resumeData;
  }, [resumeData]);

  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  useEffect(() => {
    onSSEEventRef.current = onSSEEvent;
  }, [onSSEEvent]);

  const resetStreamBuffers = useCallback(() => {
    runCounterRef.current += 1;
    setCurrentRunState(
      createConversationRunState(
        `${conversationId || "conversation"}:idle-${runCounterRef.current}`,
      ),
    );
  }, [conversationId]);

  const disconnect = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setIsConnected(false);
    setIsProcessing(false);
  }, []);

  const finalizeStream = useCallback(() => {
    resetStreamBuffers();
    setIsProcessing(false);
  }, [resetStreamBuffers]);

  const cancelStream = useCallback(
    (reason: RunCancelReason, message = "已停止生成。") => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setCurrentRunState((previous) =>
        reduceConversationRun(previous, {
          type: "run.cancelled",
          eventId: crypto.randomUUID(),
          runId: previous.runId,
          seq: previous.lastSeq + 1,
          sequenceSource: "arrival",
          at: Date.now(),
          reason,
          message,
        }),
      );
      setIsConnected(false);
      setIsProcessing(false);
    },
    [],
  );

  const sendMessage = useCallback(
    async (message: string, resumeDataOverride?: any) => {
      if (!agentEnabled) {
        setLastError("Agent is disabled by VITE_AGENT_ENABLED");
        return;
      }

      const content = message.trim();
      if (!content) return;

      disconnect();
      setLastError(null);
      setIsProcessing(true);
      setIsConnected(true);

      const controller = new AbortController();
      abortRef.current = controller;
      runCounterRef.current += 1;
      const runId = `${conversationId || "conversation"}:run-${runCounterRef.current}`;
      const eventAdapter = createAgentEventAdapter();
      setCurrentRunState(createConversationRunState(runId));

      // 2026-07-17 身份统一：JWT 下架，认证走 BetterAuth cookie，不再注入 Bearer。
      const authHeaders = getAuthHeaders();

      let completed = false;
      let failed = false;
      let failureRecorded = false;

      const recordFailure = (message: string) => {
        failed = true;
        if (failureRecorded) return;
        failureRecorded = true;
        setCurrentRunState((previous) =>
          reduceConversationRun(previous, {
            type: "run.failed",
            eventId: crypto.randomUUID(),
            runId,
            seq: previous.lastSeq + 1,
            sequenceSource: "arrival",
            at: Date.now(),
            message,
          }),
        );
      };

      const emitToPage = (event: AgentStreamEvent) => {
        onSSEEventRef.current?.(event as unknown as SSEEvent);
      };

      try {
        await streamAgent(
          {
            message: content,
            conversation_id: conversationId || null,
            resume_data:
              resumeDataOverride !== undefined
                ? resumeDataOverride
                : (resumeDataRef.current ?? null),
            model: modelRef.current || undefined,
            run_id: runId,
          },
          {
            baseUrl,
            signal: controller.signal,
            headers: authHeaders,
            idleTimeoutMs: heartbeatTimeout,
            meaningfulIdleTimeoutMs: meaningfulTimeout,
            onEvent: (event) => {
              const canonicalEvents = eventAdapter.normalize(event);
              setCurrentRunState((previous) =>
                canonicalEvents.reduce(reduceConversationRun, previous),
              );
              const type = event.type;
              if (type === "error" || type === "agent_error") {
                failed = true;
                failureRecorded = true;
              }
              if (type === "done" && (completed || failed)) return;
              emitToPage(event);

              if (type === "answer_reset") {
                return;
              }

              if (type === "thought" || type === "thought_chunk") {
                return;
              }

              if (type === "answer" || type === "answer_chunk") {
                return;
              }

              if (type === "done") {
                completed = true;
                if (import.meta.env.DEV) {
                  const shadow = canonicalEvents.length
                    ? canonicalEvents[canonicalEvents.length - 1]
                    : null;
                  console.debug("[AgentPresentation]", {
                    runId,
                    terminalEvent: shadow?.type || "done",
                  });
                }
                setAnswerCompleteCount((prev) => prev + 1);
                return;
              }

              if (type === "error" || type === "agent_error") {
                const message = extractStreamErrorMessage(event);
                if (message === "Execution stopped due to session switch") {
                  setLastError("任务被中断（来源：会话切换/新请求触发）");
                } else if (message === "Execution stopped by user") {
                  setLastError("任务被中断（来源：手动停止）");
                } else {
                  setLastError(message);
                }
              }
            },
            onError: (error) => {
              const message = error.message || "流式请求失败，请稍后重试。";
              recordFailure(message);
              setLastError(message);
            },
            onDone: () => {
              if (!completed && !failed) {
                completed = true;
                setAnswerCompleteCount((prev) => prev + 1);
              }
            },
          },
        );
      } catch (error) {
        if (!(error instanceof Error && error.name === "AbortError")) {
          const msg = error instanceof Error ? error.message : "流式请求失败";
          recordFailure(msg);
          setLastError(msg);
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setIsConnected(false);
          // 正常 done 只表示网络源结束，Response 仍可能在做前端渐进呈现。
          // 由上层在呈现完成后调用 finalizeStream；异常/中断则立即退出。
          if (!completed || failed) setIsProcessing(false);
        }
      }
    },
    [
      agentEnabled,
      disconnect,
      conversationId,
      baseUrl,
      heartbeatTimeout,
      meaningfulTimeout,
    ],
  );

  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
    };
  }, []);

  return {
    currentRunState,
    isProcessing,
    isConnected,
    lastError,
    answerCompleteCount,
    sendMessage,
    finalizeStream,
    cancelStream,
    disconnect,
  };
}
