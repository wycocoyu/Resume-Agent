import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Check,
  Copy,
  Eye,
  FileJson,
  LayoutGrid,
  Play,
  RotateCcw,
  Search,
  Sparkles,
  Terminal,
  Upload,
  X,
} from 'lucide-react'
import WorkspaceLayout from '@/pages/WorkspaceLayout'
import {
  applyRequestedTemplate,
  parseImportedResumeJson,
  resolveBuilderTemplateType,
  TEMPLATE_METADATA,
  type TemplateMetadata,
} from '@/data/templates'
import { DEFAULT_RESUME_TEMPLATE } from '@/data/defaultTemplate'
import { toBuilderResumeData } from '@/pages/Builder/adapter'
import {
  applyTemplatePreset,
  DEFAULT_TEMPLATE_SETTINGS,
  type TemplateSettings,
} from '@/pages/Builder/settings'
import ResumeRenderer from '@/pages/Builder/templates/ResumeRenderer'
import { fetchLogos, onLogosLoaded } from '@/pages/Workspace/v2/constants/companyLogos'
import { fetchSchoolLogos } from '@/pages/Workspace/v2/constants/schoolLogos'
import { useAuth } from '@/contexts/AuthContext'
import { saveResume, setCurrentResumeId } from '@/services/resumeStorage'
import type { ResumeData } from '@/pages/Workspace/v2/types'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'

const A4_PREVIEW_WIDTH = 794
const A4_PREVIEW_HEIGHT = 1123

type FilterTab = 'all' | 'recommended' | 'LaTeX' | '单栏' | '侧栏' | '双栏' | '双页'

const FILTER_TABS: { id: FilterTab; label: string }[] = [
  { id: 'all', label: '全部模板' },
  { id: 'recommended', label: '推荐默认' },
  { id: 'LaTeX', label: 'LaTeX 精排' },
  { id: '单栏', label: '单栏' },
  { id: '侧栏', label: '侧栏双列' },
  { id: '双栏', label: '双栏' },
  { id: '双页', label: '双页' },
]

function buildSkillPrompt(templateId: string): string {
  return `用 $resume-agent 按模板 ${templateId} 做一份简历`
}

