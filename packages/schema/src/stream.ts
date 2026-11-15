import { z } from "zod";

/**
 * SSE 流式事件类型枚举
 */
export const StreamEventTypeSchema = z.enum([
  // 核心文本与流式状态
  "text_delta",
  "status",
  "error",
  "done",

  // 思考与解答
  "thought_start",
  "thought_end",
  "thought",
  "answer_start",
  "answer_chunk",
  "answer_end",
  "answer",

  // 工具调用
  "tool_call_start",
  "tool_call_end",
  "tool_call",
  "tool_result",
  "tool_error",
  "tool_progress",

  // 简历领域事件
  "resume_updated",
  "resume_patch",
  "resume_generated",

  // Agent 生命周期与交互提示
  "agent_start",
  "agent_end",
  "agent_error",
  "suggestions",
  "auto_continue",
  "answer_reset",

  // 系统事件
  "system",
  "warning",
  "debug",
]);

export type StreamEventType = z.infer<typeof StreamEventTypeSchema>;

/**
 * 文本增量事件载荷 (text_delta)
 */
export const TextDeltaPayloadSchema = z.object({
  content: z.string().optional(),
  delta: z.string(),
  phase: z.string().optional(),
}).passthrough();

export type TextDeltaPayload = z.infer<typeof TextDeltaPayloadSchema>;

/**
 * 工具调用事件载荷 (tool_call)
 */
export const ToolCallPayloadSchema = z.object({
  tool: z.string().optional(),
  tool_name: z.string().optional(),
  args: z.record(z.string(), z.any()).optional(),
  tool_call_id: z.string().optional(),
  input: z.any().optional(),
}).passthrough();

export type ToolCallPayload = z.infer<typeof ToolCallPayloadSchema>;

/**
 * 工具返回结果事件载荷 (tool_result)
 */
export const ToolResultPayloadSchema = z.object({
  tool: z.string().optional(),
  tool_name: z.string().optional(),
  result: z.any().optional(),
  tool_call_id: z.string().optional(),
  outcome: z.enum(["success", "error"]).optional(),
}).passthrough();

export type ToolResultPayload = z.infer<typeof ToolResultPayloadSchema>;

/**
 * 状态事件载荷 (status)
 */
export const StatusPayloadSchema = z.object({
  status: z.string(),
  message: z.string().optional(),
  code: z.union([z.string(), z.number()]).optional(),
}).passthrough();

export type StatusPayload = z.infer<typeof StatusPayloadSchema>;

/**
 * 错误事件载荷 (error)
 */
export const ErrorPayloadSchema = z.object({
  message: z.string(),
  code: z.union([z.string(), z.number()]).optional(),
  details: z.any().optional(),
}).passthrough();

export type ErrorPayload = z.infer<typeof ErrorPayloadSchema>;

/**
 * 结束事件载荷 (done)
 */
export const DonePayloadSchema = z.object({
  summary: z.string().optional(),
  run_id: z.string().optional(),
  status: z.string().optional(),
}).passthrough();

export type DonePayload = z.infer<typeof DonePayloadSchema>;

/**
 * 简历补丁事件载荷 (resume_patch)
 */
export const ResumePatchPayloadSchema = z.object({
  patch_id: z.string().optional(),
  paths: z.array(z.string()).default([]),
  before: z.record(z.string(), z.any()).optional(),
  after: z.record(z.string(), z.any()).optional(),
  summary: z.string().default(""),
}).passthrough();

export type ResumePatchPayload = z.infer<typeof ResumePatchPayloadSchema>;

/**
 * 简历生成事件载荷 (resume_generated)
 */
export const ResumeGeneratedPayloadSchema = z.object({
  resume: z.record(z.string(), z.any()),
  summary: z.string().optional(),
}).passthrough();

export type ResumeGeneratedPayload = z.infer<typeof ResumeGeneratedPayloadSchema>;

/**
 * 通用 SSE 流式事件权威契约 (StreamEventSchema)
 * 兼容 Python 后端事件信封与前端 CanonicalPresentation
 */
export const StreamEventSchema = z.object({
  id: z.string().optional(),
  event_type: z.union([StreamEventTypeSchema, z.string()]),
  type: z.string().optional(), // 前端别名兼容
  data: z.record(z.string(), z.any()).or(z.any()).default({}),
  timestamp: z.union([z.number(), z.string()]).optional(),
  session_id: z.string().nullable().optional(),
  run_id: z.string().nullable().optional(),
  seq: z.number().nullable().optional(),
}).passthrough();

export type StreamEvent = z.infer<typeof StreamEventSchema>;

/**
 * 解析并验证 StreamEvent
 */
export function parseStreamEvent(raw: unknown): StreamEvent {
  return StreamEventSchema.parse(raw);
}

/**
 * 安全解析 StreamEvent
 */
export function safeParseStreamEvent(raw: unknown) {
  return StreamEventSchema.safeParse(raw);
}

/**
 * 将 StreamEvent 序列化为标准的 SSE 文本帧
 */
export function formatSSEMessage(event: StreamEvent): string {
  const lines: string[] = [];
  if (event.id) {
    lines.push(`id: ${event.id}`);
  }
  const eventName = event.event_type || event.type || "message";
  lines.push(`event: ${eventName}`);

  const payloadString = typeof event.data === "string" 
    ? event.data 
    : JSON.stringify(event.data);
  lines.push(`data: ${payloadString}`);

  return lines.join("\n") + "\n\n";
}

/**
 * 解析 SSE 原始文本块为结构化事件
 */
export function parseSSEBlock(rawBlock: string): StreamEvent | null {
  const trimmed = rawBlock.trim();
  if (!trimmed) return null;

  const lines = trimmed.split("\n");
  let id: string | undefined;
  let eventType: string = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  const rawData = dataLines.join("\n");
  let parsedData: any = rawData;
  try {
    parsedData = JSON.parse(rawData);
  } catch {
    // 保持原始字符串
  }

  return StreamEventSchema.parse({
    id,
    event_type: eventType,
    data: parsedData,
  });
}
