// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HeaderActions } from './components/HeaderActions'
import { PreviewPanel } from './PreviewPanel'
import EditPreviewLayout, {
  DEFAULT_EDIT_PANEL_WIDTH,
  MAX_EDIT_PANEL_WIDTH,
  MIN_EDIT_PANEL_WIDTH,
  RESERVED_PREVIEW_WIDTH,
  SIDE_PANEL_WIDTH,
  getDefaultEditPanelWidth,
  getMaxEditPanelWidth,
  resolveEditPanelWidth,
} from './EditPreviewLayout'
import type { ResumeData } from './types'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    loading: false,
    user: null,
    openModal: vi.fn(),
  }),
}))

vi.mock('./constants/companyLogos', () => ({
  fetchLogos: vi.fn(async () => []),
  onLogosLoaded: vi.fn(() => () => {}),
}))

vi.mock('./constants/schoolLogos', () => ({
  fetchSchoolLogos: vi.fn(async () => []),
}))

vi.mock('./SidePanel', () => ({
  default: () => <div data-testid="mock-side-panel" />,
}))

vi.mock('./EditPanel', () => ({
  default: () => <div data-testid="mock-edit-panel" />,
}))

vi.mock('./SidePanel/SettingsDrawer', () => ({
  default: () => <div data-testid="mock-settings-drawer" />,
}))

vi.mock('../../../components/PDFEditor', () => ({
  PDFViewerSelector: () => <div data-testid="mock-pdf-viewer" />,
}))

vi.mock('../../Builder/templates/ResumeRenderer', () => ({
  default: () => <div data-testid="mock-html-renderer" />,
}))

vi.mock('../../Builder/components/PaginatedPreview', () => ({
  PaginatedPreview: () => <div data-testid="mock-paginated-preview" />,
}))

vi.mock('./components/FloatingPreviewToolbar', () => ({
  FloatingPreviewToolbar: () => <div data-testid="mock-floating-toolbar" />,
}))

const MINIMAL_RESUME: ResumeData = {
  templateType: 'latex',
  basic: {
    name: '张三',
    title: '后端开发工程师',
    email: 'test@example.com',
    phone: '13800138000',
    location: '北京',
    website: '',
    birthDate: '',
    workYears: '',
  },
  education: [],
  workExperience: [],
  experience: [],
  projects: [],
  openSource: [],
  awards: [],
  skillContent: '',
  selfEvaluation: '',
  customData: {},
  menuSections: [{ id: 'basic', title: '基本信息', enabled: true, order: 0 }],
  globalSettings: {},
} as unknown as ResumeData

