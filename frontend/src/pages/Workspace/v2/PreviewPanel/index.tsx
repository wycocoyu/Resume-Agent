/**
 * 预览面板组件（第三列）
 * 支持 LaTeX PDF 渲染和 HTML 模板实时预览
 */
import { useState, useRef, useEffect, type ReactNode } from 'react'
import { Download, RefreshCw, FileText, Sparkles, Minus, Plus, AlertTriangle, Eye } from 'lucide-react'
import { cn } from '../../../../lib/utils'
import { PDFViewerSelector } from '../../../../components/PDFEditor'
import ResumeRenderer from '../../../Builder/templates/ResumeRenderer'
import { PaginatedPreview } from '../../../Builder/components/PaginatedPreview'
import { toBuilderResumeData } from '../../../Builder/adapter'
import { fetchLogos, onLogosLoaded } from '../constants/companyLogos'
import { fetchSchoolLogos } from '../constants/schoolLogos'
import { withSettingsDefaults } from '../../../Builder/settings'
import { PAGE_DIMENSIONS } from '../../../Builder/pageDimensions'
import { FloatingPreviewToolbar } from '../components/FloatingPreviewToolbar'
import type { ResumeData } from '../types'
import type { PDFRenderMode } from '@/services/pdfRenderMode'
import { logPDFRenderModeChange } from '@/services/api'

// 与 backend/latex_generator.py 的 margin_map 保持一致（单位：英寸），用于换算边距参考线的比例
const LATEX_MARGIN_INCHES: Record<string, number> = {
  tight: 0.25,
  compact: 0.3,
  standard: 0.4,
  relaxed: 0.5,
  wide: 0.6,
}
// A4 页面尺寸（英寸），LaTeX 生成器固定用 a4paper
const A4_WIDTH_IN = 8.27
const A4_HEIGHT_IN = 11.69

interface PreviewPanelProps {
  resumeData?: ResumeData
  pdfBlob: Blob | null
  loading: boolean
  progress: string
  renderError?: string | null
  autoRenderPending?: boolean
  renderMode?: PDFRenderMode
  canUseRemoteRender?: boolean
  onRenderModeChange?: (mode: PDFRenderMode) => void
  onRender: () => void
  onDownload: () => void
  onEngineChange?: (engine: 'latex' | 'html') => void
  /** 顶栏操作按钮群(保存/皮肤/导入/导出),内联到工具栏右侧;原来是独立整行 */
  toolbarActions?: ReactNode
}

