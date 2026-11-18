export const ANON_AGENT_TOKEN_STORAGE_KEY = 'cococv_anon_agent_token'
export const AGENT_SESSIONS_STORAGE_KEY = 'cococv_agent_sessions_v1'
export const AGENT_SESSIONS_UPDATED_EVENT = 'cococv:agent-sessions-updated'
export const MAX_LOCAL_AGENT_SESSIONS = 30
export const MAX_LOCAL_AGENT_MESSAGES = 60

export interface LocalAgentMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  thought?: string
  timestamp?: string
}

export interface LocalAgentSession {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  messages: LocalAgentMessage[]
}

export interface LocalAgentSessionMeta {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export type HistoryPayloadMessage = {
  role: 'user' | 'assistant'
  content: string
}

let inMemoryAnonToken: string | null = null

function generateAnonToken(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `anon-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export function getOrCreateAnonAgentToken(): string {
  try {
    const existing = localStorage.getItem(ANON_AGENT_TOKEN_STORAGE_KEY)?.trim()
    if (existing && existing.length <= 128) {
      inMemoryAnonToken = existing
      return existing
    }
  } catch {
    if (inMemoryAnonToken) return inMemoryAnonToken
  }

  const nextToken = inMemoryAnonToken || generateAnonToken()
  inMemoryAnonToken = nextToken
  try {
    localStorage.setItem(ANON_AGENT_TOKEN_STORAGE_KEY, nextToken)
  } catch {
    // ignore storage errors in restricted contexts
  }
  return nextToken
}

function dispatchSessionsUpdated(): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(AGENT_SESSIONS_UPDATED_EVENT))
  } catch {
    // ignore event errors
  }
}

function normalizeMessage(raw: unknown): LocalAgentMessage | null {
  if (!raw || typeof raw !== 'object') return null
  const record = raw as Record<string, unknown>
  if (record.role !== 'user' && record.role !== 'assistant') return null
  const content =
    typeof record.content === 'string'
      ? record.content
      : record.content != null
        ? JSON.stringify(record.content)
        : ''
  const msg: LocalAgentMessage = {
    role: record.role,
    content,
  }
  if (typeof record.id === 'string' && record.id) {
    msg.id = record.id
  }
  if (typeof record.thought === 'string' && record.thought.trim()) {
    msg.thought = record.thought
  }
  if (typeof record.timestamp === 'string' && record.timestamp) {
    msg.timestamp = record.timestamp
  }
  return msg
}

function deriveSessionTitle(
  messages: LocalAgentMessage[],
  explicitTitle?: string,
  existingTitle?: string,
): string {
  if (explicitTitle && explicitTitle.trim()) {
    return explicitTitle.trim().slice(0, 60)
  }
  if (existingTitle && existingTitle.trim() && existingTitle.trim() !== '新对话') {
    return existingTitle.trim().slice(0, 60)
  }
  const firstUser = messages.find((m) => m.role === 'user' && m.content.trim())
  if (!firstUser) return '新对话'
  const singleLine = firstUser.content.replace(/\s+/g, ' ').trim()
  return singleLine.length > 32 ? `${singleLine.slice(0, 32)}…` : singleLine
}

function toMs(iso?: string): number {
  if (!iso) return 0
  const parsed = Date.parse(iso)
  return Number.isNaN(parsed) ? 0 : parsed
}

function sortAndCapSessions(sessions: LocalAgentSession[]): LocalAgentSession[] {
  return [...sessions]
    .sort((a, b) => toMs(b.updated_at) - toMs(a.updated_at))
    .slice(0, MAX_LOCAL_AGENT_SESSIONS)
}

function readAllSessionsRaw(): LocalAgentSession[] {
  try {
    const raw = localStorage.getItem(AGENT_SESSIONS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []

    const sessions: LocalAgentSession[] = []
    for (const item of parsed) {
      if (!item || typeof item !== 'object') continue
      const rec = item as Record<string, unknown>
      const sessionId = typeof rec.session_id === 'string' ? rec.session_id.trim() : ''
      if (!sessionId) continue
      const messages = Array.isArray(rec.messages)
        ? rec.messages
            .map(normalizeMessage)
            .filter((m): m is LocalAgentMessage => m !== null)
            .slice(-MAX_LOCAL_AGENT_MESSAGES)
        : []
      const now = new Date().toISOString()
      const createdAt = typeof rec.created_at === 'string' && rec.created_at ? rec.created_at : now
      const updatedAt = typeof rec.updated_at === 'string' && rec.updated_at ? rec.updated_at : createdAt
      const title = deriveSessionTitle(
        messages,
        typeof rec.title === 'string' ? rec.title : undefined,
      )
      sessions.push({
        session_id: sessionId,
        title,
        created_at: createdAt,
        updated_at: updatedAt,
        message_count: messages.length,
        messages,
      })
    }
    return sortAndCapSessions(sessions)
  } catch {
    return []
  }
}

function writeAllSessions(sessions: LocalAgentSession[]): void {
  const capped = sortAndCapSessions(sessions)
  for (let limit = capped.length; limit >= 1; limit -= 1) {
    try {
      localStorage.setItem(AGENT_SESSIONS_STORAGE_KEY, JSON.stringify(capped.slice(0, limit)))
      dispatchSessionsUpdated()
      return
    } catch {
      // Retry with fewer sessions on QuotaExceededError
    }
  }
  try {
    localStorage.setItem(AGENT_SESSIONS_STORAGE_KEY, '[]')
    dispatchSessionsUpdated()
  } catch {
    // ignore unrecoverable storage failure
  }
}

export function listLocalAgentSessions(): LocalAgentSessionMeta[] {
  return readAllSessionsRaw().map(({ session_id, title, created_at, updated_at, message_count }) => ({
    session_id,
    title,
    created_at,
    updated_at,
    message_count,
  }))
}

export function getLocalAgentSession(sessionId: string): LocalAgentSession | null {
  const id = sessionId.trim()
  if (!id) return null
  return readAllSessionsRaw().find((s) => s.session_id === id) ?? null
}

export function saveLocalAgentSession(
  sessionId: string,
  messages: LocalAgentMessage[],
  options?: { title?: string; updatedAt?: string },
): LocalAgentSession | null {
  const id = sessionId.trim()
  if (!id) return null

  const existingAll = readAllSessionsRaw()
  const existing = existingAll.find((s) => s.session_id === id)
  const now = options?.updatedAt || new Date().toISOString()
  const normalizedMessages = messages
    .map(normalizeMessage)
    .filter((m): m is LocalAgentMessage => m !== null)
    .slice(-MAX_LOCAL_AGENT_MESSAGES)

  const nextSession: LocalAgentSession = {
    session_id: id,
    title: deriveSessionTitle(normalizedMessages, options?.title, existing?.title),
    created_at: existing?.created_at || now,
    updated_at: now,
    message_count: normalizedMessages.length,
    messages: normalizedMessages,
  }

  // Prepend updated session so same-millisecond writes preserve newest-first order
  const others = existingAll.filter((s) => s.session_id !== id)
  writeAllSessions([nextSession, ...others])
  return nextSession
}

export function appendLocalAgentMessages(
  sessionId: string,
  messagesDelta: LocalAgentMessage[],
  options?: { title?: string; updatedAt?: string },
): LocalAgentSession | null {
  const id = sessionId.trim()
  if (!id) return null

  const existing = getLocalAgentSession(id)
  const combined = [...(existing?.messages || []), ...messagesDelta]
  return saveLocalAgentSession(id, combined, options)
}

export function renameLocalAgentSession(
  sessionId: string,
  title: string,
): LocalAgentSession | null {
  const id = sessionId.trim()
  const trimmedTitle = title.trim()
  if (!id || !trimmedTitle) return null

  const existingAll = readAllSessionsRaw()
  const target = existingAll.find((s) => s.session_id === id)
  if (!target) return null

  const updated: LocalAgentSession = {
    ...target,
    title: trimmedTitle.slice(0, 60),
  }
  const nextAll = existingAll.map((s) => (s.session_id === id ? updated : s))
  writeAllSessions(nextAll)
  return updated
}

export function deleteLocalAgentSession(sessionId: string): boolean {
  const id = sessionId.trim()
  if (!id) return false

  const existingAll = readAllSessionsRaw()
  const filtered = existingAll.filter((s) => s.session_id !== id)
  if (filtered.length === existingAll.length) return false

  writeAllSessions(filtered)
  return true
}

export function clearAllLocalAgentSessions(): void {
  try {
    localStorage.removeItem(AGENT_SESSIONS_STORAGE_KEY)
  } catch {
    // ignore
  }
  dispatchSessionsUpdated()
}

export function getRecentHistoryPayload(
  sessionId: string,
  limit = 20,
): HistoryPayloadMessage[] {
  if (limit <= 0) return []
  const session = getLocalAgentSession(sessionId)
  if (!session) return []

  return session.messages
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content.trim().length > 0)
    .slice(-limit)
    .map((m) => ({
      role: m.role,
      content: m.content,
    }))
}
