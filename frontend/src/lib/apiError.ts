/**
 * Extracts a human-readable error message from backend JSON/text error payloads.
 * Handles Issue #97 flat `{ code, message, detail }` payloads as well as
 * FastAPI `{ detail: string | { message?: string } }` responses.
 */
export function extractApiErrorMessage(data: unknown, fallback = ''): string {
  if (!data) return fallback
  if (typeof data === 'string') {
    const trimmed = data.trim()
    if (!trimmed) return fallback
    try {
      const parsed = JSON.parse(trimmed)
      return extractApiErrorMessage(parsed, trimmed)
    } catch {
      return trimmed
    }
  }
  if (typeof data === 'object') {
    const record = data as Record<string, unknown>
    if (typeof record.message === 'string' && record.message.trim()) {
      return record.message.trim()
    }
    if (typeof record.detail === 'string' && record.detail.trim()) {
      return record.detail.trim()
    }
    if (record.detail && typeof record.detail === 'object') {
      const detailObj = record.detail as Record<string, unknown>
      if (typeof detailObj.message === 'string' && detailObj.message.trim()) {
        return detailObj.message.trim()
      }
      try {
        return JSON.stringify(detailObj)
      } catch {
        return fallback
      }
    }
    if (typeof record.error_message === 'string' && record.error_message.trim()) {
      return record.error_message.trim()
    }
    if (typeof record.error === 'string' && record.error.trim()) {
      return record.error.trim()
    }
  }
  return fallback
}

export async function readFetchErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const text = await response.clone().text()
    const extracted = extractApiErrorMessage(text, '')
    if (extracted) return extracted
  } catch {
    // ignore read/parse error
  }
  return fallback
}

export function extractAxiosErrorMessage(error: unknown, fallback: string): string {
  const responseData = (error as { response?: { data?: unknown } } | null)?.response?.data
  if (responseData !== undefined) {
    const extracted = extractApiErrorMessage(responseData, '')
    if (extracted) return extracted
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}
