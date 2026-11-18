import { afterEach, describe, expect, it, vi } from 'vitest';
import { uploadResumeImageStream } from '../uploadResumeImageStream';

function makeSseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

describe('uploadResumeImageStream', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('parses status, heartbeat, and final json events from SSE stream', async () => {
    const statuses: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeSseResponse([
        'data: {"type":"status","stage":"ocr","content":"正在识别第 1/1 张图片..."}\n\n',
        'data: {"type":"heartbeat","stage":"ocr","elapsed":15.0}\n\n',
        'data: {"type":"status","stage":"structuring","content":"正在整理简历结构..."}\n\n',
        'data: {"type":"json","content":{"resume":{"name":"张三"},"provider":"glm-ocr"}}\n\ndata: [DONE]\n\n',
      ]),
    );

    const formData = new FormData();
    formData.append('model', 'glm-ocr');

    const result = await uploadResumeImageStream({
      apiBaseUrl: 'http://127.0.0.1:9000',
      formData,
      onStatus: (msg) => statuses.push(msg),
    });

    expect(result).toEqual({ name: '张三' });
    expect(statuses).toEqual(['正在识别第 1/1 张图片...', '正在整理简历结构...']);
  });

  it('surfaces SSE error events with user-facing detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeSseResponse([
        'data: {"type":"error","status":502,"content":"图片识别失败: upstream busy"}\n\n',
      ]),
    );

    await expect(
      uploadResumeImageStream({
        apiBaseUrl: 'http://127.0.0.1:9000',
        formData: new FormData(),
      }),
    ).rejects.toThrow('图片识别失败: upstream busy');
  });

  it('falls back cleanly when proxy responds with application/json', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ resume: { name: '李四' }, provider: 'glm-ocr' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await uploadResumeImageStream({
      apiBaseUrl: 'http://127.0.0.1:9000',
      formData: new FormData(),
    });
    expect(result).toEqual({ name: '李四' });
  });

  it('extracts friendly message on 503/429 JSON error responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'AI_RATE_LIMITED',
          message: '当前 IP 短时间内 AI 调用次数已达上限',
          detail: '当前 IP 短时间内 AI 调用次数已达上限，请稍后再试。',
        }),
        {
          status: 429,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    await expect(
      uploadResumeImageStream({
        apiBaseUrl: 'http://127.0.0.1:9000',
        formData: new FormData(),
      }),
    ).rejects.toThrow('当前 IP 短时间内 AI 调用次数已达上限');
  });
});