function buildCliCommand(templateId: string): string {
  const engineFlag = templateId === 'default' ? ' --engine latex' : ''
  return `cococv render resume.json --template ${templateId}${engineFlag} -o resume.pdf`
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 退回 textarea 方案，兼容 http 本地预览与无剪贴板权限环境
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    textarea.style.top = '-9999px'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

function matchesFilter(tpl: TemplateMetadata, tab: FilterTab, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (q) {
    const haystack = [tpl.id, tpl.name, tpl.description, tpl.category || '', ...(tpl.tags || [])]
      .join(' ')
      .toLowerCase()
    if (!haystack.includes(q)) return false
  }
  if (tab === 'all') return true
  if (tab === 'recommended') return Boolean(tpl.recommended)
  if (tab === 'LaTeX') return tpl.type === 'latex'
  return tpl.category === tab || (tpl.tags || []).includes(tab)
}

interface ScaledResumePreviewProps {
  builderData: ReturnType<typeof toBuilderResumeData>
  settings: TemplateSettings
  fallbackScale?: number
  aspectClip?: boolean
}

function ScaledResumePreview({
  builderData,
  settings,
  fallbackScale = 0.32,
  aspectClip = true,
}: ScaledResumePreviewProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(fallbackScale)
  const [contentHeight, setContentHeight] = useState(A4_PREVIEW_HEIGHT)

  useEffect(() => {
    const el = boxRef.current
    const inner = contentRef.current
    if (!el) return
    const update = () => {
      if (el.clientWidth > 0) {
        const nextScale = aspectClip
          ? el.clientWidth / A4_PREVIEW_WIDTH
          : Math.min(1, el.clientWidth / A4_PREVIEW_WIDTH)
        setScale(nextScale)
      }
      if (inner && inner.scrollHeight > 0) {
        setContentHeight(inner.scrollHeight)
      }
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    if (inner) ro.observe(inner)
    return () => ro.disconnect()
  }, [aspectClip])

  return (
    <div
      ref={boxRef}
      className={cn(
        'relative w-full bg-white text-left',
        aspectClip
          ? 'aspect-[210/297] overflow-hidden select-none pointer-events-none'
          : 'overflow-hidden mx-auto max-w-[794px]',
      )}
      style={!aspectClip && scale < 1 ? { height: `${Math.ceil(contentHeight * scale)}px` } : undefined}
    >
      <div
        ref={contentRef}
        style={{
          width: `${A4_PREVIEW_WIDTH}px`,
          minHeight: `${A4_PREVIEW_HEIGHT}px`,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }}
      >
        <ResumeRenderer resumeData={builderData} settings={settings} />
      </div>
    </div>
  )
}

export default function TemplatesPage() {
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [activeTab, setActiveTab] = useState<FilterTab>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [importedResume, setImportedResume] = useState<ResumeData | null>(null)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [previewTemplate, setPreviewTemplate] = useState<TemplateMetadata | null>(null)
  const [tryingId, setTryingId] = useState<string | null>(null)
  const [logosVersion, setLogosVersion] = useState(0)

  // 拉取公司与学校 Logo，确保模板广场与工作台预览一致显示品牌图标
  useEffect(() => {
    let alive = true
    const bump = () => {
      if (alive) setLogosVersion((v) => v + 1)
    }
    void fetchLogos().then(bump).catch(() => {})
    void fetchSchoolLogos().then(bump).catch(() => {})
    const off = onLogosLoaded(bump)
    return () => {
      alive = false
      off()
    }
  }, [])

  const previewResume = importedResume || DEFAULT_RESUME_TEMPLATE
  const builderPreviewData = useMemo(() => toBuilderResumeData(previewResume), [previewResume, logosVersion])

  const filteredTemplates = useMemo(
    () => TEMPLATE_METADATA.filter((tpl) => matchesFilter(tpl, activeTab, searchQuery)),
    [activeTab, searchQuery],
  )

  const handleCopy = useCallback(async (key: string, text: string, successMessage: string) => {
    const ok = await copyTextToClipboard(text)
    if (ok) {
      setCopiedKey(key)
      toast.success(successMessage)
      setTimeout(() => {
        setCopiedKey((prev) => (prev === key ? null : prev))
      }, 2000)
    } else {
      toast.error('复制失败，请手动复制文本')
    }
  }, [])

  const handleTryTemplate = useCallback(
    async (templateId: string) => {
      if (tryingId) return
      if (!importedResume) {
        navigate(`/workspace/new?template=${encodeURIComponent(templateId)}`)
        return
      }
      setTryingId(templateId)
      try {
        const prepared = applyRequestedTemplate(importedResume, templateId)
        const saved = await saveResume(prepared)
        setCurrentResumeId(saved.id)
        toast.success(
          isAuthenticated
            ? '已应用模板并保存到云端工作台'
            : '已保存到本机浏览器，正在打开工作台（免登录）',
        )
        navigate(`/workspace/${saved.id}`)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '载入工作台失败，请重试')
      } finally {
        setTryingId(null)
      }
    },
    [importedResume, isAuthenticated, navigate, tryingId],
  )

  const handleFileSelected = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const raw = await file.text()
      const parsed = parseImportedResumeJson(raw)
      setImportedResume(parsed)
      toast.success(`已载入「${parsed.basic.name || '本地简历'}」，下方模板已实时切换为你的内容`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导入 JSON 失败，请确认文件格式')
    }
  }, [])

  const settingsForTemplate = useCallback((templateId: string): TemplateSettings => {
    return applyTemplatePreset(DEFAULT_TEMPLATE_SETTINGS, resolveBuilderTemplateType(templateId))
  }, [])

  const useStaticXeLatexPreview = useCallback(
    (tpl: TemplateMetadata) => Boolean(tpl.type === 'latex' && tpl.thumbnail && !importedResume),
    [importedResume],
  )

  const recommendedInView = useMemo(
    () => filteredTemplates.filter((tpl) => tpl.recommended),
    [filteredTemplates],
  )
  const otherInView = useMemo(
    () => filteredTemplates.filter((tpl) => !tpl.recommended),
    [filteredTemplates],
  )

  const renderTemplateGrid = (items: TemplateMetadata[], sectionTestId?: string) => (
    <div
      data-testid={sectionTestId}
      className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
    >
      {items.map((tpl) => {
        const promptKey = `prompt:${tpl.id}`
        const isCopied = copiedKey === promptKey
        const supportsCli = tpl.supportsCli !== false
        const isXeLatexStatic = useStaticXeLatexPreview(tpl)
        return (
          <article
            key={tpl.id}
            data-testid={`template-card-${tpl.id}`}
            className="group flex flex-col border-2 fresh:border border-black fresh:border-slate-200 bg-white dark:bg-[#1C1C1C] dark:border-white shadow-[4px_4px_0px_0px_#000000] fresh:rounded-xl fresh:shadow-sm dark:shadow-[4px_4px_0px_0px_#ffffff] overflow-hidden transition-transform hover:-translate-y-0.5"
          >
            {/* 顶部标签条（不遮挡简历正文抬头） */}
            <div className="flex items-center justify-between gap-2 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/90 px-3 py-2">
              <span
                className={cn(
                  'border px-2 py-0.5 text-[10px] font-bold fresh:rounded-md',
                  tpl.type === 'latex'
                    ? 'border-amber-700/40 bg-amber-100 text-amber-900'
                    : supportsCli
                      ? 'border-emerald-700/30 bg-emerald-50 text-emerald-800'
                      : 'border-slate-300 bg-white text-slate-700',
                )}
              >
                {tpl.type === 'latex' ? 'XeLaTeX 精排' : supportsCli ? 'HTML · 支持 CLI' : '网页专属 HTML'}
              </span>
              {tpl.recommended && (
                <span className="border border-black fresh:border-blue-600 bg-[#4285F4] px-2 py-0.5 text-[10px] font-bold text-white fresh:rounded-md">
                  推荐
                </span>
              )}
            </div>

            {/* 真实渲染缩略图区 */}
            <div className="relative border-b border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900 p-3">
              <button
                type="button"
                onClick={() => setPreviewTemplate(tpl)}
                className="relative block w-full text-left overflow-hidden border border-slate-300 bg-white shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4]"
                aria-label={`放大预览 ${tpl.name}`}
              >
                {isXeLatexStatic ? (
                  <img
                    src={tpl.thumbnail}
                    alt={`${tpl.name} XeLaTeX 真实渲染预览`}
                    className="w-full aspect-[210/297] object-cover object-top bg-white"
                  />
                ) : (
                  <ScaledResumePreview
                    builderData={builderPreviewData}
                    settings={settingsForTemplate(tpl.id)}
                  />
                )}
                <div className="absolute inset-0 flex items-center justify-center bg-slate-900/0 opacity-0 transition-all group-hover:bg-slate-900/20 group-hover:opacity-100">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-white/95 px-3 py-1.5 text-xs font-bold text-slate-900 shadow">
                    <Eye className="h-3.5 w-3.5" />
                    放大预览
                  </span>
                </div>
              </button>
            </div>

            {/* 信息与操作 */}
            <div className="flex flex-1 flex-col justify-between gap-3 p-4">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-base font-bold text-slate-900 dark:text-white truncate">
                    {tpl.name}
                  </h2>
                  <code className="shrink-0 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[11px] font-mono text-slate-700 dark:text-slate-300 rounded">
                    {tpl.id}
                  </code>
                </div>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-300 line-clamp-2">
                  {tpl.description}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => void handleTryTemplate(tpl.id)}
                  disabled={tryingId === tpl.id}
                  className="inline-flex items-center justify-center gap-1 whitespace-nowrap border border-black fresh:border-[#356fd6] bg-[#4285F4] px-2.5 py-2 text-xs font-bold text-white fresh:rounded-lg hover:bg-[#3367D6] disabled:opacity-60 transition-colors"
                >
                  <Play className="h-3.5 w-3.5 shrink-0" />
                  <span>{importedResume ? '套用模板' : '在线体验'}</span>
                </button>
                {supportsCli ? (
                  <button
                    type="button"
                    onClick={() =>
                      void handleCopy(
                        promptKey,
                        buildSkillPrompt(tpl.id),
                        `已复制口令：${buildSkillPrompt(tpl.id)}`,
                      )
                    }
                    className={cn(
                      'inline-flex items-center justify-center gap-1 whitespace-nowrap border px-2.5 py-2 text-xs font-bold fresh:rounded-lg transition-colors',
                      isCopied
                        ? 'border-emerald-600 bg-emerald-50 text-emerald-700'
                        : 'border-black/40 fresh:border-slate-300 bg-white dark:bg-[#2A2A2A] text-slate-800 dark:text-slate-100 hover:bg-slate-50',
                    )}
                  >
                    {isCopied ? (
                      <>
                        <Check className="h-3.5 w-3.5 shrink-0" />
                        <span>已复制</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5 shrink-0" />
                        <span>复制口令</span>
                      </>
                    )}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setPreviewTemplate(tpl)}
                    className="inline-flex items-center justify-center gap-1 whitespace-nowrap border border-black/40 fresh:border-slate-300 bg-white dark:bg-[#2A2A2A] px-2.5 py-2 text-xs font-bold text-slate-800 dark:text-slate-100 fresh:rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <Eye className="h-3.5 w-3.5 shrink-0" />
                    <span>放大预览</span>
                  </button>
                )}
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )

  return (
    <WorkspaceLayout>
      <div className="h-full overflow-y-auto bg-[#F6F3EC] fresh:bg-slate-50 dark:bg-[#141414]">
        <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 space-y-6">
          {/* 顶部说明与导入区 */}
          <section className="border-2 fresh:border border-black fresh:border-slate-200 bg-white dark:bg-[#1C1C1C] dark:border-white p-5 sm:p-6 shadow-[4px_4px_0px_0px_#000000] fresh:rounded-xl fresh:shadow-sm dark:shadow-[4px_4px_0px_0px_#ffffff]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 border border-black fresh:border-blue-200 bg-[#D7E7FF] fresh:bg-blue-50 px-2.5 py-0.5 text-xs font-mono fresh:font-sans font-bold text-[#1a73e8] fresh:rounded-full">
                    <LayoutGrid className="h-3.5 w-3.5" />
                    {TEMPLATE_METADATA.length} 套真实工作台模板
                  </span>
                  <span className="inline-flex items-center gap-1.5 border border-black/20 fresh:border-emerald-200 bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300 fresh:rounded-full">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {isAuthenticated ? '已登录 · 支持云端同步' : '免登录可用 · 编辑内容留在本地浏览器'}
                  </span>
                </div>
                <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-slate-900 dark:text-white">
                  所见即工作台真实排版，选好直接写或交给 AI Agent
                </h1>
                <p className="text-sm text-slate-600 dark:text-slate-300 max-w-3xl">
                  与工作台抽屉 1:1 对齐：支持本地免登录直接在线编辑与 HTML 导出；带「复制口令」的模板还可直接发给 Codex / Claude Code 本地出稿。
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2.5 shrink-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json,application/json"
                  className="hidden"
                  aria-label="选择本地 resume.json 文件"
                  onChange={handleFileSelected}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-2 border-2 fresh:border border-black fresh:border-slate-300 bg-[#F6F3EC] fresh:bg-white dark:bg-[#2A2A2A] dark:border-white px-4 py-2.5 text-sm font-bold text-slate-900 dark:text-white shadow-[2px_2px_0px_0px_#000000] fresh:rounded-lg fresh:shadow-sm hover:bg-[#E5E5E0] dark:hover:bg-[#333333] transition-colors"
                >
                  <FileJson className="h-4 w-4 text-[#3367D6]" />
                  <span>导入我的 JSON 试套</span>
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/create-new', { state: { from: '/templates' } })}
                  className="inline-flex items-center gap-2 border-2 fresh:border border-black fresh:border-[#356fd6] bg-[#4285F4] px-4 py-2.5 text-sm font-bold text-white shadow-[2px_2px_0px_0px_#000000] fresh:rounded-lg fresh:shadow-sm hover:bg-[#3367D6] transition-colors"
                >
                  <Upload className="h-4 w-4" />
                  <span>导入 PDF / AI 从零创建</span>
                </button>
              </div>
            </div>

            {importedResume && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border border-blue-300 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-800 px-3.5 py-2.5 text-sm fresh:rounded-lg">
                <div className="flex items-center gap-2 text-blue-900 dark:text-blue-200">
                  <Sparkles className="h-4 w-4 shrink-0 text-blue-600" />
                  <span>
                    正在用「<strong>{importedResume.basic.name || importedResume.title || '本地简历'}</strong>」的 JSON 实时预览模板（仅保留在当前浏览器）
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setImportedResume(null)}
                  className="inline-flex items-center gap-1 text-xs font-bold text-blue-700 dark:text-blue-300 hover:underline"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  恢复默认样例
                </button>
              </div>
            )}
          </section>

          {/* 筛选条与搜索 */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="模板分类筛选">
              {FILTER_TABS.map((tab) => {
                const active = activeTab === tab.id
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'px-3.5 py-1.5 text-xs font-bold border transition-all fresh:rounded-full',
                      active
                        ? 'border-black fresh:border-[#4285F4] bg-[#4285F4] text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm'
                        : 'border-black/30 fresh:border-slate-200 bg-white dark:bg-[#222] dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:border-black',
                    )}
                  >
                    {tab.label}
                  </button>
                )
              })}
            </div>

            <label className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜模板 ID / 风格 / 场景..."
                className="w-full border border-black/30 fresh:border-slate-200 bg-white dark:bg-[#222] dark:border-slate-700 py-2 pl-9 pr-3 text-sm text-slate-900 dark:text-white fresh:rounded-lg focus:border-[#4285F4] focus:outline-none"
              />
            </label>
          </div>

          {/* 模板卡片网格 */}
          {filteredTemplates.length === 0 ? (
            <div className="border-2 border-dashed border-slate-300 dark:border-slate-700 bg-white/70 dark:bg-[#1C1C1C] py-16 text-center fresh:rounded-xl">
              <p className="text-sm text-slate-500 dark:text-slate-400">没有找到匹配的模板，试试清空搜索条件</p>
            </div>
          ) : activeTab === 'all' && recommendedInView.length > 0 && otherInView.length > 0 ? (
            <div className="space-y-6">
              <section className="space-y-3" aria-label="推荐默认模板">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200">
                    推荐默认（{recommendedInView.length}）
                  </span>
                  <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
                </div>
                {renderTemplateGrid(recommendedInView, 'recommended-templates-section')}
              </section>

              <div className="flex items-center gap-3 py-1" role="separator" aria-label="其余模板分割线">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  全部其他模板（{otherInView.length}）
                </span>
                <div className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
              </div>

              {renderTemplateGrid(otherInView, 'other-templates-section')}
            </div>
          ) : (
            renderTemplateGrid(filteredTemplates)
          )}
        </div>
      </div>

      {/* 放大预览弹窗 */}
      {previewTemplate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
          aria-label={`预览模板 ${previewTemplate.name}`}
          onClick={() => setPreviewTemplate(null)}
        >
          <div
            className="flex max-h-[92vh] w-full max-w-[1180px] flex-col border-2 border-black bg-white dark:bg-[#1C1C1C] dark:border-white shadow-[8px_8px_0px_0px_#000000] fresh:rounded-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 dark:border-slate-800 px-5 py-3.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <h3 className="text-lg font-bold text-slate-900 dark:text-white truncate">
                  {previewTemplate.name}
                </h3>
                <code className="bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-mono text-slate-700 dark:text-slate-300 rounded">
                  {previewTemplate.id}
                </code>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {previewTemplate.supportsCli !== false && (
                  <button
                    type="button"
                    onClick={() =>
                      void handleCopy(
                        `modal-prompt:${previewTemplate.id}`,
                        buildSkillPrompt(previewTemplate.id),
                        `已复制口令：${buildSkillPrompt(previewTemplate.id)}`,
                      )
                    }
                    className="inline-flex items-center gap-1.5 border border-slate-300 bg-white dark:bg-[#2A2A2A] px-3 py-1.5 text-xs font-bold text-slate-800 dark:text-slate-100 fresh:rounded-lg hover:bg-slate-50"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    复制 Agent 口令
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void handleTryTemplate(previewTemplate.id)}
                  className="inline-flex items-center gap-1.5 bg-[#4285F4] px-3.5 py-1.5 text-xs font-bold text-white fresh:rounded-lg hover:bg-[#3367D6]"
                >
                  <Play className="h-3.5 w-3.5" />
                  {importedResume ? '套用并进入编辑' : '免登录用此模板编辑'}
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewTemplate(null)}
                  aria-label="关闭预览"
                  className="p-1.5 text-slate-500 hover:text-slate-900 dark:hover:text-white"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] flex-1 min-h-0 overflow-hidden">
              <div className="overflow-y-auto bg-slate-100 dark:bg-slate-950 p-4 sm:p-6 flex justify-center">
                <div className="w-full max-w-[794px] border border-slate-300 bg-white shadow-lg">
                  {useStaticXeLatexPreview(previewTemplate) ? (
                    <img
                      src={previewTemplate.thumbnail}
                      alt={`${previewTemplate.name} XeLaTeX 真实渲染预览`}
                      className="w-full h-auto block bg-white"
                    />
                  ) : (
                    <ScaledResumePreview
                      builderData={builderPreviewData}
                      settings={settingsForTemplate(previewTemplate.id)}
                      fallbackScale={1}
                      aspectClip={false}
                    />
                  )}
                </div>
              </div>

              <aside className="border-t lg:border-t-0 lg:border-l border-slate-200 dark:border-slate-800 p-5 space-y-4 overflow-y-auto bg-white dark:bg-[#1C1C1C]">
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">模板说明</h4>
                  <p className="mt-1.5 text-sm text-slate-700 dark:text-slate-300">
                    {previewTemplate.description}
                  </p>
                  {previewTemplate.type === 'latex' && importedResume && (
                    <p className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 border border-amber-200">
                      已加载你导入的 JSON（上方为排版结构示意；点击「套用并进入编辑」即可在工作台调用 XeLaTeX 编译真实矢量 PDF）。
                    </p>
                  )}
                  {previewTemplate.tags && previewTemplate.tags.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {previewTemplate.tags.map((tag) => (
                        <span
                          key={tag}
                          className="bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs text-slate-600 dark:text-slate-300 rounded"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {previewTemplate.supportsCli !== false ? (
                  <>
                    <div className="space-y-2 border-t border-slate-200 dark:border-slate-800 pt-4">
                      <div className="flex items-center justify-between">
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 dark:text-slate-200">
                          <Sparkles className="h-3.5 w-3.5 text-[#4285F4]" />
                          发给 Codex / Claude Code
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            void handleCopy(
                              `side-prompt:${previewTemplate.id}`,
                              buildSkillPrompt(previewTemplate.id),
                              '已复制 Skill 对话口令',
                            )
                          }
                          className="text-xs font-bold text-[#4285F4] hover:underline"
                        >
                          {copiedKey === `side-prompt:${previewTemplate.id}` ? '已复制 ✓' : '复制'}
                        </button>
                      </div>
                      <pre className="whitespace-pre-wrap break-all rounded-lg bg-slate-900 p-2.5 text-xs text-slate-100 font-mono">
                        {buildSkillPrompt(previewTemplate.id)}
                      </pre>
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 dark:text-slate-200">
                          <Terminal className="h-3.5 w-3.5 text-emerald-600" />
                          本地 CLI 命令
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            void handleCopy(
                              `side-cli:${previewTemplate.id}`,
                              buildCliCommand(previewTemplate.id),
                              '已复制本地 CLI 命令',
                            )
                          }
                          className="text-xs font-bold text-[#4285F4] hover:underline"
                        >
                          {copiedKey === `side-cli:${previewTemplate.id}` ? '已复制 ✓' : '复制'}
                        </button>
                      </div>
                      <pre className="whitespace-pre-wrap break-all rounded-lg bg-slate-900 p-2.5 text-xs text-emerald-300 font-mono">
                        {buildCliCommand(previewTemplate.id)}
                      </pre>
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 p-3 text-xs text-slate-600 dark:text-slate-300 space-y-1.5">
                    <div className="font-bold text-slate-800 dark:text-slate-100">网页工作台专属模板</div>
                    <p>
                      此版式仅在网页工作台提供，无需登录即可直接在线编辑并导出；如需在 Codex / Claude 本地 CLI 生成，建议选用「Classic LaTeX」或「ASu」系列模板。
                    </p>
                  </div>
                )}

                <div className="border-t border-slate-200 dark:border-slate-800 pt-4 space-y-2">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full inline-flex items-center justify-center gap-1.5 border border-slate-300 bg-slate-50 dark:bg-[#2A2A2A] px-3 py-2 text-xs font-bold text-slate-800 dark:text-slate-100 fresh:rounded-lg hover:bg-slate-100"
                  >
                    <FileJson className="h-3.5 w-3.5 text-[#3367D6]" />
                    导入我的 resume.json 试套这套
                  </button>
                </div>
              </aside>
            </div>
          </div>
        </div>
      )}
    </WorkspaceLayout>
  )
}
