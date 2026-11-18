import { extractApiErrorMessage } from "@/lib/apiError";

/**
 * 调用后端 AI 解析接口，将粘贴/上传的纯文本转为结构化简历 JSON。
 */
export async function parseResumeText(
  apiBaseUrl: string,
  text: string,
  model = "deepseek-flash",
): Promise<Record<string, unknown>> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("简历文本为空");
  }

  const response = await fetch(`${apiBaseUrl}/api/resume/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: trimmed, model }),
  });

  if (!response.ok) {
    let errMsg = "解析失败";
    try {
      const err = await response.json();
      errMsg = extractApiErrorMessage(err, errMsg) || errMsg;
    } catch {
      errMsg = `HTTP ${response.status}`;
    }
    throw new Error(errMsg);
  }

  const result = (await response.json()) as {
    resume?: Record<string, unknown>;
  };
  return (result.resume || result) as Record<string, unknown>;
}
