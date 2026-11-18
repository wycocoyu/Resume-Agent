// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AGENT_SESSIONS_STORAGE_KEY,
  AGENT_SESSIONS_UPDATED_EVENT,
  ANON_AGENT_TOKEN_STORAGE_KEY,
  MAX_LOCAL_AGENT_MESSAGES,
  MAX_LOCAL_AGENT_SESSIONS,
  appendLocalAgentMessages,
  clearAllLocalAgentSessions,
  deleteLocalAgentSession,
  getLocalAgentSession,
  getOrCreateAnonAgentToken,
  getRecentHistoryPayload,
  listLocalAgentSessions,
  renameLocalAgentSession,
  saveLocalAgentSession,
} from './agentLocalHistory'

describe('agentLocalHistory', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('creates and reuses persistent anonymous ownership token', () => {
    const first = getOrCreateAnonAgentToken()
    expect(first).toBeTruthy()
    expect(first.length).toBeLessThanOrEqual(128)
    expect(localStorage.getItem(ANON_AGENT_TOKEN_STORAGE_KEY)).toBe(first)

    const second = getOrCreateAnonAgentToken()
    expect(second).toBe(first)
  })

  it('saves, reads, appends, renames, and deletes sessions while emitting update events', () => {
    const eventListener = vi.fn()
    window.addEventListener(AGENT_SESSIONS_UPDATED_EVENT, eventListener)

    const saved = saveLocalAgentSession('conv-1', [
      { role: 'user', content: '帮我优化实习经历，突出高并发压测指标' },
      { role: 'assistant', content: '好的，请先发一下你目前的实习经历内容。', thought: '分析用户意图' },
    ])

    expect(saved).not.toBeNull()
    expect(saved?.title).toContain('帮我优化实习经历')
    expect(saved?.message_count).toBe(2)
    expect(eventListener).toHaveBeenCalledTimes(1)

    const appended = appendLocalAgentMessages('conv-1', [
      { role: 'user', content: '字节跳动后端实习生，负责推荐网关。' },
    ])
    expect(appended?.message_count).toBe(3)
    expect(appended?.title).toContain('帮我优化实习经历')
    expect(eventListener).toHaveBeenCalledTimes(2)

    const loaded = getLocalAgentSession('conv-1')
    expect(loaded?.messages).toHaveLength(3)
    expect(loaded?.messages[1].thought).toBe('分析用户意图')

    const renamed = renameLocalAgentSession('conv-1', '字节实习优化')
    expect(renamed?.title).toBe('字节实习优化')
    expect(listLocalAgentSessions()[0].title).toBe('字节实习优化')
    expect(eventListener).toHaveBeenCalledTimes(3)

    expect(deleteLocalAgentSession('conv-1')).toBe(true)
    expect(deleteLocalAgentSession('conv-1')).toBe(false)
    expect(getLocalAgentSession('conv-1')).toBeNull()
    expect(listLocalAgentSessions()).toHaveLength(0)
    expect(eventListener).toHaveBeenCalledTimes(4)

    window.removeEventListener(AGENT_SESSIONS_UPDATED_EVENT, eventListener)
  })

  it('sorts sessions by updated_at desc and caps at 30 sessions and 60 messages', () => {
    for (let i = 1; i <= 35; i++) {
      saveLocalAgentSession(
        `conv-${i}`,
        [{ role: 'user', content: `会话消息 ${i}` }],
        { updatedAt: new Date(Date.UTC(2026, 10, 18, 0, i)).toISOString() },
      )
    }

    const sessions = listLocalAgentSessions()
    expect(sessions).toHaveLength(MAX_LOCAL_AGENT_SESSIONS)
    expect(sessions[0].session_id).toBe('conv-35')
    expect(sessions[sessions.length - 1].session_id).toBe('conv-6')

    const manyMessages = Array.from({ length: 75 }, (_, idx) => ({
      role: idx % 2 === 0 ? ('user' as const) : ('assistant' as const),
      content: `msg-${idx + 1}`,
    }))
    const capped = saveLocalAgentSession('conv-cap', manyMessages)
    expect(capped?.messages).toHaveLength(MAX_LOCAL_AGENT_MESSAGES)
    expect(capped?.messages[0].content).toBe('msg-16')
    expect(capped?.messages[MAX_LOCAL_AGENT_MESSAGES - 1].content).toBe('msg-75')
  })

  it('builds recent history_messages payload capped to limit without extra metadata', () => {
    const msgs = Array.from({ length: 26 }, (_, idx) => ({
      id: `id-${idx}`,
      role: idx % 2 === 0 ? ('user' as const) : ('assistant' as const),
      content: `turn-${idx + 1}`,
      thought: `internal-${idx + 1}`,
    }))
    saveLocalAgentSession('conv-history', msgs)

    const payload = getRecentHistoryPayload('conv-history', 20)
    expect(payload).toHaveLength(20)
    expect(payload[0]).toEqual({ role: 'user', content: 'turn-7' })
    expect(payload[19]).toEqual({ role: 'assistant', content: 'turn-26' })
    expect('thought' in payload[0]).toBe(false)
    expect('id' in payload[0]).toBe(false)

    clearAllLocalAgentSessions()
    expect(localStorage.getItem(AGENT_SESSIONS_STORAGE_KEY)).toBeNull()
    expect(listLocalAgentSessions()).toHaveLength(0)
  })
})
