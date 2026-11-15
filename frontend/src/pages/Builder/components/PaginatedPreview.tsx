/**
 * 分页实时预览 —— 移植自 Resume-Matcher components/preview/paginated-preview.tsx。
 * WYSIWYG:真实页面尺寸 + 边距参考线 + 自动分页;隐藏测量容器渲染全量内容供 usePagination 切页。
 * 差异:label 硬编码 EN;去 i18n label props;token 换算。
 */
import React, { useRef, useState, useCallback, useEffect } from 'react'
import { ZoomIn, ZoomOut, Eye, FileText } from 'lucide-react'
import type { BuilderResumeData } from '../types'
import type { TemplateSettings } from '../settings'
import { ResumeRenderer } from '../templates/ResumeRenderer'
import { PageContainer } from './PageContainer'
import { usePagination } from './usePagination'
import { SwissButton } from './SwissButton'
import { PAGE_DIMENSIONS, mmToPx, getContentAreaPx } from '../pageDimensions'

interface PaginatedPreviewProps {
  resumeData: BuilderResumeData
  settings: TemplateSettings
}

const MIN_ZOOM = 0.4
const MAX_ZOOM = 1.5
const ZOOM_STEP = 0.1

export function PaginatedPreview({ resumeData, settings }: PaginatedPreviewProps) {
  const measurementRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(0.6)
  const [showMargins, setShowMargins] = useState(false)
  const [autoZoom, setAutoZoom] = useState(true)
  // 页面边距由 PageContainer 承担,渲染体自身边距归零
  const resumeSettings: TemplateSettings = {
    ...settings,
    margins: { top: 0, bottom: 0, left: 0, right: 0 },
  }

  const { pages, isCalculating } = usePagination({
    pageSize: settings.pageSize,
    margins: settings.margins,
    measurementRef,
  })

  // Calculate auto-zoom to fit container width
  const calculateAutoZoom = useCallback(() => {
    if (!containerRef.current || !autoZoom) return

    const containerWidth = containerRef.current.clientWidth - 48 // Padding
    const pageWidthPx = mmToPx(PAGE_DIMENSIONS[settings.pageSize].width)
    const optimalZoom = Math.min(containerWidth / pageWidthPx, MAX_ZOOM)
    setZoom(Math.max(MIN_ZOOM, Math.min(optimalZoom, MAX_ZOOM)))
  }, [settings.pageSize, autoZoom])

  // Auto-zoom on mount, container resize, and when page size changes
  useEffect(() => {
    calculateAutoZoom()
    const handleResize = () => calculateAutoZoom()
    window.addEventListener('resize', handleResize)
    const target = containerRef.current
    const observer =
      target && typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => calculateAutoZoom())
        : null
    if (target && observer) {
      observer.observe(target)
    }
    return () => {
      window.removeEventListener('resize', handleResize)
      observer?.disconnect()
    }
  }, [calculateAutoZoom])

  const handleZoomIn = () => {
    setAutoZoom(false)
    setZoom((z) => Math.min(z + ZOOM_STEP, MAX_ZOOM))
  }

  const handleZoomOut = () => {
    setAutoZoom(false)
    setZoom((z) => Math.max(z - ZOOM_STEP, MIN_ZOOM))
  }

  const toggleMargins = () => setShowMargins((s) => !s)

  // Get content area dimensions for the hidden measurement container
  const contentArea = getContentAreaPx(settings.pageSize, settings.margins)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Scrollable preview area */}
      <div ref={containerRef} className="flex-1 overflow-auto bg-[#F6F3EC] p-6">
        {/* Hidden measurement container - renders content at actual size */}
        <div
          ref={measurementRef}
          className="absolute opacity-0 pointer-events-none"
          style={{
            width: contentArea.width,
            left: -9999,
            top: 0,
          }}
          aria-hidden="true"
        >
          <ResumeRenderer resumeData={resumeData} settings={resumeSettings} />
        </div>

        {/* Visible pages */}
        <div className="flex flex-col items-center gap-4">
          {pages.map((page, index) => (
            <React.Fragment key={page.pageNumber}>
              {index > 0 && (
                <div className="flex items-center gap-2 py-2">
                  <div className="h-px w-8 bg-[#878E99]" />
                  <span className="font-mono text-[10px] text-[#878E99] uppercase tracking-wider">
                    分页
                  </span>
                  <div className="h-px w-8 bg-[#878E99]" />
                </div>
              )}
              <PageContainer
                pageSize={settings.pageSize}
                margins={settings.margins}
                pageNumber={page.pageNumber}
                totalPages={pages.length}
                scale={zoom}
                showMarginGuides={showMargins}
                contentOffset={page.contentOffset}
                contentEnd={page.contentEnd}
              >
                <ResumeRenderer resumeData={resumeData} settings={resumeSettings} themeAware />
              </PageContainer>
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Controls bar：从预览区顶部挪到渲染区下方（第三列底部） */}
      <div className="flex items-center px-4 py-2 border-t border-[#878E99] bg-[#E5E5E0] shrink-0">
        <div className="flex items-center gap-2">
          {/* Zoom controls */}
          <SwissButton
            variant="ghost"
            size="icon"
            onClick={handleZoomOut}
            disabled={zoom <= MIN_ZOOM}
            title="缩小"
          >
            <ZoomOut className="w-4 h-4" />
          </SwissButton>
          <span className="font-mono text-xs w-12 text-center text-[#444850]">
            {Math.round(zoom * 100)}%
          </span>
          <SwissButton
            variant="ghost"
            size="icon"
            onClick={handleZoomIn}
            disabled={zoom >= MAX_ZOOM}
            title="放大"
          >
            <ZoomIn className="w-4 h-4" />
          </SwissButton>

          <div className="w-px h-5 bg-[#878E99] mx-2" />

          {/* Margin toggle */}
          <SwissButton
            variant={showMargins ? 'secondary' : 'ghost'}
            size="sm"
            onClick={toggleMargins}
            className="h-8 gap-1.5"
          >
            <Eye className={showMargins ? 'w-4 h-4 text-[#444850]' : 'w-4 h-4 text-[#878E99]'} />
            <span className="font-mono text-xs uppercase">边距</span>
          </SwissButton>

          <div className="w-px h-5 bg-[#878E99] mx-2" />

          {/* Page count：放到「边距」右边，不再推到最右 */}
          <div className="flex items-center gap-2 text-[#444850]">
            <FileText className="w-4 h-4" />
            <span className="font-mono text-xs uppercase">
              {isCalculating
                ? '计算中…'
                : pages.length === 1
                  ? '1 页'
                  : `${pages.length} 页`}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
