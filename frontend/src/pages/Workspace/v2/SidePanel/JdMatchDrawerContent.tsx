/**
 * Main Content Component for SettingsDrawer 'jd' Tab.
 *
 * Feature 18 / Issue #54: Job JD Targeted Matching & 3D Radar Analysis.
 */
import React, { useState } from 'react'
import {
  Sparkles,
  CheckCheck,
  GitFork,
  CheckCircle2,
  AlertCircle,
  Plus,
} from 'lucide-react'
import { JdRadarChart, type RadarDimension } from './components/JdRadarChart'
import { JdStructuredInput, type JdParsedData } from './components/JdStructuredInput'
import { StarRewriteDiffCard, type StarSuggestionItem } from './components/StarRewriteDiffCard'
import { DerivativeResumeModal } from './components/DerivativeResumeModal'

export interface JdMatchDrawerContentProps {
  resumeData: any
  currentResumeId?: string | null
  jdFields?: { key: string; label: string; content: string }[]
  onApplyTextReplacement: (key: string, original: string, suggested: string) => void
  onApplyTextReplacements?: (items: { key: string; original: string; suggested: string }[]) => void
  onClose?: () => void
}

export const JdMatchDrawerContent: React.FC<JdMatchDrawerContentProps> = ({
  resumeData,
  currentResumeId,
  jdFields = [],
  onApplyTextReplacement,
  onApplyTextReplacements,
}) => {
  const [jdInput, setJdInput] = useState<JdParsedData>({
    jobTitle: '',
    targetCompany: '',
    jdText: '',
    hardSkills: [],
    domainSkills: [],
  })

  const [loading, setLoading] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<any>(null)
  const [suggestions, setSuggestions] = useState<StarSuggestionItem[]>([])
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set())
  const [forkModalOpen, setForkModalOpen] = useState(false)

  const hasResumeContent = Boolean(
    resumeData?.basic?.name ||
    resumeData?.experience?.length ||
    resumeData?.skills?.length ||
    jdFields.length > 0
  )

  const handleAnalyze = async () => {
    if (!jdInput.jdText.trim() || !hasResumeContent) return

    setLoading(true)
    try {
      // 1. Run 3D Radar Matching
      const matchRes = await fetch('/api/jd/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resume_data: resumeData,
          jd_text: jdInput.jdText,
        }),
      })

      if (matchRes.ok) {
        const matchData = await matchRes.json()
        setAnalysisResult(matchData)
        if (matchData.parsed_jd) {
          setJdInput((prev) => ({
            ...prev,
            jobTitle: prev.jobTitle || matchData.parsed_jd.title,
            hardSkills: matchData.parsed_jd.required_skills,
            domainSkills: matchData.parsed_jd.domain_keywords,
          }))
        }
      }

      // 2. Run STAR Rewrite Generation
      const starRes = await fetch('/api/jd/star-rewrite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jd_text: jdInput.jdText,
          fields: jdFields,
          resume_data: resumeData,
        }),
      })

      if (starRes.ok) {
        const starData = await starRes.json()
        setSuggestions(starData.suggestions || [])
      }
    } catch (err) {
      console.error('JD analysis error:', err)
    } finally {
      setLoading(false)
    }
  }

  // Handle single apply
  const handleApplySingle = (key: string, original: string, suggested: string) => {
    onApplyTextReplacement(key, original, suggested)
    const match = suggestions.find((s) => s.key === key && s.original === original)
    if (match) {
      setAppliedIds((prev) => new Set(prev).add(match.id))
    }
  }

  // Handle batch apply all
  const handleBatchApply = () => {
    const unapplied = suggestions.filter((s) => !appliedIds.has(s.id))
    if (!unapplied.length) return

    if (onApplyTextReplacements) {
      onApplyTextReplacements(
        unapplied.map((s) => ({
          key: s.key,
          original: s.original,
          suggested: s.suggested,
        }))
      )
    } else {
      unapplied.forEach((s) => {
        onApplyTextReplacement(s.key, s.original, s.suggested)
      })
    }

    setAppliedIds(new Set(suggestions.map((s) => s.id)))
  }

  // Add missing keyword to skill content
  const handleAddKeywordToSkills = (keyword: string) => {
    const current = resumeData?.skillContent || ''
    const updated = current.trim()
      ? `${current.trim()}、熟练掌握 ${keyword}`
      : `熟练掌握 ${keyword}`
    onApplyTextReplacement('skillContent', current, updated)
  }

  // Format Radar Dimensions
  const radarDimensions: RadarDimension[] = analysisResult
    ? [
        {
          key: 'technical',
          name: '技术匹配度',
          score: analysisResult.radar.technical_score,
        },
        {
          key: 'project',
          name: '项目契合度',
          score: analysisResult.radar.project_score,
        },
        {
          key: 'experience',
          name: '资历契合度',
          score: analysisResult.radar.experience_score,
        },
      ]
    : [
        { key: 'technical', name: '技术匹配度', score: 60 },
        { key: 'project', name: '项目契合度', score: 50 },
        { key: 'experience', name: '资历契合度', score: 70 },
      ]

  return (
    <div className="space-y-4 pb-8">
      {/* 1. Structured JD Input */}
      <JdStructuredInput
        data={jdInput}
        onChange={setJdInput}
        onAnalyze={handleAnalyze}
        loading={loading}
        hasResumeContent={hasResumeContent}
      />

      {/* 2. 3D Radar Analysis Section */}
      {analysisResult && (
        <div className="p-3 bg-white dark:bg-slate-900 rounded border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-2">
            <span className="font-bold text-xs text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-blue-500" />
              3D 靶向匹配雷达诊断
            </span>
            <div className="flex items-center gap-1 text-[11px] font-mono font-bold text-blue-600 dark:text-blue-400">
              综合评分：{Math.round(analysisResult.overall_score)} 分
            </div>
          </div>

          {/* Pure SVG 3D Radar */}
          <JdRadarChart
            dimensions={radarDimensions}
            overallScore={analysisResult.overall_score}
            size={280}
          />

          {/* Skills Breakdown Tags */}
          <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800 text-xs">
            {/* Matched skills */}
            {analysisResult.technical_match?.matched_skills?.length > 0 && (
              <div>
                <span className="text-[11px] text-emerald-700 dark:text-emerald-400 font-semibold flex items-center gap-1 mb-1">
                  <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                  已命中关键技术栈 ({analysisResult.technical_match.matched_skills.length})
                </span>
                <div className="flex flex-wrap gap-1">
                  {analysisResult.technical_match.matched_skills.map((sk: string) => (
                    <span
                      key={sk}
                      className="px-1.5 py-0.5 rounded text-[11px] bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 font-medium"
                    >
                      ✓ {sk}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Missing skills with one-click integration */}
            {analysisResult.technical_match?.missing_skills?.length > 0 && (
              <div>
                <span className="text-[11px] text-rose-700 dark:text-rose-400 font-semibold flex items-center gap-1 mb-1">
                  <AlertCircle className="w-3 h-3 text-rose-500" />
                  待补充技术点 ({analysisResult.technical_match.missing_skills.length})
                </span>
                <div className="flex flex-wrap gap-1">
                  {analysisResult.technical_match.missing_skills.map((sk: string) => (
                    <button
                      key={sk}
                      type="button"
                      onClick={() => handleAddKeywordToSkills(sk)}
                      title={`点击一键补充「${sk}」到专业技能`}
                      className="group px-1.5 py-0.5 rounded text-[11px] bg-rose-50 hover:bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:hover:bg-rose-900/60 dark:text-rose-300 border border-rose-200 dark:border-rose-800 font-medium flex items-center gap-0.5 transition-colors"
                    >
                      <Plus className="w-3 h-3 text-rose-500 group-hover:scale-125 transition-transform" />
                      {sk}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 3. Action Toolbar: Batch Apply & Derivative Resume Fork */}
      {analysisResult && (
        <div className="flex items-center justify-between gap-2 p-2.5 rounded bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-900">
          <button
            type="button"
            onClick={() => setForkModalOpen(true)}
            className="px-3 py-1.5 text-xs font-bold rounded bg-white dark:bg-slate-800 border border-blue-500 text-blue-600 dark:text-blue-400 hover:bg-blue-50 flex items-center gap-1.5 transition-all shadow-sm active:scale-95"
          >
            <GitFork className="w-3.5 h-3.5" />
            另存为岗位专属版本
          </button>

          {suggestions.length > 0 && (
            <button
              type="button"
              disabled={appliedIds.size >= suggestions.length}
              onClick={handleBatchApply}
              className="px-3 py-1.5 text-xs font-bold rounded bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white flex items-center gap-1.5 transition-all shadow-sm active:scale-95"
            >
              <CheckCheck className="w-3.5 h-3.5" />
              {appliedIds.size >= suggestions.length
                ? '已全部采纳'
                : `一键采纳全部 (${suggestions.length - appliedIds.size})`}
            </button>
          )}
        </div>
      )}

      {/* 4. STAR Rewrite Diff List */}
      {suggestions.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs px-1">
            <span className="font-bold text-slate-800 dark:text-slate-200">
              🎯 目标岗位针对性改写建议 ({suggestions.length})
            </span>
            <span className="text-[11px] text-slate-500">
              已采纳 {appliedIds.size} / {suggestions.length}
            </span>
          </div>

          <div className="space-y-2.5">
            {suggestions.map((suggestion) => (
              <StarRewriteDiffCard
                key={suggestion.id}
                suggestion={suggestion}
                isApplied={appliedIds.has(suggestion.id)}
                targetKeywords={jdInput.hardSkills}
                onApply={handleApplySingle}
              />
            ))}
          </div>
        </div>
      )}

      {/* 5. Derivative Resume Fork Modal */}
      <DerivativeResumeModal
        open={forkModalOpen}
        onClose={() => setForkModalOpen(false)}
        currentResumeData={resumeData}
        currentResumeId={currentResumeId}
        targetCompany={jdInput.targetCompany}
        jobTitle={jdInput.jobTitle}
        matchScore={analysisResult?.overall_score || 80}
        onSuccess={(newId, shouldNavigate) => {
          if (shouldNavigate) {
            window.location.href = `/workspace/${newId}`
          } else {
            alert('已成功派生目标岗位专属版本！您可随时在仪表盘查看。')
          }
        }}
      />
    </div>
  )
}
