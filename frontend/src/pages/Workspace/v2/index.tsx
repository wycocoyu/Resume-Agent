import { toast } from '@/lib/toast'
/**
 * Workspace v2 - 编辑区主入口
 * 使用 WorkspaceLayout 包裹，提供统一的侧边栏布局
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import html2pdf from 'html2pdf.js'

// Hooks
import { useAIImport, useAutoSaveResume, usePDFOperations, useResumeData } from './hooks'

// 组件
import WorkspaceLayout from '@/pages/WorkspaceLayout'
import { HeaderActions } from './components/HeaderActions'
import SkinPickerModal from './components/SkinPickerModal'
import { getStoredSkin } from '@/lib/skin'
import EditPreviewLayout from './EditPreviewLayout'
import AIImportModal from './shared/AIImportModal'
import JdOptimizeDialog from './shared/JdOptimizeDialog'
import JdMatchDialog from './shared/JdMatchDialog'
import TranslateDialog from './shared/TranslateDialog'
import HealthCheckDialog from './shared/HealthCheckDialog'
// AI 助手悬浮气泡暂不开放（2026-07-17），恢复时连同下方渲染处一起取消注释
// import AiAssistantChat from './shared/AiAssistantChat'
import { scoreResume, type JdOptimizeField } from '@/services/api'
import { stripHtmlTags } from './utils/textUtils'
import { withSettingsDefaults } from '../../Builder/settings'

const PDF_RENDER_DEBOUNCE_MS = 2000
// 首次加载的自动渲染延迟：短一点，打开工作台即出预览
const PDF_RENDER_INITIAL_DELAY_MS = 300

export default function WorkspaceV2() {
  const { resumeId } = useParams<{ resumeId?: string }>()

  // 跟踪编辑状态和保存状态
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [initialResumeData, setInitialResumeData] = useState<any>(null)
  const [isAutoRenderPending, setIsAutoRenderPending] = useState(false)
  // 评分状态
  const [jdText, setJdText] = useState('')
  const [scoreData, setScoreData] = useState<any>(null)
  const [scoring, setScoring] = useState(false)
  const [showJdMatch, setShowJdMatch] = useState(false)
  const [showJdOptimize, setShowJdOptimize] = useState(false)
  const [showTranslate, setShowTranslate] = useState(false)
  const [showHealthCheck, setShowHealthCheck] = useState(false)
  // 首次进入编辑页且从未选过皮肤时,弹皮肤选择框
  const [showSkinPicker, setShowSkinPicker] = useState(() => getStoredSkin() === null)
  // 简历数据管理
  const {
    resumeData,
    setResumeData,
    activeSection,
    setActiveSection,
    currentResumeId,
    setCurrentId,
    isDataLoaded,
    updateBasicInfo,
    updateProject,
    deleteProject,
    reorderProjects,
    updateExperience,
    deleteExperience,
    reorderExperiences,
    updateWorkExperience,
    deleteWorkExperience,
    reorderWorkExperiences,
    updateEducation,
    deleteEducation,
    reorderEducations,
    updateOpenSource,
    deleteOpenSource,
    reorderOpenSources,
    updateAward,
    deleteAward,
    reorderAwards,
    addCustomItem,
    updateCustomItem,
    deleteCustomItem,
    updateSelfEvaluation,
    updateSkillContent,
    applyTextReplacement,
    applyTextReplacements,
    updateMenuSections,
    reorderSections,
    toggleSectionVisibility,
    updateGlobalSettings,
    addCustomSection,
  } = useResumeData()

  // 构建 JD 优化的可改写字段列表（自我评价 / 技能 / 各实习·项目·开源的正文）
  const jdFields = useMemo<JdOptimizeField[]>(() => {
    const fields: JdOptimizeField[] = []
    if (resumeData.selfEvaluation?.trim()) {
      fields.push({ key: 'selfEvaluation', label: '自我评价', content: resumeData.selfEvaluation })
    }
    if (resumeData.skillContent?.trim()) {
      fields.push({ key: 'skillContent', label: '专业技能', content: resumeData.skillContent })
    }
    resumeData.experience?.forEach((e) => {
      if (e.details?.trim()) fields.push({ key: `experience:${e.id}`, label: `实习·${stripHtmlTags(e.company) || '经历'}`, content: e.details })
    })
    resumeData.projects?.forEach((p) => {
      if (p.description?.trim()) fields.push({ key: `project:${p.id}`, label: `项目·${stripHtmlTags(p.name) || ''}`, content: p.description })
    })
    resumeData.openSource?.forEach((o) => {
      if (o.description?.trim()) fields.push({ key: `openSource:${o.id}`, label: `开源·${stripHtmlTags(o.name) || ''}`, content: o.description })
    })
    return fields
  }, [resumeData])

  // 点击外部区域关闭下拉菜单
  // PDF 操作
  const {
    pdfBlob,
    loading,
    progress,
    renderError,
    saveSuccess,
    handleRender,
    handleDownload,
  } = usePDFOperations({ resumeData, currentResumeId, setCurrentId })

  // AI 导入
  const {
    aiModalOpen,
    aiModalSection,
    aiModalTitle,
    setAiModalOpen,
    handleAIImport,
    handleGlobalAIImport,
    handleAISave,
  } = useAIImport({ setResumeData })


  // 文件输入引用（用于导入 JSON）
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 自动保存（带路由 ID 时按 ID 保存）
  const { saveStatus, saveError } = useAutoSaveResume({
    resumeData,
    currentResumeId,
    routeResumeId: resumeId,
    isDataLoaded,
    setCurrentId,
  })

  // 监听编辑状态：页面加载时保存初始状态
  useEffect(() => {
    if (!initialResumeData) {
      setInitialResumeData(JSON.stringify(resumeData))
    }
  }, [])

  // 监听简历数据变化，判断是否有未保存的修改
  useEffect(() => {
    if (initialResumeData && saveSuccess === false) {
      const currentData = JSON.stringify(resumeData)
      setHasUnsavedChanges(currentData !== initialResumeData)
    }
  }, [resumeData, initialResumeData, saveSuccess])

  // 保存成功时（手动保存或自动保存），更新初始状态
  // 依赖只跟保存状态：仅在“变为已保存”那一刻快照，避免把保存后的新编辑误标为已保存
  useEffect(() => {
    if (saveSuccess || saveStatus === 'saved') {
      setInitialResumeData(JSON.stringify(resumeData))
      setHasUnsavedChanges(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveSuccess, saveStatus])

  // 页面卸载时提醒用户保存
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault()
        e.returnValue = '记得保存简历的修改'
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasUnsavedChanges])

  const renderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hasPendingRenderRef = useRef(false)
  const loadingRef = useRef(loading)
  const autoRenderInitializedRef = useRef(false)

  useEffect(() => {
    loadingRef.current = loading
  }, [loading])

  const scheduleRender = useCallback((delayMs: number) => {
    if (renderTimerRef.current) clearTimeout(renderTimerRef.current)
    renderTimerRef.current = setTimeout(() => {
      if (loadingRef.current) return
      if (!hasPendingRenderRef.current) return
      hasPendingRenderRef.current = false
      setIsAutoRenderPending(false)
      handleRender()
    }, delayMs)
  }, [handleRender])

  // 简历数据变化时自动触发 PDF 渲染（仅 LaTeX）
  // 策略：编辑空闲一段时间后统一渲染，避免每次输入都刷新 PDF
  useEffect(() => {
    if (!isDataLoaded) return
    if (resumeData.templateType === 'html') return
    if (!autoRenderInitializedRef.current) {
      autoRenderInitializedRef.current = true
      // 首次加载也自动渲染预览（渲染对所有人开放，无需登录）
      hasPendingRenderRef.current = true
      setIsAutoRenderPending(false)
      scheduleRender(PDF_RENDER_INITIAL_DELAY_MS)
      return
    }
    hasPendingRenderRef.current = true
    setIsAutoRenderPending(true)
    scheduleRender(PDF_RENDER_DEBOUNCE_MS)
  }, [resumeData, isDataLoaded, scheduleRender])

  // 若渲染期间继续有编辑，等当前渲染结束后再补一次（合并多次变更）
  useEffect(() => {
    if (resumeData.templateType === 'html') return
    if (!loading && hasPendingRenderRef.current) {
      scheduleRender(PDF_RENDER_DEBOUNCE_MS)
    }
  }, [loading, resumeData.templateType, scheduleRender])

  // 引擎偏好持久化恢复与即时渲染调度
  useEffect(() => {
    try {
      const preferred = localStorage.getItem('cococv_preferred_render_engine')
      if (preferred === 'html' || preferred === 'latex') {
        setResumeData((prev) => {
          if (prev.templateType === preferred) return prev
          return { ...prev, templateType: preferred }
        })
      }
    } catch {}
  }, [setResumeData])

  const prevTemplateTypeRef = useRef(resumeData.templateType)
  useEffect(() => {
    if (prevTemplateTypeRef.current === 'html' && resumeData.templateType === 'latex' && !pdfBlob) {
      hasPendingRenderRef.current = true
      scheduleRender(0)
    }
    prevTemplateTypeRef.current = resumeData.templateType
  }, [resumeData.templateType, pdfBlob, scheduleRender])

  useEffect(() => {
    return () => {
      if (renderTimerRef.current) clearTimeout(renderTimerRef.current)
    }
  }, [])

  // JD 文本变化时自动触发评分
  useEffect(() => {
    if (currentResumeId && jdText && jdText.trim().length > 10) {
      setScoring(true)
      scoreResume(currentResumeId, jdText)
        .then(setScoreData)
        .catch(console.error)
        .finally(() => setScoring(false))
    }
  }, [currentResumeId, jdText])

  // HTML 模板：前端 html2pdf 导出预览容器（TODO: 换 window.print 真文字方案，见设计文档）
  const handleDownloadHtmlPDF = useCallback(() => {
    const sourceElement = document.querySelector('.html-template-container') as HTMLElement | null
    if (!sourceElement) {
      toast.error('找不到简历预览内容，请确保预览区域可见')
      return
    }
    const filename = `${resumeData?.basic?.name || '简历'}-${new Date().toISOString().split('T')[0]}.pdf`
    // 页面尺寸跟随排版设置（A4 / US Letter）
    const pageSize = withSettingsDefaults(resumeData?.globalSettings?.builderSettings).pageSize
    html2pdf()
      .set({
        margin: 0,
        filename,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: pageSize === 'LETTER' ? 'letter' : 'a4', orientation: 'portrait' },
      })
      .from(sourceElement)
      .save()
      .catch(() => toast.error('导出 PDF 失败，请重试'))
  }, [resumeData?.basic?.name, resumeData?.globalSettings?.builderSettings])

  // 下载入口按模板类型分流：经典 LaTeX 走后端 PDF，HTML 模板走前端导出
  const handleDownloadByTemplate =
    resumeData.templateType === 'html' ? handleDownloadHtmlPDF : handleDownload

  // 导出 JSON
  const handleExportJSON = () => {
    try {
      const jsonString = JSON.stringify(resumeData, null, 2)
      const blob = new Blob([jsonString], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `resume-${new Date().toISOString().split('T')[0]}.json`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error('导出 JSON 失败:', error)
      toast.error('导出失败，请重试')
    }
  }

  // 导入 JSON
  const handleImportJSON = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string
        const importedData = JSON.parse(text)

        // 验证数据格式（基本检查）
        if (typeof importedData === 'object' && importedData !== null) {
          setResumeData(importedData)
          toast.success('导入成功！')
        } else {
          throw new Error('无效的 JSON 格式')
        }
      } catch (error) {
        console.error('导入 JSON 失败:', error)
        toast.error('导入失败：文件格式不正确，请确保是有效的 JSON 文件')
      }
    }
    reader.onerror = () => {
      toast.error('读取文件失败，请重试')
    }
    reader.readAsText(file)

    // 清空 input，以便可以重复选择同一文件
    event.target.value = ''
  }

  return (
    <WorkspaceLayout>
      {/* 首次进入且从未选过皮肤:弹选择框 */}
      <SkinPickerModal open={showSkinPicker} onPicked={() => setShowSkinPicker(false)} />

      {/* 工作区标题：NEO 保留海报感，Fresh 使用克制的产品工具栏层级 */}
      <div className="border-b border-black fresh:border-slate-200 dark:border-white bg-[#F0F0E8] fresh:bg-white dark:bg-[#1C1C1C] px-6 py-3 md:px-8 shrink-0">
        <div className="flex items-baseline gap-4 flex-wrap">
          <h1 className="font-mono fresh:font-hero text-[28px] font-black fresh:font-bold uppercase fresh:normal-case text-black fresh:text-slate-900 dark:text-white tracking-[-0.04em] fresh:tracking-[-0.025em] leading-none">
            Resume Builder
          </h1>
          <div className="flex items-center gap-3">
            <p className="text-sm font-mono fresh:font-sans text-blue-700 fresh:text-slate-500 tracking-normal font-medium">
              正在编辑
            </p>
            {resumeData?.basic?.name && (
              <span className="font-mono fresh:font-sans text-xs text-[#444850] fresh:text-gray-600 dark:text-neutral-300 border border-black fresh:border-slate-200 dark:border-white bg-white dark:bg-[#2A2A2A] px-2 py-1 fresh:rounded-md">
                {resumeData.basic.name}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 编辑 + 预览三列布局(原顶部整行操作栏已并入预览工具栏右侧) */}
      <EditPreviewLayout
        toolbarActions={
          <HeaderActions
            saveStatus={saveStatus}
            saveError={saveError}
            onGlobalAIImport={handleGlobalAIImport}
            onExportJSON={handleExportJSON}
            onImportJSON={handleImportJSON}
            resumeData={resumeData}
            resumeName={resumeData?.basic?.name || '我的简历'}
            pdfBlob={pdfBlob}
            onDownloadPDF={handleDownloadByTemplate}
          />
        }
        resumeData={resumeData}
        setResumeData={setResumeData}
        activeSection={activeSection}
        setActiveSection={setActiveSection}
        toggleSectionVisibility={toggleSectionVisibility}
        updateMenuSections={updateMenuSections}
        reorderSections={reorderSections}
        updateGlobalSettings={updateGlobalSettings}
        addCustomSection={addCustomSection}
        updateBasicInfo={updateBasicInfo}
        updateProject={updateProject}
        deleteProject={deleteProject}
        reorderProjects={reorderProjects}
        updateExperience={updateExperience}
        deleteExperience={deleteExperience}
        reorderExperiences={reorderExperiences}
        updateWorkExperience={updateWorkExperience}
        deleteWorkExperience={deleteWorkExperience}
        reorderWorkExperiences={reorderWorkExperiences}
        updateEducation={updateEducation}
        deleteEducation={deleteEducation}
        reorderEducations={reorderEducations}
        updateOpenSource={updateOpenSource}
        deleteOpenSource={deleteOpenSource}
        reorderOpenSources={reorderOpenSources}
        updateAward={updateAward}
        deleteAward={deleteAward}
        reorderAwards={reorderAwards}
        addCustomItem={addCustomItem}
        updateCustomItem={updateCustomItem}
        deleteCustomItem={deleteCustomItem}
        updateSelfEvaluation={updateSelfEvaluation}
        updateSkillContent={updateSkillContent}
        handleAIImport={handleAIImport}
        pdfBlob={pdfBlob}
        loading={loading}
        progress={progress}
        renderError={renderError}
        autoRenderPending={isAutoRenderPending}
        handleRender={handleRender}
        handleDownload={handleDownloadByTemplate}
      />

      {/* JD 匹配优化 —— 聚焦弹窗（粘 JD → 多维评分 → 一键深度优化），取代页面底部常驻大框 */}
      <JdMatchDialog
        open={showJdMatch}
        onOpenChange={setShowJdMatch}
        jdText={jdText}
        onJdTextChange={(v) => { setJdText(v); setScoreData(null) }}
        scoreData={scoreData}
        scoring={scoring}
        hasContent={jdFields.length > 0}
        onOptimize={() => { setShowJdMatch(false); setShowJdOptimize(true) }}
      />

      {/* 针对 JD 优化弹窗 */}
      <JdOptimizeDialog
        open={showJdOptimize}
        onOpenChange={setShowJdOptimize}
        fields={jdFields}
        jdText={jdText}
        onApply={applyTextReplacement}
        onApplyBatch={applyTextReplacements}
      />

      {/* 简历一键翻译弹窗 */}
      <TranslateDialog
        open={showTranslate}
        onOpenChange={setShowTranslate}
        fields={jdFields}
        onApply={applyTextReplacement}
        onApplyBatch={applyTextReplacements}
      />

      {/* 通用简历体检弹窗 */}
      <HealthCheckDialog
        open={showHealthCheck}
        onOpenChange={setShowHealthCheck}
        fields={jdFields}
        onApply={applyTextReplacement}
        onApplyBatch={applyTextReplacements}
      />

      {/* AI 助手（右下角绿色悬浮气泡）暂不开放，先隐藏（2026-07-17 产品决定）。
          恢复时取消下面注释即可，props 契约未变。 */}
      {/* <AiAssistantChat
        resumeData={resumeData}
        onJdOptimize={() => setShowJdMatch(true)}
        jdReady={jdText.trim().length >= 10 && jdFields.length > 0}
        onFocusJd={() => setShowJdMatch(true)}
        onTranslate={() => setShowTranslate(true)}
        onHealthCheck={() => setShowHealthCheck(true)}
        hasContent={jdFields.length > 0}
      /> */}

      {/* 隐藏的文件输入（用于导入 JSON） */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />

      {/* AI 导入弹窗 */}
      <AIImportModal
        isOpen={aiModalOpen}
        sectionType={aiModalSection}
        sectionTitle={aiModalTitle}
        onClose={() => setAiModalOpen(false)}
        onSave={handleAISave}
      />

    </WorkspaceLayout>
  )
}
