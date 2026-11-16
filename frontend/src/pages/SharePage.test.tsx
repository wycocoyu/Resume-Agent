// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mockNavigate = vi.fn()
const mockOpenModal = vi.fn()
const mockSaveResume = vi.fn()
const mockSetCurrentResumeId = vi.fn()
const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()
let mockIsAuthenticated = false

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ shareId: 'share_test_1' }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated,
    loading: false,
    openModal: mockOpenModal,
  }),
}))

vi.mock('@/lib/runtimeEnv', () => ({
  getApiBaseUrl: () => 'http://localhost:9000',
}))

vi.mock('@/services/resumeStorage', () => ({
  saveResume: (...args: unknown[]) => mockSaveResume(...args),
  setCurrentResumeId: (...args: unknown[]) => mockSetCurrentResumeId(...args),
}))

vi.mock('@/lib/toast', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}))

vi.mock('../components/PDFEditor', () => ({
  PDFViewerSelector: () => <div data-testid="pdf-viewer" />,
}))

vi.mock('../services/api', () => ({
  recordPdfDownload: vi.fn(),
  renderPDFStream: vi.fn(() => new Promise(() => {})),
}))

import SharePage from './SharePage'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SHARED_PAYLOAD = {
  success: true,
  name: '测试候选人',
  expires_at: '2026-12-01T00:00:00',
  views: 2,
  data: {
    basic: { name: '测试候选人', title: '后端工程师', email: 'a@b.com', phone: '13800138000', location: '深圳' },
    education: [],
    experience: [],
    projects: [],
    openSource: [],
    awards: [],
    customData: {},
    selfEvaluation: '',
    skillContent: '',
    menuSections: [],
    globalSettings: {},
  },
}

describe('SharePage workspace continuation buttons', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    mockNavigate.mockReset()
    mockOpenModal.mockReset()
    mockSaveResume.mockReset()
    mockSetCurrentResumeId.mockReset()
    mockToastSuccess.mockReset()
    mockToastError.mockReset()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => SHARED_PAYLOAD,
      }))
    )
  })

  afterEach(async () => {
    await act(async () => {
      root.unmount()
    })
    container.remove()
    vi.unstubAllGlobals()
  })

  it('allows anonymous users to import into local browser workspace without login', async () => {
    mockIsAuthenticated = false
    mockSaveResume.mockResolvedValue({ id: 'resume_local_123' })

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
    })

    const buttons = Array.from(container.querySelectorAll('button'))
    const localEditBtn = buttons.find((b) => b.textContent?.includes('免登录存本机编辑'))
    const loginBtn = buttons.find((b) => b.textContent?.includes('登录后下载'))
    expect(localEditBtn).toBeDefined()
    expect(loginBtn).toBeDefined()

    await act(async () => {
      localEditBtn!.click()
      await Promise.resolve()
    })

    expect(mockSaveResume).toHaveBeenCalledWith(SHARED_PAYLOAD.data)
    expect(mockSetCurrentResumeId).toHaveBeenCalledWith('resume_local_123')
    expect(mockNavigate).toHaveBeenCalledWith('/workspace/resume_local_123')
    expect(mockToastSuccess).toHaveBeenCalled()
  })

  it('allows authenticated users to import into cloud workspace', async () => {
    mockIsAuthenticated = true
    mockSaveResume.mockResolvedValue({ id: 'resume_cloud_456' })

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
    })

    const buttons = Array.from(container.querySelectorAll('button'))
    const cloudEditBtn = buttons.find((b) => b.textContent?.includes('导入工作台编辑'))
    expect(cloudEditBtn).toBeDefined()

    await act(async () => {
      cloudEditBtn!.click()
      await Promise.resolve()
    })

    expect(mockSaveResume).toHaveBeenCalledWith(SHARED_PAYLOAD.data)
    expect(mockSetCurrentResumeId).toHaveBeenCalledWith('resume_cloud_456')
    expect(mockNavigate).toHaveBeenCalledWith('/workspace/resume_cloud_456')
  })
})
