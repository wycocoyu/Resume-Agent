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
const mockRecordPdfDownload = vi.fn()
const mockRenderPDFStream = vi.fn()
const mockSaveAs = vi.fn()
let mockIsAuthenticated = false
let mockAuthEnabled = false

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
  useRuntimeFeatures: () => ({
    authEnabled: mockAuthEnabled,
    agentEnabled: false,
    editorAiEnabled: true,
    auth_enabled: mockAuthEnabled,
    agent_enabled: false,
    editor_ai_enabled: true,
    loaded: true,
  }),
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
  PDFViewerSelector: (props: { scale?: number }) => (
    <div data-testid="pdf-viewer" data-scale={String(props.scale)} />
  ),
}))

vi.mock('file-saver', () => ({
  saveAs: (...args: unknown[]) => mockSaveAs(...args),
}))

vi.mock('../services/api', () => ({
  recordPdfDownload: (...args: unknown[]) => mockRecordPdfDownload(...args),
  renderPDFStream: (...args: unknown[]) => mockRenderPDFStream(...args),
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

describe('SharePage auth toggle & workspace continuation', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.useFakeTimers()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    mockIsAuthenticated = false
    mockAuthEnabled = false
    mockNavigate.mockReset()
    mockOpenModal.mockReset()
    mockSaveResume.mockReset()
    mockSetCurrentResumeId.mockReset()
    mockToastSuccess.mockReset()
    mockToastError.mockReset()
    mockRecordPdfDownload.mockReset()
    mockSaveAs.mockReset()
    mockRenderPDFStream.mockReset()
    mockRenderPDFStream.mockImplementation(() => new Promise(() => {}))
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
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('when authEnabled=false, renders PDF preview & downloads directly without login or recordPdfDownload()', async () => {
    mockIsAuthenticated = false
    mockAuthEnabled = false
    mockSaveResume.mockResolvedValue({ id: 'resume_local_123' })
    mockRenderPDFStream.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
    })

    const buttonsBeforeTimer = Array.from(container.querySelectorAll('button'))
    expect(buttonsBeforeTimer.find((b) => b.textContent?.includes('登录后下载'))).toBeUndefined()
    const localEditBtn = buttonsBeforeTimer.find((b) => b.textContent?.includes('免登录存本机编辑'))
    expect(localEditBtn).toBeDefined()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(350)
    })

    expect(mockRenderPDFStream).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[data-testid="pdf-viewer"]')).not.toBeNull()

    const downloadBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('下载 PDF'),
    )
    expect(downloadBtn).toBeDefined()
    expect(downloadBtn!.disabled).toBe(false)

    await act(async () => {
      downloadBtn!.click()
      await Promise.resolve()
    })

    expect(mockRecordPdfDownload).not.toHaveBeenCalled()
    expect(mockOpenModal).not.toHaveBeenCalled()
    expect(mockSaveAs).toHaveBeenCalledTimes(1)

    await act(async () => {
      localEditBtn!.click()
      await Promise.resolve()
    })

    expect(mockSaveResume).toHaveBeenCalledWith(SHARED_PAYLOAD.data)
    expect(mockSetCurrentResumeId).toHaveBeenCalledWith('resume_local_123')
    expect(mockNavigate).toHaveBeenCalledWith('/workspace/resume_local_123')
    expect(mockToastSuccess).toHaveBeenCalled()
  })

  it('when authEnabled=true and unauthenticated, shows login button and gates PDF preview/download', async () => {
    mockIsAuthenticated = false
    mockAuthEnabled = true

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(350)
    })

    expect(mockRenderPDFStream).not.toHaveBeenCalled()
    const buttons = Array.from(container.querySelectorAll('button'))
    const loginBtn = buttons.find((b) => b.textContent?.includes('登录后下载'))
    const downloadBtn = buttons.find((b) => b.textContent?.includes('下载 PDF'))
    expect(loginBtn).toBeDefined()
    expect(downloadBtn?.disabled).toBe(true)

    await act(async () => {
      loginBtn!.click()
    })
    expect(mockOpenModal).toHaveBeenCalledWith('login')
  })

  it('allows authenticated users to import into cloud workspace and records PDF download', async () => {
    mockIsAuthenticated = true
    mockAuthEnabled = true
    mockSaveResume.mockResolvedValue({ id: 'resume_cloud_456' })
    mockRecordPdfDownload.mockResolvedValue({ unlimited: false, limit: 10, used: 1, remaining: 9 })
    mockRenderPDFStream.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(350)
    })

    const buttons = Array.from(container.querySelectorAll('button'))
    const cloudEditBtn = buttons.find((b) => b.textContent?.includes('导入工作台编辑'))
    const downloadBtn = buttons.find((b) => b.textContent?.includes('下载 PDF'))
    expect(cloudEditBtn).toBeDefined()
    expect(downloadBtn?.disabled).toBe(false)

    await act(async () => {
      downloadBtn!.click()
      await Promise.resolve()
    })
    expect(mockRecordPdfDownload).toHaveBeenCalledTimes(1)
    expect(mockSaveAs).toHaveBeenCalledTimes(1)

    await act(async () => {
      cloudEditBtn!.click()
      await Promise.resolve()
    })

    expect(mockSaveResume).toHaveBeenCalledWith(SHARED_PAYLOAD.data)
    expect(mockSetCurrentResumeId).toHaveBeenCalledWith('resume_cloud_456')
    expect(mockNavigate).toHaveBeenCalledWith('/workspace/resume_cloud_456')
  })

  it('passes zoom scale directly to PDFViewerSelector without CSS transform or maxWidth clipping', async () => {
    mockIsAuthenticated = false
    mockAuthEnabled = false
    mockRenderPDFStream.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))

    await act(async () => {
      root.render(<SharePage />)
    })
    await act(async () => {
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(350)
    })

    const viewer = container.querySelector('[data-testid="pdf-viewer"]') as HTMLElement | null
    expect(viewer).not.toBeNull()
    expect(viewer?.getAttribute('data-scale')).toBe('1')
    expect(viewer?.parentElement?.style.transform).toBe('')
    expect(viewer?.parentElement?.style.maxWidth).toBe('')

    const buttons = Array.from(container.querySelectorAll('button'))
    const zoomOutBtn = buttons.find((b) => b.querySelector('.lucide-zoom-out'))
    expect(zoomOutBtn).toBeDefined()

    await act(async () => {
      zoomOutBtn!.click()
      zoomOutBtn!.click()
    })

    expect(viewer?.getAttribute('data-scale')).toBe('0.8')
  })
})
