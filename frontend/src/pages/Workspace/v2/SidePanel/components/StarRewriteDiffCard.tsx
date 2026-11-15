/**
 * STAR Rewrite Diff Card with Keyword & Metric Highlighting.
 *
 * Feature 18 / Issue #54.
 */
import React, { useState } from 'react'
import { Check, Edit3, ArrowRight, Sparkles, CheckCheck } from 'lucide-react'

export interface StarComponent {
  situation?: string
  task?: string
  action?: string
  result?: string
}

export interface StarSuggestionItem {
  id: string
  key: string
  label?: string
  original: string
  suggested: string
  reason?: string
  star_breakdown?: StarComponent
  aligned_keywords?: string[]
  quantifiable_metrics?: string[]
}

export interface StarRewriteDiffCardProps {
  suggestion: StarSuggestionItem
  isApplied: boolean
  targetKeywords?: string[]
  onApply: (key: string, original: string, suggested: string) => void
  onEditApply?: (key: string, original: string, editedSuggested: string) => void
}

/**
 * Deterministically highlights quantifiable metrics in blue and JD keywords in emerald.
 */
export function highlightKeywordsAndMetrics(text: string, keywords: string[] = []): string {
  if (!text) return ''

  // Escape HTML entities first to prevent XSS
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 1. Highlight numbers & metrics (e.g. 35%, 10万, 5000+, 35ms)
  html = html.replace(
    /(\d+(?:\.\d+)?(?:%|‰|倍|万|k|K|M|ms|s|秒|次\/秒|QPS|TPS|GB|TB|人|个|套)?\+?)/g,
    '<mark class="bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 font-semibold px-1 py-0.5 rounded text-[11px]">$1</mark>'
  )

  // 2. Highlight JD keywords
  keywords.forEach((kw) => {
    if (!kw || kw.length < 2) return
    const esc = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const reg = new RegExp(`(?<![a-zA-Z0-9_\u4e00-\u9fa5])(${esc})(?![a-zA-Z0-9_\u4e00-\u9fa5])`, 'gi')
    html = html.replace(
      reg,
      '<mark class="bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 font-bold px-1 py-0.5 rounded text-[11px]">$1</mark>'
    )
  })

  return html
}

export const StarRewriteDiffCard: React.FC<StarRewriteDiffCardProps> = ({
  suggestion,
  isApplied,
  targetKeywords = [],
  onApply,
  onEditApply,
}) => {
  const [isEditing, setIsEditing] = useState(false)
  const [editedText, setEditedText] = useState(suggestion.suggested)

  const combinedKeywords = Array.from(
    new Set([...(suggestion.aligned_keywords || []), ...targetKeywords])
  )

  const handleApplyClick = () => {
    if (isEditing) {
      if (onEditApply) {
        onEditApply(suggestion.key, suggestion.original, editedText)
      } else {
        onApply(suggestion.key, suggestion.original, editedText)
      }
      setIsEditing(false)
    } else {
      onApply(suggestion.key, suggestion.original, suggestion.suggested)
    }
  }

  return (
    <div className="p-3 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-2.5 transition-all">
      {/* Header bar: target label + status badge */}
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-amber-500" />
          {suggestion.label || '经历条目 STAR 改写'}
        </span>
        {isApplied ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
            <CheckCheck className="w-3 h-3" />
            已采纳到简历
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">待优化</span>
        )}
      </div>

      {/* STAR breakdown pills if available */}
      {suggestion.star_breakdown && (
        <div className="flex flex-wrap gap-1 text-[10px]">
          <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
            [S] 场景挑战
          </span>
          <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
            [T] 架构目标
          </span>
          <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800">
            [A] 技术行动
          </span>
          <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
            [R] 量化成果
          </span>
        </div>
      )}

      {/* Diff comparison box */}
      <div className="space-y-2 text-xs">
        {/* Original (struck through or faded) */}
        <div className="p-2 rounded bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 text-slate-500 dark:text-slate-400 line-through leading-relaxed">
          {suggestion.original}
        </div>

        {/* Arrow divider */}
        <div className="flex items-center justify-center text-slate-300 dark:text-slate-600">
          <ArrowRight className="w-4 h-4 rotate-90" />
        </div>

        {/* Suggested with highlight */}
        {isEditing ? (
          <textarea
            rows={3}
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            className="w-full p-2 rounded border border-blue-400 dark:border-blue-600 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs font-mono focus:outline-none ring-1 ring-blue-500 leading-relaxed"
          />
        ) : (
          <div
            className="p-2.5 rounded bg-emerald-50/40 dark:bg-emerald-950/10 border border-emerald-200/60 dark:border-emerald-800/40 text-slate-800 dark:text-slate-200 leading-relaxed"
            dangerouslySetInnerHTML={{
              __html: highlightKeywordsAndMetrics(suggestion.suggested, combinedKeywords),
            }}
          />
        )}
      </div>

      {/* Rationale and Keywords info */}
      {suggestion.reason && (
        <div className="text-[11px] text-slate-500 dark:text-slate-400 italic">
          💡 {suggestion.reason}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center justify-end gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
        <button
          type="button"
          onClick={() => setIsEditing(!isEditing)}
          className="px-2.5 py-1 text-xs rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 flex items-center gap-1 transition-colors"
        >
          <Edit3 className="w-3 h-3" />
          {isEditing ? '取消编辑' : '微调'}
        </button>
        <button
          type="button"
          onClick={handleApplyClick}
          disabled={isApplied && !isEditing}
          className={`px-3 py-1 text-xs font-bold rounded flex items-center gap-1 transition-all ${
            isApplied && !isEditing
              ? 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500 cursor-default'
              : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm active:scale-95'
          }`}
        >
          <Check className="w-3.5 h-3.5" />
          {isEditing ? '确认采纳微调' : isApplied ? '已采纳' : '一键采纳改写'}
        </button>
      </div>
    </div>
  )
}
