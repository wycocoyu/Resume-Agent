import React, { useState, useCallback, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Header } from './components/Header'
import { CreateCard } from './components/CreateCard'
import { ResumeCard } from './components/ResumeCard'
import { useDashboardLogic } from './hooks/useDashboardLogic'
import { Alert, AlertDescription, AlertTitle } from './components/ui/alert'
import { AlertCircle, Settings } from './components/Icons'
import { Button } from './components/ui/button'
import WorkspaceLayout from '@/pages/WorkspaceLayout'
import { useAuth } from '@/contexts/AuthContext'
import { useRuntimeFeatures } from '@/lib/runtimeEnv'
import AIImportModal from '@/pages/Workspace/v2/shared/AIImportModal'
import { saveResume, setCurrentResumeId } from '@/services/resumeStorage'
import type { ResumeData } from '@/pages/Workspace/v2/types'
import { matchCompanyLogo } from '@/pages/Workspace/v2/constants/companyLogos'
import { highlightsToHtml, groupedHighlightsToHtml, skillsToHtml } from '@/utils/resumeRichtext'
import './dashboard.css'

const RESUMES_PER_PAGE = 8
const FIRST_PAGE_RESUME_COUNT = RESUMES_PER_PAGE - 1

const getPaginationItems = (currentPage: number, totalPages: number): Array<number | 'ellipsis'> => {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1)
  }

  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1])
  const sortedPages = [...pages]
    .filter(page => page >= 1 && page <= totalPages)
    .sort((a, b) => a - b)

  const items: Array<number | 'ellipsis'> = []
  sortedPages.forEach((page, index) => {
    if (index > 0 && page - sortedPages[index - 1] > 1) items.push('ellipsis')
    items.push(page)
  })
  return items
}

