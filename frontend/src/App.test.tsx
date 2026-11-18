// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    loading: false,
  }),
}))

vi.mock('./contexts/ResumeContext', () => ({
  ResumeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('./lib/runtimeEnv', () => ({
  canUseAdminFeature: () => false,
  useRuntimeFeatures: () => ({
    agentEnabled: false,
    authEnabled: false,
    editorAiEnabled: true,
    loaded: true,
  }),
}))

vi.mock('./components/ThemeInit', () => ({
  ThemeInit: () => null,
}))

vi.mock('./components/SkinInit', () => ({
  SkinInit: () => null,
}))

vi.mock('./components/AuthModal', () => ({
  AuthModal: () => null,
}))

vi.mock('./lib/toast', () => ({
  Toaster: () => null,
}))

vi.mock('./lib/confirm', () => ({
  ConfirmHost: () => null,
}))

vi.mock('./pages/ResumeDashboard', () => ({
  default: () => <div data-testid="resume-dashboard" />,
}))

vi.mock('./pages/LandingPage', () => ({
  default: () => <div data-testid="landing-page">CocoCV Landing</div>,
}))

import App from './App'
import { LATEST_CHANGELOG } from './data/changelog'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

async function flushUi() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 20))
  })
}

describe('App first-visit modals', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    localStorage.clear()
    window.history.pushState({}, '', '/')
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
  })

  it('does not show the removed BetaNoticeModal on first visit while keeping ChangelogModal intact', async () => {
    await act(async () => {
      root.render(<App />)
    })
    await flushUi()

    expect(container.textContent).toContain('CocoCV Landing')
    expect(container.textContent).toContain('有什么新变化')
    expect(container.textContent).toContain(`v${LATEST_CHANGELOG.version}`)
    expect(container.textContent).not.toContain('当前为 Beta 测试版')
    expect(container.textContent).not.toContain('感谢你愿意陪它一起成长')
    expect(localStorage.getItem('seen_beta_notice')).toBeNull()
  })
})
