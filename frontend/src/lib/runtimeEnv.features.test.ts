// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  hydrateRuntimeFeatures,
  isAgentEnabled,
  isAuthEnabled,
  isEditorAiEnabled,
  resetRuntimeFeaturesForTest,
  setAgentEnabledOverride,
  setAuthEnabledOverride,
  setRuntimeFeaturesForTest,
  useRuntimeFeatures,
} from './runtimeEnv'
import { extractApiErrorMessage } from './apiError'
import axios from 'axios'
import { scoreResume } from '@/services/api'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function FeaturesHarness({
  onSnapshot,
}: {
  onSnapshot: (snap: ReturnType<typeof useRuntimeFeatures>) => void
}) {
  const snap = useRuntimeFeatures()
  onSnapshot(snap)
  return null
}

describe('runtimeEnv feature flags & hydration', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    localStorage.clear()
    resetRuntimeFeaturesForTest()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => {
      root.unmount()
    })
    container.remove()
    localStorage.clear()
    resetRuntimeFeaturesForTest()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('defaults auth=false, agent=true, editor_ai=true before /api/features loads', () => {
    expect(isAuthEnabled()).toBe(false)
    expect(isAgentEnabled()).toBe(true)
    expect(isEditorAiEnabled()).toBe(true)
  })

  it('hydrates from /api/features and notifies React subscribers via useRuntimeFeatures()', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        auth_enabled: true,
        agent_enabled: true,
        editor_ai_enabled: false,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const latest: { current: ReturnType<typeof useRuntimeFeatures> | null } = { current: null }
    await act(async () => {
      root.render(createElement(FeaturesHarness, { onSnapshot: (snap) => (latest.current = snap) }))
    })

    expect(latest.current?.authEnabled).toBe(false)
    expect(latest.current?.agentEnabled).toBe(true)
    expect(latest.current?.editorAiEnabled).toBe(true)
    expect(latest.current?.loaded).toBe(false)

    await act(async () => {
      await hydrateRuntimeFeatures()
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/features$/)
    expect(isAuthEnabled()).toBe(true)
    expect(isAgentEnabled()).toBe(true)
    expect(isEditorAiEnabled()).toBe(false)
    expect(latest.current?.authEnabled).toBe(true)
    expect(latest.current?.agentEnabled).toBe(true)
    expect(latest.current?.editorAiEnabled).toBe(false)
    expect(latest.current?.loaded).toBe(true)
  })

  it('lets loaded backend runtime flags take precedence over DEV fallback and updates subscribers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          auth_enabled: false,
          agent_enabled: false,
          editor_ai_enabled: true,
        }),
      }),
    )

    await hydrateRuntimeFeatures()
    expect(isAgentEnabled()).toBe(false)
    expect(isAuthEnabled()).toBe(false)

    const latest: { current: ReturnType<typeof useRuntimeFeatures> | null } = { current: null }
    await act(async () => {
      root.render(createElement(FeaturesHarness, { onSnapshot: (snap) => (latest.current = snap) }))
    })
    expect(latest.current?.agentEnabled).toBe(false)

    act(() => {
      setRuntimeFeaturesForTest({ auth_enabled: true, agent_enabled: true, editor_ai_enabled: false })
    })
    expect(latest.current?.authEnabled).toBe(true)
    expect(latest.current?.agentEnabled).toBe(true)
    expect(latest.current?.editorAiEnabled).toBe(false)
  })

  it('honors localStorage overrides over fetched runtime flags', () => {
    setRuntimeFeaturesForTest({ auth_enabled: false, agent_enabled: false, editor_ai_enabled: true })
    expect(isAuthEnabled()).toBe(false)
    expect(isAgentEnabled()).toBe(false)

    setAuthEnabledOverride(true)
    setAgentEnabledOverride(true)
    expect(isAuthEnabled()).toBe(true)
    expect(isAgentEnabled()).toBe(true)

    setAuthEnabledOverride(false)
    setAgentEnabledOverride(false)
    expect(isAuthEnabled()).toBe(false)
    expect(isAgentEnabled()).toBe(false)

    setAuthEnabledOverride(null)
    expect(isAuthEnabled()).toBe(false)
  })

  it('keeps safe defaults when /api/features request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const res = await hydrateRuntimeFeatures()
    expect(res).toBeNull()
    expect(isAuthEnabled()).toBe(false)
    expect(isAgentEnabled()).toBe(true)
    expect(isEditorAiEnabled()).toBe(true)
  })

  it('extracts friendly 503/429 AI error messages cleanly without [object Object]', () => {
    expect(
      extractApiErrorMessage({
        code: 'AI_QUOTA_EXHAUSTED',
        message: '免费 AI 额度暂已用完',
        detail: '当前免费 AI 额度暂已用完，您仍可正常手动编辑简历并免费导出 LaTeX / HTML PDF。',
      }),
    ).toBe('免费 AI 额度暂已用完')

    expect(
      extractApiErrorMessage({
        detail: '当前 IP 短时间内 AI 调用次数已达上限，请稍后再试。',
      }),
    ).toBe('当前 IP 短时间内 AI 调用次数已达上限，请稍后再试。')

    expect(
      extractApiErrorMessage({
        detail: { message: '当前 AI 辅助功能已暂时关闭' },
      }),
    ).toBe('当前 AI 辅助功能已暂时关闭')
  })

  it('scoreResume supports anonymous inline resume_data and unwraps 503/429 error detail', async () => {
    const postSpy = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { resume_id: 'anonymous', overall_score: 88, dimensions: [] },
    })

    const res = await scoreResume(null, '需要熟悉 TypeScript 与 React 18 开发', {
      basic: { name: '张三' },
      experience: [],
    })
    expect(res.overall_score).toBe(88)
    expect(postSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/resume\/score$/),
      {
        jd_text: '需要熟悉 TypeScript 与 React 18 开发',
        resume_data: { basic: { name: '张三' }, experience: [] },
      },
      expect.objectContaining({ headers: expect.any(Object) }),
    )

    postSpy.mockRejectedValueOnce({
      response: {
        status: 503,
        data: {
          code: 'AI_QUOTA_EXHAUSTED',
          message: '当前免费 AI 额度暂已用完',
          detail: '当前免费 AI 额度暂已用完，您仍可正常手动编辑简历并免费导出 LaTeX / HTML PDF。',
        },
      },
    })
    await expect(scoreResume('r1', 'JD text here')).rejects.toThrow('当前免费 AI 额度暂已用完')
  })

  it('isLocalDevAuthEnabled stays false when auth_enabled is false even in DEV', async () => {
    const mod = await import('./runtimeEnv')
    mod.resetRuntimeFeaturesForTest()
    expect(mod.isAuthEnabled()).toBe(false)
    expect(mod.isLocalDevAuthEnabled()).toBe(false)

    mod.setRuntimeFeaturesForTest({ auth_enabled: true, agent_enabled: false, editor_ai_enabled: true })
    expect(mod.isAuthEnabled()).toBe(true)
    expect(mod.isLocalDevAuthEnabled()).toBe(import.meta.env.DEV)
  })
})
