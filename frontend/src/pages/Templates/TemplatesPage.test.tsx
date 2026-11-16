// @vitest-environment jsdom

import fs from 'node:fs'
import path from 'node:path'
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mockNavigate = vi.fn()
const mockSaveResume = vi.fn()
const mockSetCurrentResumeId = vi.fn()
const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()
const mockWriteText = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    loading: false,
    openModal: vi.fn(),
  }),
}))

vi.mock('@/pages/WorkspaceLayout', () => ({
  default: ({ children }: { children: ReactNode }) => <div data-testid="workspace-layout">{children}</div>,
}))

vi.mock('@/pages/Builder/templates/ResumeRenderer', () => ({
  default: ({ resumeData, settings }: { resumeData: { personalInfo?: { name?: string } }; settings?: { template?: string } }) => (
    <div data-testid="mock-renderer" data-template={settings?.template || ''}>
      {resumeData.personalInfo?.name || ''}
    </div>
  ),
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

import TemplatesPage from './index'
import { applyRequestedTemplate, parseImportedResumeJson, TEMPLATE_METADATA } from '@/data/templates'
import { DEFAULT_RESUME_TEMPLATE } from '@/data/defaultTemplate'
import { htmlToBullets } from '@/pages/Builder/adapter'
import { TemplateLogo } from '@/pages/Builder/templates/TemplateLogo'
import { ASU_VARIANTS_CONFIG } from '@/pages/Builder/templates/ResumeAsuVariant'
import type { AsuVariantId } from '@/pages/Builder/settings'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('TemplatesPage & template helpers', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    mockNavigate.mockReset()
    mockSaveResume.mockReset()
    mockSetCurrentResumeId.mockReset()
    mockToastSuccess.mockReset()
    mockToastError.mockReset()
    mockWriteText.mockReset().mockResolvedValue(undefined)
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: mockWriteText },
      configurable: true,
    })
  })

  afterEach(async () => {
    await act(async () => {
      root.unmount()
    })
    container.remove()
  })

  it('renders all 27 real Workspace templates, uses static XeLaTeX preview for default, and hides CLI copy for web-only templates', async () => {
    await act(async () => {
      root.render(<TemplatesPage />)
    })
    await flushMicrotasks()

    const cards = container.querySelectorAll('[data-testid^="template-card-"]')
    expect(cards).toHaveLength(TEMPLATE_METADATA.length)
    expect(cards).toHaveLength(27)

    // Classic LaTeX renders authentic XeLaTeX preview image without shadowing SPA /templates route
    const defaultCard = container.querySelector('[data-testid="template-card-default"]') as HTMLElement
    const defaultImg = defaultCard.querySelector('img') as HTMLImageElement
    expect(defaultImg).not.toBeNull()
    expect(defaultImg.getAttribute('src')).toBe('/template-previews/classic-latex-preview.png')
    expect(fs.existsSync(path.resolve(__dirname, '../../../public/templates'))).toBe(false)

    // Web-only template (modern) should NOT expose a broken CLI copy button
    const modernCard = container.querySelector('[data-testid="template-card-modern"]') as HTMLElement
    expect(modernCard).not.toBeNull()
    expect(modernCard.textContent).not.toContain('复制口令')
    expect(modernCard.textContent).toContain('放大预览')

    // CLI-supported ASu template copies Skill prompt
    const asuCard = container.querySelector('[data-testid="template-card-asu-13"]') as HTMLElement
    const copyBtn = Array.from(asuCard.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('复制口令'),
    ) as HTMLButtonElement
    expect(copyBtn).toBeDefined()

    await act(async () => {
      copyBtn.click()
    })
    await flushMicrotasks()

    expect(mockWriteText).toHaveBeenCalledWith('用 $resume-agent 按模板 asu-13 做一份简历')
    expect(mockToastSuccess).toHaveBeenCalled()
  })

  it('navigates directly to /workspace/new?template=xxx for anonymous trial', async () => {
    await act(async () => {
      root.render(<TemplatesPage />)
    })
    await flushMicrotasks()

    const asuCard = container.querySelector('[data-testid="template-card-asu-tech"]') as HTMLElement
    const tryBtn = Array.from(asuCard.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('在线体验'),
    ) as HTMLButtonElement

    await act(async () => {
      tryBtn.click()
    })

    expect(mockNavigate).toHaveBeenCalledWith('/workspace/new?template=asu-tech')
  })

  it('filters templates and imports local resume.json to preview and apply locally', async () => {
    mockSaveResume.mockResolvedValue({ id: 'local_imported_1' })

    await act(async () => {
      root.render(<TemplatesPage />)
    })
    await flushMicrotasks()

    // Filter to LaTeX only
    const latexTab = Array.from(container.querySelectorAll('[role="tab"]')).find((el) =>
      el.textContent?.includes('LaTeX'),
    ) as HTMLButtonElement
    await act(async () => {
      latexTab.click()
    })
    expect(container.querySelectorAll('[data-testid^="template-card-"]')).toHaveLength(1)

    // Switch back to all
    const allTab = Array.from(container.querySelectorAll('[role="tab"]')).find((el) =>
      el.textContent?.includes('全部模板'),
    ) as HTMLButtonElement
    await act(async () => {
      allTab.click()
    })

    // Simulate local resume.json import
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const payload = JSON.stringify({
      basic: { name: '李四', title: 'AI 工程师', email: 'lisi@example.com', phone: '13900001111' },
      education: [{ id: 'e1', school: '清华大学', major: '计算机', degree: '硕士', startDate: '2021-09', endDate: '2024-06' }],
    })
    const fakeFile = { text: async () => payload } as unknown as File
    Object.defineProperty(fileInput, 'files', { value: [fakeFile], configurable: true })

    await act(async () => {
      fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await flushMicrotasks()

    expect(container.textContent).toContain('李四')

    // Apply imported resume with asu-05 into local browser workspace
    const card05 = container.querySelector('[data-testid="template-card-asu-05"]') as HTMLElement
    const applyBtn = Array.from(card05.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('套用模板'),
    ) as HTMLButtonElement

    await act(async () => {
      applyBtn.click()
    })
    await flushMicrotasks()

    expect(mockSaveResume).toHaveBeenCalledTimes(1)
    const savedArg = mockSaveResume.mock.calls[0][0]
    expect(savedArg.templateType).toBe('html')
    expect(savedArg.templateId).toBe('asu-05')
    expect((savedArg.globalSettings?.builderSettings as { template?: string })?.template).toBe('asu-05')
    expect(mockSetCurrentResumeId).toHaveBeenCalledWith('local_imported_1')
    expect(mockNavigate).toHaveBeenCalledWith('/workspace/local_imported_1')
  })

  it('htmlToBullets flattens nested lists cleanly without duplicating child items', () => {
    const nestedHtml =
      '<ul class="custom-list"><li><p><strong>专项一</strong></p><ul class="custom-list"><li><p>子任务 A</p></li><li><p>子任务 B</p></li></ul></li></ul>'
    expect(htmlToBullets(nestedHtml)).toEqual([
      '<strong>专项一</strong>',
      '  子任务 A',
      '  子任务 B',
    ])
  })

  it('applyRequestedTemplate and parseImportedResumeJson handle html, default latex, and invalid JSON', () => {
    const htmlApplied = applyRequestedTemplate(structuredClone(DEFAULT_RESUME_TEMPLATE), 'asu-tech')
    expect(htmlApplied.templateType).toBe('html')
    expect(htmlApplied.templateId).toBe('asu-tech')
    expect((htmlApplied.globalSettings?.builderSettings as { template?: string })?.template).toBe('asu-tech')

    const latexApplied = applyRequestedTemplate(htmlApplied, 'default')
    expect(latexApplied.templateType).toBe('latex')
    expect(latexApplied.templateId).toBe('default')

    const modernApplied = applyRequestedTemplate(structuredClone(DEFAULT_RESUME_TEMPLATE), 'modern')
    expect(modernApplied.templateType).toBe('html')
    expect((modernApplied.globalSettings?.builderSettings as { template?: string })?.template).toBe('modern')

    expect(() => parseImportedResumeJson('not-json')).toThrow('JSON 解析失败')
    expect(() => parseImportedResumeJson('{}')).toThrow('缺少 basic 或 education 字段')
  })

  it('keeps card preview buttons left-aligned and renders TemplateLogo with auto width ratio', async () => {
    await act(async () => {
      root.render(<TemplatesPage />)
    })
    await flushMicrotasks()

    const asuCard = container.querySelector('[data-testid="template-card-asu-tech"]') as HTMLElement
    const previewBtn = asuCard.querySelector('button[aria-label^="放大预览"]') as HTMLButtonElement
    expect(previewBtn.className).toContain('text-left')

    // Under "全部模板", recommended 3 templates sit in a dedicated top row,
    // followed by 16 single-column templates prioritized above a divider, and 8 two-column/sidebar templates below
    const recSection = container.querySelector('[data-testid="recommended-templates-section"]') as HTMLElement
    const otherSection = container.querySelector('[data-testid="other-templates-section"]') as HTMLElement
    const singleSection = container.querySelector('[data-testid="single-column-templates-section"]') as HTMLElement
    const twoColSection = container.querySelector('[data-testid="two-column-templates-section"]') as HTMLElement
    const separators = container.querySelectorAll('[role="separator"]')
    expect(recSection).not.toBeNull()
    expect(otherSection).not.toBeNull()
    expect(singleSection).not.toBeNull()
    expect(twoColSection).not.toBeNull()
    expect(separators).toHaveLength(2)

    const extractIds = (el: Element) =>
      Array.from(el.querySelectorAll('[data-testid^="template-card-"]')).map((node) =>
        node.getAttribute('data-testid')?.replace('template-card-', ''),
      )

    expect(extractIds(recSection)).toEqual(['default', 'latex', 'asu-tech'])
    expect(extractIds(singleSection)).toEqual([
      'swiss-single',
      'modern',
      'clean',
      'asu-01',
      'asu-02',
      'asu-03',
      'asu-04',
      'asu-06',
      'asu-07',
      'asu-09',
      'asu-10',
      'asu-11',
      'asu-12',
      'asu-15',
      'asu-17',
      'asu-18',
    ])
    expect(extractIds(twoColSection)).toEqual([
      'swiss-two-column',
      'modern-two-column',
      'vivid',
      'asu-05',
      'asu-08',
      'asu-13',
      'asu-14',
      'asu-16',
    ])
    expect(otherSection.querySelectorAll('[data-testid^="template-card-"]')).toHaveLength(24)

    // Contract: ASu variant metadata layout matches ASU_VARIANTS_CONFIG column geometry
    for (const tpl of TEMPLATE_METADATA) {
      if (tpl.id.startsWith('asu-') && tpl.id !== 'asu-tech') {
        const cfg = ASU_VARIANTS_CONFIG[tpl.id as AsuVariantId]
        expect(tpl.layout).toBe(cfg.layout === 'single-column' ? 'single' : 'two-column')
      }
    }

    // Recommended tab remains functional and shows the exact same 3 templates
    const recTab = Array.from(container.querySelectorAll('[role="tab"]')).find((el) =>
      el.textContent?.includes('推荐默认'),
    ) as HTMLButtonElement
    await act(async () => {
      recTab.click()
    })
    const recTabIds = Array.from(container.querySelectorAll('[data-testid^="template-card-"]')).map((el) =>
      el.getAttribute('data-testid')?.replace('template-card-', ''),
    )
    expect(recTabIds).toEqual(['default', 'latex', 'asu-tech'])

    await act(async () => {
      root.render(<TemplateLogo src="/api/logos/file/tencent" size={20} alt="腾讯" />)
    })
    const img = container.querySelector('img[alt="腾讯"]') as HTMLImageElement
    expect(img.style.height).toBe('20px')
    expect(img.style.width).toBe('auto')
    expect(img.style.maxWidth).toBe('70px')
  })
})