const ResumeDashboard = () => {
  const navigate = useNavigate()
  const resumeGridRef = useRef<HTMLDivElement>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const pageFromUrl = Number.parseInt(searchParams.get('page') || '1', 10)
  const currentPage = Number.isFinite(pageFromUrl) && pageFromUrl > 0 ? pageFromUrl : 1
  const pageSize = currentPage === 1 ? FIRST_PAGE_RESUME_COUNT : RESUMES_PER_PAGE
  const pageOffset = currentPage === 1
    ? 0
    : FIRST_PAGE_RESUME_COUNT + (currentPage - 2) * RESUMES_PER_PAGE
  const { isAuthenticated, user, logout, openModal } = useAuth()
  const { authEnabled } = useRuntimeFeatures()
  const {
    resumes,
    totalCount,
    isLoading,
    hasLoaded,
    createResume,
    deleteResume,
    duplicateResume,
    editResume,
    importJson,
    // 多选模式相关
    isMultiSelectMode,
    toggleMultiSelectMode,
    exitMultiSelectMode,
    selectedIds,
    toggleSelect,
    batchDelete,
    batchDownload,
    downloadProgress,
    clearSelection,
    selectAll,
    // 备注/别名
    updateAlias,
    // 置顶
    togglePin,
    // 刷新列表
    loadResumes
  } = useDashboardLogic({ offset: pageOffset, limit: pageSize })

  const totalPages = totalCount <= FIRST_PAGE_RESUME_COUNT
    ? 1
    : 1 + Math.ceil((totalCount - FIRST_PAGE_RESUME_COUNT) / RESUMES_PER_PAGE)
  const activePage = Math.min(currentPage, totalPages)
  const pageStart = pageOffset
  const visibleResumes = resumes
  const paginationItems = getPaginationItems(activePage, totalPages)

  useEffect(() => {
    if (!hasLoaded || currentPage <= totalPages) return
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (totalPages <= 1) next.delete('page')
      else next.set('page', String(totalPages))
      return next
    }, { replace: true })
  }, [currentPage, hasLoaded, setSearchParams, totalPages])

  const changePage = useCallback((page: number) => {
    const nextPage = Math.max(1, Math.min(page, totalPages))
    if (nextPage === activePage) return
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (nextPage === 1) next.delete('page')
      else next.set('page', String(nextPage))
      return next
    })

    requestAnimationFrame(() => {
      resumeGridRef.current?.scrollIntoView({ behavior: 'auto', block: 'start' })
    })
  }, [activePage, setSearchParams, totalPages])

  // 登录时数据保存到数据库，未登录时保存到本地存储
  const hasConfiguredFolder = true // 总是有存储配置（本地或云端）

  // AI 智能导入相关状态
  const [aiModalOpen, setAiModalOpen] = useState(false)

  // 打开 AI 导入弹窗
  const handleOpenAIImport = useCallback(() => {
    setAiModalOpen(true)
  }, [])

  // 从 /create-new 带 ?openAIImport=1 进入时自动打开 AI 导入弹窗
  useEffect(() => {
    if (searchParams.get('openAIImport') === '1') {
      setAiModalOpen(true)
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.delete('openAIImport')
        return next
      }, { replace: true })
    }
  }, [])

  // AI 解析完成后，创建新简历并跳转到工作区
  const handleAISave = useCallback(async (data: any) => {
    // 将 AI 解析的数据转换为 ResumeData 格式
    const newResumeData: ResumeData = {
      basic: {
        name: data.name || '',
        title: data.objective || '',
        email: data.contact?.email || '',
        phone: data.contact?.phone || '',
        location: data.contact?.location || '',
      },
      education: data.education?.map((e: any, i: number) => {
        let startDate = ''
        let endDate = ''
        if (e.date) {
          const dateStr = e.date.trim()
          const dateMatch = dateStr.match(/^(.+?)\s*[-–~]\s*(.+)$/)
          if (dateMatch) {
            startDate = dateMatch[1].trim()
            endDate = dateMatch[2].trim()
          } else {
            startDate = dateStr
          }
        }
        return {
          id: `edu_${Date.now()}_${i}`,
          school: e.title || '',
          major: e.subtitle || '',
          degree: e.degree || '',
          startDate,
          endDate,
          // 补充说明是富文本编辑器字段，统一转成无序列表 HTML（与 Agent 编辑链路一致）
          description: e.details?.length > 0 ? highlightsToHtml(e.details) : '',
          visible: true,
        }
      }) || [],
      experience: data.internships?.map((e: any, i: number) => {
        const raw = (e.title || '').trim()
        const company = !raw ? '' : raw.startsWith('**') && raw.endsWith('**') ? raw : `**${raw}**`
        const logoKey = matchCompanyLogo(e.title || '')
        return {
          id: `exp_${Date.now()}_${i}`,
          company,
          position: e.subtitle || '',
          date: e.date || '',
          details: highlightsToHtml(e.highlights),
          visible: true,
          ...(logoKey ? { companyLogo: logoKey } : {}),
        }
      }) || [],
      projects: data.projects?.map((p: any, i: number) => {
        let description = p.description || ''
        if (p.highlights && p.highlights.length > 0) {
          const highlightsList = highlightsToHtml(p.highlights)
          description = description ? description + highlightsList : highlightsList
        }
        description = description.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        return {
          id: `proj_${Date.now()}_${i}`,
          name: p.title || '',
          role: p.subtitle || '',
          date: p.date || '',
          description: description,
          visible: true,
        }
      }) || [],
      openSource: data.openSource?.map((o: any, i: number) => ({
        id: `os_${Date.now()}_${i}`,
        name: o.title || o.name || '',
        role: o.subtitle || o.role || '',
        repo: o.repoUrl || o.repo || '',
        date: o.date || '',
        description: o.items?.length > 0 ? groupedHighlightsToHtml(o.items) : o.description || '',
        visible: true,
      })) || [],
      awards: data.awards?.map((a: any, i: number) => ({
        id: `award_${Date.now()}_${i}`,
        title: a.title || '',
        issuer: a.issuer || '',
        date: a.date || '',
        description: a.description || '',
        visible: true,
      })) || [],
      selfEvaluation: typeof data.summary === 'string' && data.summary.trim()
        ? `<p>${data.summary}</p>`
        : '',
      // 专业技能统一转成无序列表 HTML（与 Agent 编辑链路一致）
      skillContent: skillsToHtml(data.skills),
      templateType: 'latex',
    }

    // 保存为新简历
    const resumeId = `resume_latex_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`
    const saved = await saveResume(newResumeData, resumeId)
    setCurrentResumeId(saved.id)

    // 关闭弹窗
    setAiModalOpen(false)

    // 刷新列表
    await loadResumes()

    // 跳转到统一工作区编辑
    navigate(`/workspace/${saved.id}`)
  }, [navigate, loadResumes])

  return (
    <WorkspaceLayout>
      <div className="relative h-full overflow-x-hidden overflow-y-auto overscroll-y-contain bg-[#F6F3EC] fresh:bg-slate-50 [background-image:linear-gradient(rgba(10,10,10,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(10,10,10,0.04)_1px,transparent_1px)] fresh:[background-image:none] [background-size:48px_48px]">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
          className="resume-dashboard-canvas relative z-10 mx-auto max-w-[1440px]"
        >
          {/* 按当前断点扣除画布上下留白，保证内容较少时铺满视口且不产生额外滚动。 */}
          <div className="resume-dashboard-frame rounded-none border border-black bg-[#F6F3EC] shadow-[8px_8px_0px_0px_#000000] fresh:rounded-xl fresh:border-slate-200 fresh:bg-white fresh:shadow-[0_10px_30px_rgba(15,23,42,0.06)] dark:border-white dark:bg-[#1C1C1C] dark:shadow-[8px_8px_0px_0px_#ffffff]">
          <motion.div
            className="flex w-full items-center justify-center"
            initial={{ y: 8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.3, delay: 0.1 }}
          >
            {hasConfiguredFolder && (
              <Alert className="mb-0 max-w-2xl py-3">
                <AlertDescription className="flex items-center justify-center gap-3 fresh:font-sans">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-green-700 animate-pulse fresh:animate-none" />
                    <span className="text-sm font-mono fresh:font-sans font-bold fresh:font-medium uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black fresh:text-slate-600">
                      {isAuthenticated
                        ? '数据已同步至云端'
                        : authEnabled
                          ? '数据保存在本地'
                          : '数据保存在本机浏览器'}
                    </span>
                  </div>
                  {!isAuthenticated && authEnabled && (
                    <button
                      className="text-sm font-mono fresh:font-sans font-bold fresh:font-medium uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-[#3367D6] hover:underline underline-offset-4"
                      onClick={() => openModal('login')}
                    >
                      立即登录同步
                    </button>
                  )}
                </AlertDescription>
              </Alert>
            )}
          </motion.div>

          {/* 顶部标题栏 - 传入多选模式相关 props */}
          <Header
            onImport={importJson}
            onCreate={createResume}
            onAIImport={handleOpenAIImport}
            selectedCount={selectedIds.size}
            onBatchDelete={batchDelete}
            onBatchDownload={() => batchDownload(Array.from(selectedIds))}
            downloadProgress={downloadProgress}
            totalCount={totalCount}
            selectableCount={resumes.length}
            isMultiSelectMode={isMultiSelectMode}
            onToggleMultiSelectMode={toggleMultiSelectMode}
            onExitMultiSelectMode={exitMultiSelectMode}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
          />

          <motion.div
            className="resume-dashboard-results w-full pb-4"
            initial={{ y: 8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.3, delay: 0.2 }}
          >
            <div
              ref={resumeGridRef}
              className="resume-dashboard-grid grid w-full scroll-mt-4 grid-cols-1 content-start gap-4 sm:grid-cols-2 xl:grid-cols-4"
              aria-busy={isLoading}
            >
              {activePage === 1 && <CreateCard onClick={createResume} />}

              {!isLoading && visibleResumes.map((resume, idx) => (
                  <ResumeCard
                    key={resume.id}
                    resume={resume}
                    index={pageStart + idx + 1}
                    onEdit={editResume}
                    onDelete={deleteResume}
                    onDuplicate={duplicateResume}
                    // 多选模式相关
                    isMultiSelectMode={isMultiSelectMode}
                    isSelected={selectedIds.has(resume.id)}
                    onSelectChange={toggleSelect}
                    // 备注/别名
                    onAliasChange={updateAlias}
                    // 置顶
                    onTogglePin={togglePin}
                  />
                ))}

              {isLoading && Array.from({ length: pageSize }, (_, index) => (
                <div
                  key={`resume-skeleton-${index}`}
                  className="resume-dashboard-card border border-black/15 bg-black/[0.035] fresh:rounded-xl fresh:border-slate-200 fresh:bg-slate-100/70"
                  aria-hidden="true"
                />
              ))}
            </div>

            {totalPages > 1 && (
              <nav
                className="resume-dashboard-pagination flex items-center justify-center"
                aria-label="简历列表分页"
              >
                <div className="inline-flex items-center gap-1.5 [font-variant-numeric:tabular-nums]">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={isLoading || activePage === 1}
                    onClick={() => changePage(activePage - 1)}
                    className="h-10 w-10 rounded-none border-black bg-transparent shadow-none hover:translate-x-0 hover:translate-y-0 hover:bg-black/5 disabled:border-black/20 disabled:bg-transparent fresh:rounded-lg fresh:border-slate-200 fresh:bg-white fresh:text-slate-600 fresh:shadow-none fresh:hover:bg-slate-100 fresh:disabled:border-slate-200 fresh:disabled:bg-slate-50 fresh:disabled:text-slate-300"
                    aria-label="上一页"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>

                  <div className="flex items-center gap-1.5" aria-label={`第 ${activePage} 页，共 ${totalPages} 页`}>
                    {paginationItems.map((item, index) => item === 'ellipsis' ? (
                      <span
                        key={`ellipsis-${index}`}
                        className="flex h-10 w-6 items-center justify-center text-sm text-black/50 fresh:text-slate-400"
                        aria-hidden="true"
                      >
                        …
                      </span>
                    ) : (
                      <Button
                        key={item}
                        type="button"
                        variant={item === activePage ? 'default' : 'outline'}
                        size="icon"
                        disabled={isLoading}
                        onClick={() => changePage(item)}
                        className={`h-10 w-10 rounded-none border-black shadow-none hover:translate-x-0 hover:translate-y-0 fresh:rounded-lg fresh:font-sans fresh:normal-case fresh:tracking-normal fresh:shadow-none ${
                          item === activePage
                            ? 'bg-[#4285F4] text-white hover:bg-[#3367D6] fresh:border-blue-500 fresh:bg-[#4285F4] fresh:hover:bg-[#3367D6]'
                            : 'bg-transparent hover:bg-black/5 fresh:border-slate-200 fresh:bg-white fresh:text-slate-600 fresh:hover:bg-slate-100'
                        }`}
                        aria-label={`第 ${item} 页`}
                        aria-current={item === activePage ? 'page' : undefined}
                      >
                        {item}
                      </Button>
                    ))}
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={isLoading || activePage === totalPages}
                    onClick={() => changePage(activePage + 1)}
                    className="h-10 w-10 rounded-none border-black bg-transparent shadow-none hover:translate-x-0 hover:translate-y-0 hover:bg-black/5 disabled:border-black/20 disabled:bg-transparent fresh:rounded-lg fresh:border-slate-200 fresh:bg-white fresh:text-slate-600 fresh:shadow-none fresh:hover:bg-slate-100 fresh:disabled:border-slate-200 fresh:disabled:bg-slate-50 fresh:disabled:text-slate-300"
                    aria-label="下一页"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
                <span className="sr-only" aria-live="polite">
                  当前第 {activePage} 页，共 {totalPages} 页
                </span>
              </nav>
            )}
          </motion.div>
          </div>
        </motion.div>
      </div>
      {/* AI 智能导入弹窗 */}
      <AIImportModal
        isOpen={aiModalOpen}
        sectionType="all"
        sectionTitle="AI 智能导入"
        onClose={() => setAiModalOpen(false)}
        onSave={handleAISave}
      />
    </WorkspaceLayout>
  )
}

export default ResumeDashboard
