import { getApiBaseUrl } from "@/lib/runtimeEnv";

export interface AgentStreamEvent {
  id: string;
  type: string;
  data: any;
  timestamp: string;
  runId?: string;
  seq?: number;
}

export interface AgentStreamPayload {
  message: string;
  conversation_id?: string | null;
  resume_data?: any;
  model?: string;
  run_id?: string;
}

export interface AgentStreamHandlers {
  onEvent?: (event: AgentStreamEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
  signal?: AbortSignal;
  baseUrl?: string;
  headers?: Record<string, string>;
  /** 流式读取的空闲超时（毫秒）：超过该时长未收到任何数据块即判定连接中断。
   *  后端每 55s 发心跳，故 60s 余量足够；传 <=0 或不传则不启用。 */
  idleTimeoutMs?: number;
  /** 业务静默超时（毫秒）：超过该时长未收到任何可解析的业务事件（thought/answer/
   *  tool 等）即判定为"LLM 迟迟不返回"并主动断开。独立于 idleTimeoutMs——后端心跳
   *  字节会持续重置 idleTimeoutMs，但心跳本身不代表 LLM 真的有产出，所以需要单独
   *  按"解析出事件"而不是"收到字节"来计时。传 <=0 或不传则不启用。 */
  meaningfulIdleTimeoutMs?: number;
  onResumePatch?: (patch: {
    patch_id: string
    paths:    string[]
    before:   Record<string, any>
    after:    Record<string, any>
    summary:  string
  }) => void;
  onResumeGenerated?: (data: {
    resume:  Record<string, any>
    summary: string
  }) => void;
}

function extractEventFields(rawBlock: string): {
  id: string;
  dataLines: string[];
} {
  const lines = rawBlock.split("\n");
  let id = "";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  return { id, dataLines };
}

export function parseAgentStreamBlock(
  rawBlock: string,
): AgentStreamEvent | null {
  const block = rawBlock.trim();
  if (!block) return null;

  const { id, dataLines } = extractEventFields(block);
  if (dataLines.length === 0) return null;

  const rawData = dataLines.join("\n").trim();
  if (!rawData) return null;

  try {
    const parsed = JSON.parse(rawData);
    if (parsed?.type === "heartbeat") {
      return {
        id: String(parsed.id || id || crypto.randomUUID()),
        type: "heartbeat",
        data: {},
        timestamp: String(parsed.timestamp || new Date().toISOString()),
      };
    }
    const canonical = parsed?.data;
    if (
      !canonical ||
      typeof canonical !== "object" ||
      typeof canonical.id !== "string" ||
      typeof canonical.type !== "string" ||
      typeof canonical.run_id !== "string" ||
      typeof canonical.seq !== "number" ||
      !canonical.data ||
      typeof canonical.data !== "object"
    ) {
      return null;
    }
    return {
      id: canonical.id,
      type: canonical.type,
      data: canonical.data,
      timestamp: String(parsed?.timestamp || new Date().toISOString()),
      runId: canonical.run_id,
      seq: canonical.seq,
    };
  } catch {
    return null;
  }
}

function isDoneEvent(event: AgentStreamEvent): boolean {
  return event.type === "done";
}

export async function streamAgent(
  payload: AgentStreamPayload,
  handlers: AgentStreamHandlers = {},
): Promise<void> {
  const {
    onEvent,
    onError,
    onDone,
    signal,
    baseUrl = getApiBaseUrl(),
    headers = {},
    idleTimeoutMs = 0,
    meaningfulIdleTimeoutMs = 0,
  } = handlers;

  let doneEmitted = false;
  const markDone = () => {
    if (doneEmitted) return;
    doneEmitted = true;
    onDone?.();
  };

  // 提到函数顶层：try/catch 两块都要能访问，用于 finally 清理。
  let meaningfulTimer: ReturnType<typeof setTimeout> | null = null;
  const clearMeaningfulTimer = () => {
    if (meaningfulTimer) {
      clearTimeout(meaningfulTimer);
      meaningfulTimer = null;
    }
  };

  try {
    const response = await fetch(`${baseUrl}/api/agent/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...headers,
      },
      credentials: "include",
      body: JSON.stringify(payload),
      signal,
    });

    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new Error(
        `SSE request failed: ${response.status} ${response.statusText}${body ? ` - ${body.slice(0, 300)}` : ""}`,
      );
    }

    if (!response.body) {
      throw new Error("SSE response has no body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // 空闲看门狗：每个数据块（含后端心跳）到达即重置；超过 idleTimeoutMs 仍无任何块，
    // 判定为静默断流，取消 reader 并以超时错误退出，避免前端一直卡在“生成中”。
    let idleTimer: ReturnType<typeof setTimeout> | null = null;
    const clearIdle = () => {
      if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
      }
    };
    const readChunk = (): Promise<ReadableStreamReadResult<Uint8Array>> => {
      if (idleTimeoutMs <= 0) return reader.read();
      return new Promise((resolve, reject) => {
        idleTimer = setTimeout(() => {
          reader.cancel().catch(() => {});
          reject(
            new Error(
              `流式响应空闲超过 ${Math.round(idleTimeoutMs / 1000)} 秒，连接可能已中断，请重试`,
            ),
          );
        }, idleTimeoutMs);
        reader.read().then(
          (result) => {
            clearIdle();
            resolve(result);
          },
          (error) => {
            clearIdle();
            reject(error);
          },
        );
      });
    };

    // 业务静默看门狗：跟上面的 idleTimer 独立——后端心跳字节会持续重置
    // idleTimer，但心跳不代表 LLM 真的有产出。这里只在"解析出一个真实业务
    // 事件"时才重置，超时只 cancel reader（不直接 reject），由主循环在
    // readChunk() 返回后检查标志位，抛出更明确的错误信息。
    let meaningfulTimedOut = false;
    let meaningfulTimeoutError: Error | null = null;
    const armMeaningfulTimer = () => {
      if (meaningfulIdleTimeoutMs <= 0) return;
      clearMeaningfulTimer();
      meaningfulTimer = setTimeout(() => {
        meaningfulTimedOut = true;
        meaningfulTimeoutError = new Error(
          `LLM 响应静默超过 ${Math.round(meaningfulIdleTimeoutMs / 1000)} 秒，请重试`,
        );
        reader.cancel().catch(() => {});
      }, meaningfulIdleTimeoutMs);
    };
    armMeaningfulTimer();

    while (true) {
      const { done, value } = await readChunk();
      if (meaningfulTimedOut) {
        throw meaningfulTimeoutError!;
      }
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        const parsed = parseAgentStreamBlock(block);
        if (!parsed) {
          throw new Error("收到了不符合 canonical 协议的 SSE 事件。");
        }
        // 心跳事件是格式完整、可解析的 SSE block（带 data 字段），但不代表
        // LLM 真的有产出——不能重置业务静默计时器，否则跟 idleTimer 一样
        // 被心跳一直续命，120s 阈值永远打不到，这层超时就形同虚设。
        if (parsed.type !== "heartbeat") {
          armMeaningfulTimer();
        }
        onEvent?.(parsed);
        if (isDoneEvent(parsed)) {
          markDone();
        }
        if (parsed.type === 'resume_patch' && handlers.onResumePatch) {
          handlers.onResumePatch(parsed.data)
        }
        if (parsed.type === 'resume_generated' && handlers.onResumeGenerated) {
          handlers.onResumeGenerated(parsed.data)
        }
      }
    }

    if (buffer.trim()) {
      const parsed = parseAgentStreamBlock(buffer);
      if (!parsed) {
        throw new Error("收到了不符合 canonical 协议的 SSE 事件。");
      }
      onEvent?.(parsed);
      if (isDoneEvent(parsed)) {
        markDone();
      }
    }

    clearMeaningfulTimer();
    if (!doneEmitted) {
      throw new Error("SSE 连接在收到真实 done 事件前结束。");
    }
  } catch (error) {
    clearMeaningfulTimer();
    if (error instanceof Error && error.name === "AbortError") {
      return;
    }
    const rawError = error instanceof Error ? error : new Error(String(error));
    const err =
      rawError instanceof TypeError && rawError.message === "Failed to fetch"
        ? new Error(
            `无法连接 Agent 服务：${
              baseUrl ||
              (typeof window !== "undefined"
                ? window.location.origin
                : "(current origin)")
            }/api/agent/stream。` +
              "请确认后端 9000 端口、前端 API 地址和登录代理均已启动。",
          )
        : rawError;
    onError?.(err);
    throw err;
  }
}
