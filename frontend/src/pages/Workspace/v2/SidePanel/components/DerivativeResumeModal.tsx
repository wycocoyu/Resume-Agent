/**
 * Derivative Resume Modal (Fork / Branch Resume for Target JD).
 *
 * Feature 18 / Issue #54.
 */
import React, { useState } from 'react'
import { GitFork, X, Check, ArrowRight } from 'lucide-react'
import { saveResume, updateResumeAlias } from '../../../../../services/resumeStorage'

export interface DerivativeResumeModalProps {
  open: boolean
  onClose: () => void
  currentResumeData: any
  currentResumeId?: string | null
  targetCompany: string
  jobTitle: string
  matchScore: number
  onSuccess: (newResumeId: string, shouldNavigate: boolean) => void
}

export const DerivativeResumeModal: React.FC<DerivativeResumeModalProps> = ({
  open,
  onClose,
  currentResumeData,
  currentResumeId,
  targetCompany,
  jobTitle,
  matchScore,
  onSuccess,
}) => {
  const defaultTitle = jobTitle ? `${targetCompany || ''} ${jobTitle} 定制版`.trim() : '岗位定向定制版'
  const candidateName = currentResumeData?.basic?.name || '简历'

  const [customName, setCustomName] = useState(`${candidateName} - ${defaultTitle}`)
  const [alias, setAlias] = useState(`针对「${jobTitle || '目标岗位'}」定向优化版`)
  const [loading, setLoading] = useState(false)

  if (!open) return null

  const handleFork = async (shouldNavigate: boolean) => {
    try {
      setLoading(true)

      // 1. Deep clone current resume data
      const forkedData = JSON.parse(JSON.stringify(currentResumeData || {}))
      if (!forkedData._meta) forkedData._meta = {}
      forkedData._meta.forkedFrom = currentResumeId || 'local_master'
      forkedData._meta.forkedAt = new Date().toISOString()
      forkedData._meta.targetJd = {
        company: targetCompany,
        title: jobTitle,
        score: matchScore,
      }

      // 2. If backend API is available and currentResumeId is a DB ID, try API fork first
      let createdId: string | null = null
      if (currentResumeId && !currentResumeId.startsWith('resume_temp_')) {
        try {
          const resp = await fetch(`/api/resumes/${currentResumeId}/fork`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_jd_title: jobTitle,
              target_company: targetCompany,
              custom_name: customName,
            }),
          })
          if (resp.ok) {
            const result = await resp.json()
            createdId = result.id
          }
        } catch {
          // Fall back to local storage fork
        }
      }

      // 3. Fallback or local save
      if (!createdId) {
        // Save without ID to force new UUID creation
        const saved = await saveResume(forkedData)
        createdId = saved.id
        await updateResumeAlias(createdId, alias)
      }

      onSuccess(createdId, shouldNavigate)
      onClose()
    } catch (err) {
      console.error('Failed to fork derivative resume:', err)
      alert('派生版本失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white dark:bg-slate-900 rounded-lg max-w-md w-full border border-slate-200 dark:border-slate-800 shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400">
              <GitFork className="w-4 h-4" />
            </div>
            <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">另存为岗位专属版本 (Fork)</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3.5 text-xs">
          <p className="text-slate-600 dark:text-slate-400 leading-relaxed">
            将当前已采纳 STAR 改写的简历保存为一个全新的衍生版本，不会覆盖您的通用主简历，方便您针对不同岗位定向投递。
          </p>

          <div>
            <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">
              新版本简历名称
            </label>
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              className="w-full px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium"
            />
          </div>

          <div>
            <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">
              版本备注 / 投递标签
            </label>
            <input
              type="text"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              className="w-full px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="p-2.5 rounded bg-blue-50/60 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300 text-[11px] space-y-1">
            <div className="font-semibold">版本关联档案</div>
            <div>• 目标公司：{targetCompany || '未指定'}</div>
            <div>• 目标岗位：{jobTitle || '通用定制'}</div>
            <div>• 3D 匹配得分：{Math.round(matchScore)} 分</div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 bg-slate-50 dark:bg-slate-800/40 border-t border-slate-200 dark:border-slate-800 text-xs">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            取消
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => handleFork(false)}
            className="px-3 py-1.5 rounded border border-blue-600 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40 font-bold"
          >
            保存并留在此处
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => handleFork(true)}
            className="px-3.5 py-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-1 shadow-sm"
          >
            <Check className="w-3.5 h-3.5" />
            保存并立即前往
            <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  )
}
