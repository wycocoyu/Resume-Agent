/**
 * 自动保存常驻状态指示器（保存中… / 已保存 / 保存失败）
 */
import { Check, CloudOff, Loader2 } from 'lucide-react'
import type { AutoSaveStatus } from '../hooks/useAutoSaveResume'

interface SaveStatusIndicatorProps {
  status: AutoSaveStatus
  error?: string | null
}

export function SaveStatusIndicator({ status, error }: SaveStatusIndicatorProps) {
  if (status === 'idle') return null

  if (status === 'pending' || status === 'saving') {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-slate-400 dark:text-slate-500 select-none">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        保存中…
      </span>
    )
  }

  if (status === 'error') {
    return (
      <span
        className="flex items-center gap-1.5 whitespace-nowrap text-xs text-red-500 select-none"
        title={error || '自动保存失败'}
      >
        <CloudOff className="w-3.5 h-3.5" />
        保存失败
      </span>
    )
  }

  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-emerald-500 select-none">
      <Check className="w-3.5 h-3.5" />
      已保存
    </span>
  )
}