describe('EditPreviewLayout responsive sizing & PreviewPanel wrapping', () => {
  let container: HTMLDivElement
  let root: Root | null = null

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
  })

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount()
      })
      root = null
    }
    container.remove()
    vi.restoreAllMocks()
  })

  it('computes desktop & laptop widths that preserve >= RESERVED_PREVIEW_WIDTH when un-dragged', () => {
    // Fallback when unmeasured
    expect(getDefaultEditPanelWidth(0)).toBe(DEFAULT_EDIT_PANEL_WIDTH)
    expect(getMaxEditPanelWidth(0)).toBe(MAX_EDIT_PANEL_WIDTH)

    // 1920px with expanded 200px sidebar => container = 1720px: keeps 700px
    expect(getDefaultEditPanelWidth(1720)).toBe(700)

    // 1512px with expanded 200px sidebar => container = 1312px: 607px edit + 420px preview
    const w1512 = getDefaultEditPanelWidth(1312)
    expect(w1512).toBe(607)
    expect(1312 - SIDE_PANEL_WIDTH - 5 - w1512).toBe(RESERVED_PREVIEW_WIDTH)

    // 1440px with expanded 200px sidebar => container = 1240px: 535px edit + 420px preview
    const w1440Expanded = getDefaultEditPanelWidth(1240)
    expect(w1440Expanded).toBe(535)
    expect(1240 - SIDE_PANEL_WIDTH - 5 - w1440Expanded).toBe(RESERVED_PREVIEW_WIDTH)

    // 1440px with collapsed 96px sidebar => container = 1344px: 639px edit + 420px preview
    const w1440Collapsed = getDefaultEditPanelWidth(1344)
    expect(w1440Collapsed).toBe(639)
    expect(1344 - SIDE_PANEL_WIDTH - 5 - w1440Collapsed).toBe(RESERVED_PREVIEW_WIDTH)

    // 1280px with expanded 200px sidebar => container = 1080px: floored at 400px edit, leaving 395px preview
    expect(getDefaultEditPanelWidth(1080)).toBe(MIN_EDIT_PANEL_WIDTH)
    expect(1080 - SIDE_PANEL_WIDTH - 5 - MIN_EDIT_PANEL_WIDTH).toBe(395)
  })

  it('preserves user custom dragged width while capping safely when viewport narrows', () => {
    // User dragged to 900px on 1920px desktop
    expect(
      resolveEditPanelWidth({ containerWidth: 1720, customWidth: 900 }),
    ).toBe(900)

    // Shrinking window to 1280px (container 1080) caps edit width to preserve >= 260px preview
    expect(
      resolveEditPanelWidth({ containerWidth: 1080, customWidth: 900 }),
    ).toBe(535)

    // Returning to 1920px restores 900px custom preference cleanly
    expect(
      resolveEditPanelWidth({ containerWidth: 1720, customWidth: 900 }),
    ).toBe(900)
  })

  it('allows PreviewPanel toolbarActions to shrink & wrap instead of forcing shrink-0 overflow', async () => {
    root = createRoot(container)
    await act(async () => {
      root!.render(
        <PreviewPanel
          resumeData={MINIMAL_RESUME}
          pdfBlob={null}
          loading={false}
          progress=""
          onRender={vi.fn()}
          onDownload={vi.fn()}
          toolbarActions={
            <HeaderActions
              saveStatus="saved"
              onGlobalAIImport={vi.fn()}
              onExportJSON={vi.fn()}
              onImportJSON={vi.fn()}
              resumeData={MINIMAL_RESUME}
              onDownloadPDF={vi.fn()}
            />
          }
        />,
      )
      await Promise.resolve()
    })

    const skinBtn = container.querySelector('button[aria-label="界面皮肤"]')
    expect(skinBtn).toBeTruthy()
    expect(skinBtn?.className).toContain('whitespace-nowrap')

    const actionsContainer = skinBtn?.parentElement
    expect(actionsContainer?.className).toContain('flex-wrap')
    expect(actionsContainer?.className).toContain('min-w-0')
    expect(actionsContainer?.className).toContain('max-w-full')
    expect(actionsContainer?.className).toContain('justify-start')

    const toolbarActionsWrapper = actionsContainer?.parentElement
    expect(toolbarActionsWrapper?.className).toContain('min-w-0')
    expect(toolbarActionsWrapper?.className).toContain('max-w-full')
    expect(toolbarActionsWrapper?.className).not.toContain('shrink-0')
  })

  it('adds min-w-0 on preview pane wrapper and updates width on ResizeObserver changes', async () => {
    let observedEl: Element | null = null
    let currentWidth = 1240
    let roCallback: ResizeObserverCallback | null = null

    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        roCallback = cb
      }
      observe(target: Element) {
        observedEl = target
      }
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
      if (
        this === observedEl ||
        (this.classList?.contains('flex-1') &&
          this.classList?.contains('min-w-0') &&
          this.classList?.contains('overflow-hidden') &&
          Boolean(this.querySelector?.('[data-testid="mock-edit-panel"]')))
      ) {
        return currentWidth
      }
      return 0
    })

    root = createRoot(container)
    await act(async () => {
      root!.render(
        <EditPreviewLayout
          resumeData={MINIMAL_RESUME}
          setResumeData={vi.fn()}
          activeSection="basic"
          setActiveSection={vi.fn()}
          toggleSectionVisibility={vi.fn()}
          updateMenuSections={vi.fn()}
          reorderSections={vi.fn()}
          updateGlobalSettings={vi.fn()}
          addCustomSection={vi.fn()}
          updateBasicInfo={vi.fn()}
          updateProject={vi.fn()}
          deleteProject={vi.fn()}
          reorderProjects={vi.fn()}
          updateExperience={vi.fn()}
          deleteExperience={vi.fn()}
          reorderExperiences={vi.fn()}
          updateEducation={vi.fn()}
          deleteEducation={vi.fn()}
          reorderEducations={vi.fn()}
          updateOpenSource={vi.fn()}
          deleteOpenSource={vi.fn()}
          reorderOpenSources={vi.fn()}
          updateAward={vi.fn()}
          deleteAward={vi.fn()}
          reorderAwards={vi.fn()}
          addCustomItem={vi.fn()}
          updateCustomItem={vi.fn()}
          deleteCustomItem={vi.fn()}
          updateSelfEvaluation={vi.fn()}
          updateSkillContent={vi.fn()}
          handleAIImport={vi.fn()}
          pdfBlob={null}
          loading={false}
          progress=""
          handleRender={vi.fn()}
          handleDownload={vi.fn()}
          toolbarActions={
            <HeaderActions
              saveStatus="saved"
              onGlobalAIImport={vi.fn()}
              resumeData={MINIMAL_RESUME}
            />
          }
        />,
      )
      await Promise.resolve()
    })

    const previewBtn = container.querySelector('button[aria-label="界面皮肤"]')
    const previewWrapper = previewBtn?.closest('div.flex-1.overflow-hidden.min-w-0')
    expect(previewWrapper).toBeTruthy()

    const editCol = container.querySelector('[data-testid="mock-edit-panel"]')?.parentElement
    // Synchronous useLayoutEffect sets 1440px expanded width (1240 container -> 535px edit) before paint
    expect(editCol?.style.width).toBe('535px')

    // Simulate sidebar collapse enlarging container to 1344px -> 639px
    currentWidth = 1344
    act(() => {
      roCallback?.([], {} as ResizeObserver)
    })
    expect(editCol?.style.width).toBe('639px')
  })
})
