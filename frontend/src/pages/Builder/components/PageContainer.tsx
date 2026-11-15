/**
 * 单页容器 —— 移植自 Resume-Matcher components/preview/page-container.tsx。
 * 按真实 mm 尺寸渲染一页,内容按 contentOffset/contentEnd 裁切,支持边距虚线可视化。
 */
import React from 'react'
import type { PageSize, MarginSettings } from '../settings'
import { PAGE_DIMENSIONS, mmToPx } from '../pageDimensions'

interface PageContainerProps {
  pageSize: PageSize
  margins: MarginSettings
  pageNumber: number
  totalPages: number
  scale: number
  showMarginGuides: boolean
  children: React.ReactNode
  contentOffset?: number
  contentEnd?: number
}

export function PageContainer({
  pageSize,
  margins,
  pageNumber,
  totalPages,
  scale,
  showMarginGuides,
  children,
  contentOffset = 0,
  contentEnd,
}: PageContainerProps) {
  const pageDims = PAGE_DIMENSIONS[pageSize]
  const pageWidthPx = mmToPx(pageDims.width)
  const pageHeightPx = mmToPx(pageDims.height)

  const marginTopPx = mmToPx(margins.top)
  const marginBottomPx = mmToPx(margins.bottom)
  const marginLeftPx = mmToPx(margins.left)
  const marginRightPx = mmToPx(margins.right)

  const contentWidth = pageWidthPx - marginLeftPx - marginRightPx
  const maxContentHeight = pageHeightPx - marginTopPx - marginBottomPx

  // Limit visible height so content that belongs to the next page never shows here
  const actualContentHeight = contentEnd
    ? Math.min(maxContentHeight, contentEnd - contentOffset)
    : maxContentHeight

  return (
    <div className="relative flex flex-col items-center">
      {/* Page wrapper with scale transform。
          深色模式（仅管理员可见）下纸张整体反色为黑底浅字：只覆盖屏幕预览这一份
          CSS 变量，不影响 PreviewPanel 里离屏渲染给 html2pdf 导出用的容器，
          导出结果始终是印刷标准的白底黑字。 */}
      <div
        className="relative bg-white dark:bg-black border border-slate-200/80 dark:border-zinc-800 shadow-[0_4px_24px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5)] origin-top
          dark:[--resume-text-primary:#f5f5f5] dark:[--resume-text-secondary:#d1d5db]
          dark:[--resume-text-tertiary:#9ca3af] dark:[--resume-text-body:#e5e7eb]
          dark:[--resume-border-primary:#6b7280] dark:[--resume-border-secondary:#4b5563]
          dark:[--resume-border-tertiary:#374151] dark:[--resume-accent-bg:#1f2937]"
        style={{
          width: pageWidthPx,
          height: pageHeightPx,
          transform: `scale(${scale})`,
          marginBottom: `${pageHeightPx * scale - pageHeightPx + 16}px`,
        }}
      >
        {/* Margin guides overlay */}
        {showMarginGuides && (
          <div
            className="absolute pointer-events-none z-10"
            style={{
              top: marginTopPx,
              left: marginLeftPx,
              width: contentWidth,
              height: maxContentHeight,
              border: '1px dashed rgba(29, 78, 216, 0.5)',
            }}
          >
            {/* Corner markers */}
            <div className="absolute -top-1 -left-1 w-2 h-2 border-t border-l border-blue-500" />
            <div className="absolute -top-1 -right-1 w-2 h-2 border-t border-r border-blue-500" />
            <div className="absolute -bottom-1 -left-1 w-2 h-2 border-b border-l border-blue-500" />
            <div className="absolute -bottom-1 -right-1 w-2 h-2 border-b border-r border-blue-500" />
          </div>
        )}

        {/* Content area with clipping - uses actualContentHeight to prevent content overlap */}
        <div
          className="absolute overflow-hidden"
          style={{
            top: marginTopPx,
            left: marginLeftPx,
            width: contentWidth,
            height: actualContentHeight,
          }}
        >
          {/* Content positioned based on page offset */}
          <div
            className="absolute left-0 right-0"
            style={{
              top: -contentOffset,
              width: contentWidth,
            }}
          >
            {children}
          </div>
        </div>

        {/* Page number indicator */}
        <div
          className="absolute bottom-2 right-3 font-mono text-[10px] text-[#878E99] uppercase tracking-wider"
          style={{ transform: `scale(${1 / scale})`, transformOrigin: 'bottom right' }}
        >
          第 {pageNumber} 页 · 共 {totalPages} 页
        </div>
      </div>
    </div>
  )
}
