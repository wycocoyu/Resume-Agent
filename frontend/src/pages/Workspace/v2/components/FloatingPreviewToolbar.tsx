import React from 'react'
import { Minus, Plus, Eye, Download, FileText, Sparkles, Maximize2 } from 'lucide-react'
import { cn } from '../../../../lib/utils'

export interface FloatingPreviewToolbarProps {
  engine?: 'latex' | 'html'
  onEngineChange?: (engine: 'latex' | 'html') => void
  scale: number
  onZoomIn: () => void
  onZoomOut: () => void
  onFitWidth?: () => void
  isUserScale?: boolean
  showMargin?: boolean
  onToggleMargin?: () => void
  onDownload?: () => void
  onAutoFit?: () => void
  className?: string
}

export const FloatingPreviewToolbar: React.FC<FloatingPreviewToolbarProps> = ({
  engine = 'latex',
  onEngineChange,
  scale,
  onZoomIn,
  onZoomOut,
  onFitWidth,
  isUserScale = false,
  showMargin = false,
  onToggleMargin,
  onDownload,
  onAutoFit,
  className,
}) => {
  const percent = Math.round(scale * 100)

  return (
    <div
      className={cn(
        'absolute bottom-6 left-1/2 -translate-x-1/2 z-30',
        'flex items-center gap-2 px-3 py-1.5 rounded-full',
        'backdrop-blur-md bg-white/85 dark:bg-zinc-900/85',
        'border border-white/40 dark:border-zinc-700/40 shadow-floating text-xs',
        'text-slate-700 dark:text-slate-200 transition-all duration-200 select-none',
        className
      )}
    >
      {/* 引擎切换器 */}
      {onEngineChange && (
        <div className="flex items-center bg-slate-100/80 dark:bg-zinc-800/80 rounded-full p-0.5 border border-slate-200/50 dark:border-zinc-700/50">
          <button
            type="button"
            onClick={() => onEngineChange('latex')}
            className={cn(
              'px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all',
              engine === 'latex'
                ? 'bg-white dark:bg-zinc-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            )}
            title="切换到 LaTeX 编译引擎"
          >
            LaTeX
          </button>
          <button
            type="button"
            onClick={() => onEngineChange('html')}
            className={cn(
              'px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all',
              engine === 'html'
                ? 'bg-white dark:bg-zinc-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            )}
            title="切换到 HTML 模板实时引擎"
          >
            HTML
          </button>
        </div>
      )}

      {onEngineChange && <div className="w-px h-4 bg-slate-200 dark:bg-zinc-700" />}

      {/* 缩放控制组 */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onZoomOut}
          disabled={scale <= 0.5}
          className="p-1 rounded-full hover:bg-slate-100 dark:hover:bg-zinc-800 disabled:opacity-40 transition-colors"
          title="缩小"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <span className="font-mono text-[11px] font-semibold min-w-[36px] text-center">
          {percent}%
        </span>
        <button
          type="button"
          onClick={onZoomIn}
          disabled={scale >= 2.5}
          className="p-1 rounded-full hover:bg-slate-100 dark:hover:bg-zinc-800 disabled:opacity-40 transition-colors"
          title="放大"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        {isUserScale && onFitWidth && (
          <button
            type="button"
            onClick={onFitWidth}
            className="p-1 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 rounded-full transition-colors"
            title="适应宽度"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* 边距参考线切换 */}
      {onToggleMargin && (
        <>
          <div className="w-px h-4 bg-slate-200 dark:bg-zinc-700" />
          <button
            type="button"
            onClick={onToggleMargin}
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium transition-colors',
              showMargin
                ? 'bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400 font-semibold'
                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-zinc-800'
            )}
            title="显示或隐藏页面排版边距辅助线"
          >
            <Eye className="w-3.5 h-3.5" />
            <span>边距</span>
          </button>
        </>
      )}

      {/* 自动一页自适应 */}
      {onAutoFit && (
        <>
          <div className="w-px h-4 bg-slate-200 dark:bg-zinc-700" />
          <button
            type="button"
            onClick={onAutoFit}
            className="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40 transition-colors"
            title="触发自动一页高度自适应优化"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>自动一页</span>
          </button>
        </>
      )}

      {/* 快速导出 */}
      {onDownload && (
        <>
          <div className="w-px h-4 bg-slate-200 dark:bg-zinc-700" />
          <button
            type="button"
            onClick={onDownload}
            className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm transition-colors"
            title="导出当前简历 PDF"
          >
            <Download className="w-3.5 h-3.5" />
            <span>导出</span>
          </button>
        </>
      )}
    </div>
  )
}