export function PreviewPanel({
  resumeData,
  pdfBlob,
  loading,
  progress,
  renderError = null,
  autoRenderPending = false,
  renderMode = 'local',
  canUseRemoteRender = false,
  onRenderModeChange = () => {},
  onRender,
  onDownload,
  onEngineChange,
  toolbarActions,
}: PreviewPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScale, setAutoScale] = useState(1.0)
  const [userScale, setUserScale] = useState<number | null>(null)
  const [scalePercentInput, setScalePercentInput] = useState('')
  const [numPages, setNumPages] = useState(0)
  const [showMargin, setShowMargin] = useState(false)

  // Logo 加载时机：HTML 模板的公司/学校 Logo 由 adapter 用 getLogoUrl(key) 解析成 URL，
  // 依赖 logos 已缓存。预览可能在"没进过编辑经历面板"时就渲染，此处主动拉取并在到货后
  // bump 触发重渲（adapter 在渲染中内联调用，重渲即重新解析）。
  const [, setLogosVersion] = useState(0)
  useEffect(() => {
    let alive = true
    const bump = () => { if (alive) setLogosVersion((v) => v + 1) }
    void fetchLogos().then(bump).catch(() => {})
    void fetchSchoolLogos().then(bump).catch(() => {})
    const off = onLogosLoaded(bump) // 覆盖"别处已触发加载"的场景
    return () => { alive = false; off() }
  }, [])

  const isHTMLTemplate = resumeData?.templateType === 'html'
  const marginIn = LATEX_MARGIN_INCHES[resumeData?.globalSettings?.latexMargin || 'standard']
  const marginRatio = { x: marginIn / A4_WIDTH_IN, y: marginIn / A4_HEIGHT_IN }

  const MIN_SCALE = 0.5
  const MAX_SCALE = 2.5
  const ZOOM_STEP = 0.25
  const effectiveScale = userScale !== null ? userScale : autoScale

  // 根据容器宽度计算「适应宽度」缩放
  useEffect(() => {
    if (!containerRef.current || !pdfBlob || isHTMLTemplate) return
    const updateScale = () => {
      const container = containerRef.current
      if (!container) return
      const containerWidth = container.clientWidth - 16
      const baseWidth = 595
      const newScale = containerWidth / baseWidth
      setAutoScale((prev) => {
        const clamped = Math.max(MIN_SCALE, Math.min(newScale, MAX_SCALE))
        // 忽略微小变化：滚动条出现/消失会让容器宽度小幅抖动，
        // 若据此反复改 scale 会触发 PDF 反复重绘（闪烁），加阈值把它挡掉
        return Math.abs(clamped - prev) < 0.01 ? prev : clamped
      })
    }
    updateScale()
    const ro = new ResizeObserver(updateScale)
    ro.observe(containerRef.current)
    window.addEventListener('resize', updateScale)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', updateScale)
    }
  }, [pdfBlob, isHTMLTemplate])

  // 换简历/重新渲染时旧页数已不准确，清空等待新 PDF 上报
  useEffect(() => {
    if (!pdfBlob) setNumPages(0)
  }, [pdfBlob])

  const handleZoomOut = () => {
    const next = Math.max(MIN_SCALE, effectiveScale - ZOOM_STEP)
    setUserScale(next)
    setScalePercentInput('')
  }
  const handleZoomIn = () => {
    const next = Math.min(MAX_SCALE, effectiveScale + ZOOM_STEP)
    setUserScale(next)
    setScalePercentInput('')
  }
  const handleFitWidth = () => {
    setUserScale(null)
    setScalePercentInput('')
  }

  const displayPercent = Math.round(effectiveScale * 100)
  // 错误态来自 usePDFOperations 的独立 renderError：失败设置、渲染成功才清除（常驻），
  // 渲染中让位给进度显示，结束后若仍未成功则错误横幅回来——不会被下一次渲染永久顶掉。
  const hasRenderError = !isHTMLTemplate && !loading && !!renderError
  const showStatus = !isHTMLTemplate && (loading || autoRenderPending || hasRenderError)
  const statusText = loading
    ? (progress || '正在更新 PDF 预览...')
    : hasRenderError
      ? renderError!
      : '已记录修改:停止输入 2 秒后更新预览'

  const applyPercentInput = (raw: string) => {
    const n = parseFloat(raw.replace(/[^\d.]/g, ''))
    if (!Number.isFinite(n)) return
    const scale = Math.max(50, Math.min(250, n)) / 100
    setUserScale(scale)
    setScalePercentInput('')
  }

  return (
    <div className="h-full flex flex-col">
      {/* 工具栏 */}
      <div
        className={cn(
          'flex items-center justify-between gap-3 px-4 py-3 flex-wrap',
          'bg-white/70 fresh:bg-white dark:bg-slate-800/70',
          'backdrop-blur-sm fresh:backdrop-blur-none',
          'border-b border-slate-200/50 dark:border-slate-700/50'
        )}
      >
        {/* 左组: 双引擎切换 (LaTeX / HTML) + 渲染按钮 + 缩放·边距·页数 */}
        <div className="flex items-center gap-3 flex-wrap min-w-0">
          {/* 双引擎切换 Segmented Control */}
          <div className="inline-flex items-center p-0.5 rounded-none fresh:rounded-md border border-black fresh:border-slate-300 dark:border-white bg-[#F0F0E8] fresh:bg-slate-100 dark:bg-slate-800 shadow-[1px_1px_0px_0px_#000000] fresh:shadow-sm">
            <button
              type="button"
              onClick={() => onEngineChange?.('latex')}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded-none fresh:rounded-sm transition-all',
                !isHTMLTemplate
                  ? 'bg-[#4285F4] text-white shadow-[1px_1px_0px_0px_#000000]'
                  : 'text-slate-700 dark:text-slate-300 hover:text-black dark:hover:text-white'
              )}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>LaTeX 精排</span>
            </button>
            <button
              type="button"
              onClick={() => onEngineChange?.('html')}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded-none fresh:rounded-sm transition-all',
                isHTMLTemplate
                  ? 'bg-emerald-600 text-white shadow-[1px_1px_0px_0px_#000000]'
                  : 'text-slate-700 dark:text-slate-300 hover:text-black dark:hover:text-white'
              )}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>HTML 实时</span>
            </button>
          </div>

          {/* HTML 模板：显示实时预览标签 */}
          {isHTMLTemplate && (
            <span className="px-2.5 py-0.5 text-xs font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 dark:border-white shadow-[1px_1px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[1px_1px_0px_0px_#ffffff]">
              即时呈现
            </span>
          )}

          {/* LaTeX 模板：显示渲染按钮 */}
          {!isHTMLTemplate && (
            <div className="flex items-center gap-3">
              {/* 渲染按钮 */}
              <button
                onClick={onRender}
                disabled={loading}
                className={cn(
                  'group relative px-6 py-2.5 rounded-none fresh:rounded-md border-2 fresh:border border-black fresh:border-slate-200 overflow-hidden',
                  'bg-[#4285F4] text-white text-sm font-bold tracking-tight',
                  'disabled:opacity-60 disabled:cursor-not-allowed',
                  'transition-all',
                  'shadow-[3px_3px_0px_0px_#000000] fresh:shadow-md hover:bg-[#3367D6] hover:shadow-none fresh:hover:shadow-sm hover:translate-x-[2px] hover:translate-y-[2px] active:translate-x-[3px] active:translate-y-[3px]',
                  'disabled:hover:shadow-[3px_3px_0px_0px_#000000] disabled:hover:translate-x-0 disabled:hover:translate-y-0',
                  'dark:border-white dark:shadow-[3px_3px_0px_0px_#ffffff]'
                )}
              >
                <span className="relative flex items-center gap-2">
                  <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
                  {loading ? '更新中...' : autoRenderPending ? '立即更新 PDF' : '渲染 PDF'}
                </span>
              </button>
              {canUseRemoteRender && (
                <label className="relative">
                  <span className="sr-only">选择 PDF 渲染环境</span>
                  <select
                    value={renderMode}
                    onChange={(e) => {
                      const nextMode = e.target.value as PDFRenderMode
                      console.info('[PDF TRACE][render-mode:change]', {
                        from: renderMode,
                        to: nextMode,
                      })
                      void logPDFRenderModeChange(renderMode, nextMode)
                      onRenderModeChange(nextMode)
                    }}
                    className={cn(
                      'min-w-[120px] rounded-lg border px-4 py-2.5 pr-8 text-sm font-semibold',
                      'bg-white text-slate-700 border-slate-200 shadow-sm',
                      'hover:border-slate-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100',
                      'dark:bg-slate-700 dark:text-slate-100 dark:border-slate-600 dark:hover:border-slate-500 dark:focus:ring-blue-900/40'
                    )}
                    title="选择 PDF 渲染环境"
                  >
                    <option value="local">本地渲染</option>
                    <option value="remote">远程渲染</option>
                  </select>
                </label>
              )}
            </div>
          )}

        </div>

        {/* 右组:保存 / 皮肤 / 导入 / 导出(原独立整行,现内联到此) */}
        {toolbarActions && <div className="shrink-0 flex items-center">{toolbarActions}</div>}
      </div>

      {/* 进度提示 */}
      {showStatus && (
        <div className={cn(
          "px-4 py-2.5 text-sm font-medium flex items-center gap-2",
          "fresh:bg-none",
          hasRenderError
            ? "bg-gradient-to-r fresh:bg-red-50 from-red-50 to-rose-50 dark:from-red-900/20 dark:to-rose-900/20 text-red-600 dark:text-red-400 border-b border-red-100 dark:border-red-800/30 whitespace-pre-line"
            : loading
              ? "bg-gradient-to-r fresh:bg-blue-50 from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 text-indigo-600 dark:text-indigo-400 border-b border-indigo-100 dark:border-indigo-800/30"
              : "bg-gradient-to-r fresh:bg-amber-50 from-amber-50 to-orange-50 dark:from-amber-900/15 dark:to-orange-900/15 text-amber-700 dark:text-amber-300 border-b border-amber-100 dark:border-amber-800/30"
        )}>
          {hasRenderError ? (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          ) : loading ? (
            <Sparkles className="w-4 h-4 animate-pulse" />
          ) : (
            <FileText className="w-4 h-4" />
          )}
          <span className="min-w-0 flex-1">{statusText}</span>
          {hasRenderError && (
            <button
              type="button"
              onClick={onRender}
              className="shrink-0 rounded-md border border-red-300 dark:border-red-700 px-2 py-0.5 text-xs font-medium hover:bg-red-100 dark:hover:bg-red-900/40"
            >
              重试
            </button>
          )}
        </div>
      )}

      {/* 预览区域：PDF 时仅 PDF 区域滚动，缩放栏固定在底部；HTML/空状态时整区可滚动 */}
      <div
        ref={isHTMLTemplate || !pdfBlob ? containerRef : undefined}
        className={cn(
          'flex-1 p-2 bg-[#F6F3EC] fresh:bg-slate-100',
          isHTMLTemplate || pdfBlob ? 'flex flex-col min-h-0 overflow-hidden' : 'overflow-auto'
        )}
      >
        {isHTMLTemplate ? (
          // HTML 模板：Builder 真分页预览（消费 globalSettings.builderSettings，
          // 页面按 A4/US Letter 真实尺寸分页，切换纸张有明确的视觉差异）
          (() => {
            const builderSettings = withSettingsDefaults(resumeData!.globalSettings?.builderSettings)
            const builderResumeData = toBuilderResumeData(resumeData!)
            const pageDims = PAGE_DIMENSIONS[builderSettings.pageSize]
            return (
              <>
                <PaginatedPreview resumeData={builderResumeData} settings={builderSettings} />
                {/* 导出源：屏幕外的连续渲染，供 Workspace 的 handleDownloadHtmlPDF 用
                    document.querySelector('.html-template-container') + html2pdf 抓取。
                    分页预览带缩放栏/页码/分页线等编辑态 UI，不适合直接当导出源；
                    这里保留与旧版一致的干净连续容器，导出结果不变。 */}
                <div aria-hidden="true" className="pointer-events-none" style={{ position: 'fixed', left: -9999, top: 0 }}>
                  <div
                    className="html-template-container bg-white shadow-lg"
                    style={{ width: `${pageDims.width}mm`, minHeight: `${pageDims.height}mm` }}
                  >
                    <ResumeRenderer resumeData={builderResumeData} settings={builderSettings} />
                  </div>
                </div>
              </>
            )
          })()
        ) : (
          // LaTeX 模板：PDF 预览（缩放/边距/页数在 PDF 渲染区下方的底部栏）
          <>
            {pdfBlob ? (
              <div className="flex-1 flex flex-col min-h-0 bg-[#F6F3EC] fresh:bg-slate-100 overflow-hidden relative">
                <div
                  ref={containerRef}
                  className="flex-1 min-h-0 overflow-auto p-2"
                  style={{ scrollbarGutter: 'stable' }}
                >
                  <div className="flex justify-center w-full">
                    <PDFViewerSelector
                      pdfBlob={pdfBlob}
                      scale={effectiveScale}
                      onNumPagesChange={setNumPages}
                      showMarginGuides={showMargin}
                      marginRatio={marginRatio}
                    />
                  </div>
                </div>

                {/* 浮动操作栏：支持引擎切换、缩放、边距及快速导出 */}
                <FloatingPreviewToolbar
                  engine="latex"
                  onEngineChange={onEngineChange}
                  scale={effectiveScale}
                  onZoomIn={handleZoomIn}
                  onZoomOut={handleZoomOut}
                  onFitWidth={handleFitWidth}
                  isUserScale={userScale !== null}
                  showMargin={showMargin}
                  onToggleMargin={() => setShowMargin((s) => !s)}
                  onDownload={onDownload}
                />

                {/* 缩放 + 边距 + 页数：从顶部工具栏挪到 PDF 渲染区下方（第三列底部） */}
                <div className="shrink-0 flex items-center justify-center gap-1 flex-wrap px-4 py-2 border-t border-slate-200/50 dark:border-slate-700/50 bg-white/70 dark:bg-slate-800/70 backdrop-blur-sm">
                  <div className="flex items-center gap-0.5">
                    <button
                      type="button"
                      onClick={handleZoomOut}
                      disabled={effectiveScale <= MIN_SCALE}
                      className={cn(
                        'inline-flex items-center justify-center h-8 w-8 rounded-none fresh:rounded-md',
                        'bg-transparent border-none text-slate-700 dark:text-slate-300',
                        'hover:bg-slate-100 dark:hover:bg-white/10 transition-colors',
                        'disabled:opacity-50 disabled:pointer-events-none'
                      )}
                      title="缩小"
                    >
                      <Minus className="w-4 h-4" />
                    </button>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={scalePercentInput !== '' ? scalePercentInput : String(displayPercent)}
                      onChange={(e) => setScalePercentInput(e.target.value)}
                      onBlur={() => scalePercentInput !== '' && applyPercentInput(scalePercentInput)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.currentTarget.blur()
                        }
                      }}
                      className={cn(
                        'w-10 text-center font-mono fresh:font-sans text-xs rounded-none fresh:rounded-md bg-transparent border-none',
                        'text-slate-500 dark:text-slate-400',
                        'focus:outline-none focus:ring-1 focus:ring-blue-700 fresh:focus:ring-blue-200'
                      )}
                      title="点击输入缩放比例（50–250）"
                    />
                    <span className="font-mono fresh:font-sans text-xs text-slate-500 dark:text-slate-400">%</span>
                    <button
                      type="button"
                      onClick={handleZoomIn}
                      disabled={effectiveScale >= MAX_SCALE}
                      className={cn(
                        'inline-flex items-center justify-center h-8 w-8 rounded-none fresh:rounded-md',
                        'bg-transparent border-none text-slate-700 dark:text-slate-300',
                        'hover:bg-slate-100 dark:hover:bg-white/10 transition-colors',
                        'disabled:opacity-50 disabled:pointer-events-none'
                      )}
                      title="放大"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                    {userScale !== null && (
                      <button
                        type="button"
                        onClick={handleFitWidth}
                        className="ml-1 font-mono fresh:font-sans text-xs text-blue-700 dark:text-blue-400 hover:underline"
                      >
                        适应宽度
                      </button>
                    )}
                  </div>

                  <div className="w-px h-5 bg-slate-300 dark:bg-white/20 mx-2" />

                  {/* 边距：虚线框 + 四角标记叠加在 PDF 页面上，随缩放联动 */}
                  <button
                    type="button"
                    onClick={() => setShowMargin((s) => !s)}
                    className={cn(
                      'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-none fresh:rounded-md font-mono fresh:font-sans text-xs transition-colors',
                      showMargin
                        ? 'bg-slate-200 dark:bg-white/10 border border-black fresh:border-slate-200 dark:border-white text-black dark:text-white'
                        : 'bg-transparent border-none text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/10'
                    )}
                    title="显示/隐藏边距参考线"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    边距
                  </button>

                  <div className="w-px h-5 bg-slate-300 dark:bg-white/20 mx-2" />

                  {/* 页数：由 PDFViewer 加载完成后通过 onNumPagesChange 上报 */}
                  <div className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
                    <FileText className="w-3.5 h-3.5" />
                    <span className="font-mono fresh:font-sans text-xs whitespace-nowrap">
                      {numPages > 0 ? `共 ${numPages} 页` : '—'}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-lg fresh:rounded-md bg-gradient-to-br fresh:bg-none fresh:bg-white from-slate-100 to-slate-200 dark:from-slate-700 dark:to-slate-800 fresh:border fresh:border-slate-200 flex items-center justify-center">
                    <FileText className="w-10 h-10 text-slate-400 dark:text-slate-500" />
                  </div>
                  <p className="text-lg font-medium text-slate-500 dark:text-slate-400 mb-2">暂无 PDF 预览</p>
                  <p className="text-sm text-slate-400 dark:text-slate-500">
                    填写简历内容后：点击「渲染 PDF」生成预览
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default PreviewPanel
