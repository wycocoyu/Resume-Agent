// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BYOK_PROVIDER_PRESETS,
  BYOK_STORAGE_KEY,
  BYOK_UPDATED_EVENT,
  clearByokConfig,
  getAgentRequestHeaders,
  isByokActive,
  loadByokConfig,
  saveByokConfig,
} from './agentByokConfig'
import { ANON_AGENT_TOKEN_STORAGE_KEY } from './agentLocalHistory'

describe('agentByokConfig', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('provides all 8 expected provider presets and defaults to disabled deepseek', () => {
    expect(Object.keys(BYOK_PROVIDER_PRESETS)).toEqual([
      'deepseek',
      'openai',
      'openrouter',
      'siliconflow',
      'moonshot',
      'doubao',
      'zhipu',
      'custom',
    ])

    const initial = loadByokConfig()
    expect(initial).toEqual({
      enabled: false,
      provider: 'deepseek',
      apiKey: '',
      baseUrl: 'https://api.deepseek.com',
      model: 'deepseek-chat',
    })
    expect(isByokActive()).toBe(false)
  })

  it('always attaches X-Anon-Session-Token and adds BYOK headers only when active', () => {
    const anonHeaders = getAgentRequestHeaders({ 'Content-Type': 'application/json' })
    const token = localStorage.getItem(ANON_AGENT_TOKEN_STORAGE_KEY)
    expect(token).toBeTruthy()
    expect(anonHeaders['X-Anon-Session-Token']).toBe(token)
    expect(anonHeaders['Content-Type']).toBe('application/json')
    expect(anonHeaders['X-AI-Api-Key']).toBeUndefined()

    const listener = vi.fn()
    window.addEventListener(BYOK_UPDATED_EVENT, listener)

    // Key present but disabled -> still inactive
    saveByokConfig({
      enabled: false,
      provider: 'openai',
      apiKey: 'sk-test-disabled',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
    })
    expect(isByokActive()).toBe(false)
    expect(getAgentRequestHeaders()['X-AI-Api-Key']).toBeUndefined()

    // Enable -> active and attaches all 4 BYOK headers
    saveByokConfig({
      enabled: true,
      provider: 'openrouter',
      apiKey: '  sk-or-v1-secret  ',
      baseUrl: 'https://openrouter.ai/api/v1',
      model: 'anthropic/claude-3.5-sonnet',
    })
    expect(isByokActive()).toBe(true)
    expect(localStorage.getItem(BYOK_STORAGE_KEY)).toContain('sk-or-v1-secret')

    const activeHeaders = getAgentRequestHeaders()
    expect(activeHeaders['X-Anon-Session-Token']).toBe(token)
    expect(activeHeaders['X-AI-Provider']).toBe('openrouter')
    expect(activeHeaders['X-AI-Api-Key']).toBe('sk-or-v1-secret')
    expect(activeHeaders['X-AI-Base-Url']).toBe('https://openrouter.ai/api/v1')
    expect(activeHeaders['X-AI-Model']).toBe('anthropic/claude-3.5-sonnet')

    clearByokConfig()
    expect(isByokActive()).toBe(false)
    expect(localStorage.getItem(BYOK_STORAGE_KEY)).toBeNull()
    expect(getAgentRequestHeaders()['X-AI-Api-Key']).toBeUndefined()
    expect(listener).toHaveBeenCalledTimes(3)

    window.removeEventListener(BYOK_UPDATED_EVENT, listener)
  })
})
