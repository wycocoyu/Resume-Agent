import { extractApiErrorMessage } from './apiError';
import { FetchTimeoutError } from './fetchWithTimeout';

export interface UploadResumeImageStreamOptions {
  apiBaseUrl: string;
  formData: FormData;
  idleTimeoutMs?: number;
  maxTotalMs?: number;
  onStatus?: (message: string, stage?: string) => void;
}

/**
 * 通过 SSE 流式通道上传并解析简历图片（/api/resume/upload-image/stream）。
 * 每收到状态或心跳帧会重置空闲计时器，避免网关 100s 无字节超时断连；
 * 若代理返回普通 application/json，也兼容直接解析。
 */
export async function uploadResumeImageStream({
  apiBaseUrl,
  formData,
  idleTimeoutMs = 90_000,
  maxTotalMs = 300_000,
  onStatus,
}: UploadResumeImageStreamOptions): Promise<any> {
  const controller = new AbortController();
  let timedOut = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  const startedAt = Date.now();

  const armIdleTimer = () => {
    if (idleTimer) clearTimeout(idleTimer);
    const remaining = Math.max(1_000, maxTotalMs - (Date.now() - startedAt));
    const waitMs = Math.min(idleTimeoutMs, remaining);
    idleTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, waitMs);
  };

  armIdleTimer();

  try {
    const response = await fetch(`${apiBaseUrl}/api/resume/upload-image/stream`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    armIdleTimer();

    if (!response.ok) {
      let errMsg = `图片识别失败（${response.status}）`;
      try {
        const errBody = await response.json();
        errMsg = extractApiErrorMessage(errBody, errMsg) || errMsg;
      } catch {
        // 非 JSON 错误体保留 HTTP 状态码
      }
      throw new Error(errMsg);
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/event-stream') || !response.body) {
      const data = await response.json();
      const parsed = data?.resume || data?.data || data;
      if (!parsed || typeof parsed !== 'object') {
        throw new Error('未识别出结构化简历内容，请换更清晰的图片重试。');
      }
      return parsed;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let resolvedPayload: any = null;
    let streamErr = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      armIdleTimer();
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        const line = part.split('\n').find((l) => l.startsWith('data: '));
        if (!line) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === '[DONE]') continue;
        try {
          const evt = JSON.parse(payload);
          if (evt.type === 'status' && typeof evt.content === 'string') {
            onStatus?.(evt.content, evt.stage);
          } else if (evt.type === 'json') {
            resolvedPayload = evt.content;
          } else if (evt.type === 'error') {
            streamErr = extractApiErrorMessage(evt.content ?? evt, '图片识别失败') || '图片识别失败';
          }
        } catch {
          // 忽略不完整或非 JSON 心跳帧
        }
      }
    }

    if (buffer.trim()) {
      const line = buffer.split('\n').find((l) => l.startsWith('data: '));
      if (line) {
        const payload = line.slice(6).trim();
        if (payload && payload !== '[DONE]') {
          try {
            const evt = JSON.parse(payload);
            if (evt.type === 'json') resolvedPayload = evt.content;
            else if (evt.type === 'error') streamErr = evt.content || '图片识别失败';
          } catch {
            // 忽略尾部残余帧
          }
        }
      }
    }

    if (streamErr) throw new Error(streamErr);
    const parsed = resolvedPayload?.resume || resolvedPayload?.data || resolvedPayload;
    if (!parsed || typeof parsed !== 'object') {
      throw new Error('未识别出结构化简历内容，请换更清晰的图片重试。');
    }
    return parsed;
  } catch (err: any) {
    if (err?.name === 'AbortError' && timedOut) {
      throw new FetchTimeoutError(`图片识别超时 (${maxTotalMs}ms)`);
    }
    throw err;
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
  }
}
