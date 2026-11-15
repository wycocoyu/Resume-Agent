/**
 * Structured Job Description (JD) Input Component.
 *
 * Feature 18 / Issue #54.
 */
import React from 'react'
import { Sparkles, Trash2, FileText, Building2, Briefcase } from 'lucide-react'

export interface JdParsedData {
  jobTitle: string
  targetCompany: string
  jdText: string
  hardSkills?: string[]
  domainSkills?: string[]
}

export interface JdStructuredInputProps {
  data: JdParsedData
  onChange: (data: JdParsedData) => void
  onAnalyze: () => void
  loading: boolean
  hasResumeContent: boolean
}

const SAMPLE_JD = `职位名称：资深全栈 / 后端架构师
目标公司：字节跳动
工作职责：
1. 负责高并发核心业务中台与微服务架构治理，支撑千万级 DAU。
2. 主导全栈应用及前端微前端体系建设，保障系统 99.99% 高可用。
3. 推动 AI 与 RAG 智能应用在业务场景的落地探索。

任职要求：
1. 本科及以上学历，计算机相关专业，至少 5 年以上研发经验。
2. 熟练掌握 Go / Python / TypeScript / React / Node.js 等核心栈。
3. 深入掌握 MySQL、Redis、Kafka、Docker、Kubernetes 核心原理与性能调优。
4. 具备大规模分布式高并发架构与全链路性能优化经验。`

export const JdStructuredInput: React.FC<JdStructuredInputProps> = ({
  data,
  onChange,
  onAnalyze,
  loading,
  hasResumeContent,
}) => {
  const handleLoadSample = () => {
    onChange({
      jobTitle: '资深全栈/后端架构师',
      targetCompany: '字节跳动',
      jdText: SAMPLE_JD,
      hardSkills: ['Go', 'Python', 'TypeScript', 'React', 'Docker', 'Kubernetes', 'Redis', 'MySQL'],
      domainSkills: ['微服务', '高并发', 'RAG'],
    })
  }

  const handleClear = () => {
    onChange({
      jobTitle: '',
      targetCompany: '',
      jdText: '',
      hardSkills: [],
      domainSkills: [],
    })
  }

  return (
    <div className="space-y-3 p-3 bg-slate-50 dark:bg-slate-800/40 rounded border border-slate-200 dark:border-slate-800 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5 text-xs">
          <Briefcase className="w-3.5 h-3.5 text-blue-500" />
          目标岗位设定
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleLoadSample}
            className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
          >
            <Sparkles className="w-3 h-3" />
            填入示例 JD
          </button>
          {data.jdText && (
            <button
              type="button"
              onClick={handleClear}
              className="text-[11px] text-slate-400 hover:text-red-500 flex items-center gap-0.5"
              title="清空内容"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[11px] font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
            <Building2 className="w-3 h-3 text-slate-400" />
            目标公司
          </label>
          <input
            type="text"
            placeholder="例如：字节跳动、腾讯、Google"
            value={data.targetCompany}
            onChange={(e) => onChange({ ...data, targetCompany: e.target.value })}
            className="w-full px-2.5 py-1.5 text-xs rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-[11px] font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
            <Briefcase className="w-3 h-3 text-slate-400" />
            岗位名称
          </label>
          <input
            type="text"
            placeholder="例如：资深后端架构师"
            value={data.jobTitle}
            onChange={(e) => onChange({ ...data, jobTitle: e.target.value })}
            className="w-full px-2.5 py-1.5 text-xs rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-[11px] font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
          <FileText className="w-3 h-3 text-slate-400" />
          岗位职责与任职要求 (JD 原文)
        </label>
        <textarea
          rows={5}
          placeholder="粘贴招聘职位描述（包含岗位职责、技能要求、年限与学历要求）..."
          value={data.jdText}
          onChange={(e) => onChange({ ...data, jdText: e.target.value })}
          className="w-full px-2.5 py-1.5 text-xs font-mono rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none leading-relaxed"
        />
      </div>

      <button
        type="button"
        disabled={loading || !data.jdText.trim() || !hasResumeContent}
        onClick={onAnalyze}
        className="w-full py-2 px-3 text-xs font-bold rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white flex items-center justify-center gap-1.5 transition-all shadow-sm active:scale-[0.99]"
      >
        <Sparkles className="w-3.5 h-3.5" />
        {loading ? '正在进行 3D 靶向匹配分析...' : '开始 3D 匹配与深度诊断'}
      </button>
    </div>
  )
}
