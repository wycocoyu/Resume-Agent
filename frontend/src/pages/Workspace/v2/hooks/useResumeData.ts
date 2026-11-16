/**
 * 简历数据管理 Hook
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { getCurrentResumeId, setCurrentResumeId, getResume } from '../../../../services/resumeStorage'
import { loadFromStorage, STORAGE_KEY, isLegacyDefaultMenuOrder, migrateMenuSectionsToLatestDefault, mergeMissingDefaultModules } from '../constants'
import { stripPhotoFromResumeData } from '@/services/storage/sanitizeResume'
import { stripHtmlTags } from '../utils/textUtils'
import { useLocation, useParams } from 'react-router-dom'
import { useResumeContext } from '@/contexts/ResumeContext'
import { applyRequestedTemplate } from '@/data/templates'
import type {
  ResumeData,
  MenuSection,
  BasicInfo,
  Project,
  Experience,
  Education,
  OpenSource,
  Award,
  CustomItem,
  GlobalSettings,
} from '../types'

/** 在简历数据上对某字段做一次确定性 original→suggested 替换，返回新数据（纯函数，供单条/批量复用） */
function replaceInResume(prev: ResumeData, key: string, original: string, suggested: string): ResumeData {
  if (key === 'selfEvaluation') {
    return { ...prev, selfEvaluation: (prev.selfEvaluation || '').replace(original, suggested) }
  }
  if (key === 'skillContent') {
    return { ...prev, skillContent: (prev.skillContent || '').replace(original, suggested) }
  }
  if (key.startsWith('experience:')) {
    const id = key.slice('experience:'.length)
    return { ...prev, experience: prev.experience.map((e) => e.id === id ? { ...e, details: (e.details || '').replace(original, suggested) } : e) }
  }
  if (key.startsWith('project:')) {
    const id = key.slice('project:'.length)
    return { ...prev, projects: prev.projects.map((p) => p.id === id ? { ...p, description: (p.description || '').replace(original, suggested) } : p) }
  }
  if (key.startsWith('openSource:')) {
    const id = key.slice('openSource:'.length)
    return { ...prev, openSource: (prev.openSource || []).map((o) => o.id === id ? { ...o, description: (o.description || '').replace(original, suggested) } : o) }
  }
  return prev
}

const normalizeCustomItem = (item: Partial<CustomItem>): CustomItem => ({
  id: item.id || `custom_item_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  title: stripHtmlTags(item.title || ''),
  subtitle: stripHtmlTags(item.subtitle || ''),
  dateRange: item.dateRange || '',
  description: item.description || '',  // 富文本 HTML，保留
  visible: item.visible !== false,
})

const createEmptyCustomItem = (): CustomItem => ({
  id: `custom_item_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  title: '',
  subtitle: '',
  dateRange: '',
  description: '',
  visible: true,
})

const normalizeCustomData = (raw: unknown): Record<string, CustomItem[]> => {
  if (!raw || typeof raw !== 'object') return {}
  const entries = Object.entries(raw as Record<string, unknown>)
  return entries.reduce<Record<string, CustomItem[]>>((acc, [sectionId, items]) => {
    const list = Array.isArray(items) ? items : []
    acc[sectionId] = list
      .filter((item): item is Partial<CustomItem> => !!item && typeof item === 'object')
      .map(normalizeCustomItem)
    return acc
  }, {})
}

export function useResumeData() {
  const location = useLocation()
  const { resumeId: routeResumeId } = useParams()
  // 当前编辑的简历 ID
  const [currentResumeId, setCurrentId] = useState<string | null>(() => getCurrentResumeId())

  // 简历数据状态
  const [resumeData, setResumeDataLocal] = useState<ResumeData>(loadFromStorage)
  const [activeSection, setActiveSection] = useState('basic')

  // 数据是否已从后端加载完成
  const [isDataLoaded, setIsDataLoaded] = useState(false)

  // ResumeContext — Chat 更新简历时会设置 context.resume
  const { resume: contextResume, setResume: setContextResume } = useResumeContext()

  // 用 ref 跟踪上一次 contextResume 引用，避免循环更新
  const lastContextResumeRef = useRef<ResumeData | null>(null)

  // 当 context.resume 被 Chat 侧更新时，同步到本地编辑器状态
  useEffect(() => {
    if (contextResume && contextResume !== lastContextResumeRef.current) {
      lastContextResumeRef.current = contextResume
      setResumeDataLocal(contextResume)
    }
  }, [contextResume])

  // 包装 setResumeData：同时更新本地状态和 context，让 Chat 侧感知用户手动编辑
  const setResumeData = useCallback((updater: ResumeData | ((prev: ResumeData) => ResumeData)) => {
    setResumeDataLocal(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      // 记录此次由编辑器发起的更新，避免 context effect 反向触发
      lastContextResumeRef.current = next
      setContextResume(next)
      return next
    })
  }, [setContextResume])

  // 目标简历不存在时，把编辑器重置为空白默认模板并清掉全局草稿
  // （resume_v2_data 是编辑页私有的自动存草稿，活在存储适配器体系之外，
  // 删除简历不会清它；不重置就会显示一份数据库里已不存在的「幽灵简历」，
  // 见 knowledge-base/reviews/2026-07-15-删简历后编辑页显示旧简历-根因与方案.md）
  const resetEditorToBlank = useCallback((requestedTemplate?: string | null) => {
    setCurrentResumeId(null)
    setCurrentId(null)
    localStorage.removeItem(STORAGE_KEY)
    const fresh = loadFromStorage()
    setResumeData(requestedTemplate ? applyRequestedTemplate(fresh, requestedTemplate) : fresh)
  }, [setResumeData])

  // 从 Dashboard 进入时加载对应简历
  useEffect(() => {
    const loadResume = async () => {
      // /workspace/new 始终按“新建默认模板”处理，支持通过 ?template= 指定模板
      if (location.pathname === '/workspace/new' && !routeResumeId) {
        const requestedTemplate = new URLSearchParams(location.search).get('template')
        resetEditorToBlank(requestedTemplate)
        setIsDataLoaded(true)
        return
      }

      const id = routeResumeId || getCurrentResumeId()
      if (!id) {
        // 无任何目标简历（裸 /workspace 且无 current）：重置空白，不沿用旧草稿
        resetEditorToBlank()
        setIsDataLoaded(true)
        return
      }
      // 当路由显式携带 resumeId 时，同步到 currentResumeId，保证后续保存覆盖正确记录
      if (routeResumeId) {
        setCurrentResumeId(routeResumeId)
      }
      const saved = await getResume(id)
      if (saved && saved.data) {
        const data = saved.data as any
        const nextMenuSections = Array.isArray(data.menuSections)
          ? (
              isLegacyDefaultMenuOrder(data.menuSections)
                ? migrateMenuSectionsToLatestDefault(data.menuSections)
                : mergeMissingDefaultModules(data.menuSections)
            )
          : undefined
        setResumeData(prev => ({
          ...prev,
          basic: { ...prev.basic, ...(data.basic || {}), name: saved.name },
          education: data.education || prev.education,
          workExperience: data.workExperience || prev.workExperience,
          experience: data.experience || prev.experience,
          projects: data.projects || prev.projects,
          openSource: data.openSource || prev.openSource,  // 加载开源经历
          awards: data.awards || prev.awards,  // 加载荣誉奖项
          selfEvaluation: typeof data.selfEvaluation === 'string'
            ? data.selfEvaluation
            : (typeof data.summary === 'string' ? `<p>${data.summary}</p>` : prev.selfEvaluation),
          skillContent: data.skillContent || prev.skillContent,  // 加载技能内容
          menuSections: nextMenuSections || prev.menuSections,  // 加载菜单配置
          globalSettings: data.globalSettings ? { ...prev.globalSettings, ...data.globalSettings } : prev.globalSettings,  // 加载全局设置
          customData: data.customData !== undefined
            ? normalizeCustomData(data.customData)
            : prev.customData,  // 加载自定义数据
          templateType: data.templateType || prev.templateType,  // 保留模板类型
          templateId: data.templateId || prev.templateId,  // 保留模板 ID
        }))
        setCurrentId(id)
      } else {
        // 有 id 但简历查不到（已删除 / 不存在）：不沿用旧草稿，重置为空白，
        // 避免显示「幽灵简历」；清掉悬挂的 current id，后续保存走新建。
        resetEditorToBlank()
      }
      // 标记数据已加载完成
      setIsDataLoaded(true)
    }

    loadResume()
  }, [location.pathname, location.search, routeResumeId, resetEditorToBlank])

  // 自动保存到 localStorage
  useEffect(() => {
    const saveData = {
      ...stripPhotoFromResumeData(resumeData),
      updatedAt: new Date().toISOString(),
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saveData))
  }, [resumeData])

  // ============ 基本信息 ============
  const updateBasicInfo = useCallback((data: Partial<BasicInfo>) => {
    setResumeData((prev) => ({
      ...prev,
      basic: { ...prev.basic, ...data },
    }))
  }, [])

  // ============ 项目经历 ============
  const updateProject = useCallback((project: Project) => {
    setResumeData((prev) => ({
      ...prev,
      projects: prev.projects.map((p) => (p.id === project.id ? project : p)),
    }))
  }, [])

  const deleteProject = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      projects: prev.projects.filter((p) => p.id !== id),
    }))
  }, [])

  const reorderProjects = useCallback((projects: Project[]) => {
    setResumeData((prev) => ({ ...prev, projects }))
  }, [])

  // ============ 工作经历 ============
  const updateWorkExperience = useCallback((experience: Experience) => {
    setResumeData((prev) => {
      const list = prev.workExperience || []
      const exists = list.some((e) => e.id === experience.id)
      return {
        ...prev,
        workExperience: exists
          ? list.map((e) => (e.id === experience.id ? experience : e))
          : [...list, experience],
      }
    })
  }, [])

  const deleteWorkExperience = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      workExperience: (prev.workExperience || []).filter((e) => e.id !== id),
    }))
  }, [])

  const reorderWorkExperiences = useCallback((experiences: Experience[]) => {
    setResumeData((prev) => ({ ...prev, workExperience: experiences }))
  }, [])

  // ============ 实习经历 ============
  const updateExperience = useCallback((experience: Experience) => {
    setResumeData((prev) => ({
      ...prev,
      experience: prev.experience.map((e) =>
        e.id === experience.id ? experience : e
      ),
    }))
  }, [])

  const deleteExperience = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      experience: prev.experience.filter((e) => e.id !== id),
    }))
  }, [])

  const reorderExperiences = useCallback((experiences: Experience[]) => {
    setResumeData((prev) => ({ ...prev, experience: experiences }))
  }, [])

  // ============ 教育经历 ============
  const updateEducation = useCallback((education: Education) => {
    setResumeData((prev) => ({
      ...prev,
      education: prev.education.map((e) =>
        e.id === education.id ? education : e
      ),
    }))
  }, [])

  const deleteEducation = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      education: prev.education.filter((e) => e.id !== id),
    }))
  }, [])

  const reorderEducations = useCallback((educations: Education[]) => {
    setResumeData((prev) => ({ ...prev, education: educations }))
  }, [])

  // ============ 开源经历 ============
  const updateOpenSource = useCallback((openSource: OpenSource) => {
    setResumeData((prev) => ({
      ...prev,
      openSource: prev.openSource.map((o) =>
        o.id === openSource.id ? openSource : o
      ),
    }))
  }, [])

  const deleteOpenSource = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      openSource: prev.openSource.filter((o) => o.id !== id),
    }))
  }, [])

  const reorderOpenSources = useCallback((openSources: OpenSource[]) => {
    setResumeData((prev) => ({ ...prev, openSource: openSources }))
  }, [])

  // ============ 荣誉奖项 ============
  const updateAward = useCallback((award: Award) => {
    setResumeData((prev) => ({
      ...prev,
      awards: prev.awards.map((a) =>
        a.id === award.id ? award : a
      ),
    }))
  }, [])

  const deleteAward = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      awards: prev.awards.filter((a) => a.id !== id),
    }))
  }, [])

  const reorderAwards = useCallback((awards: Award[]) => {
    setResumeData((prev) => ({ ...prev, awards }))
  }, [])

  // ============ 技能 ============
  const updateSelfEvaluation = useCallback((content: string) => {
    setResumeData((prev) => ({ ...prev, selfEvaluation: content }))
  }, [])

  const updateSkillContent = useCallback((content: string) => {
    setResumeData((prev) => ({ ...prev, skillContent: content }))
  }, [])

  // 按字段 key 做一次确定性文本替换（供 JD 优化「应用」使用）。
  // 用函数式更新，保证对同一字段连续多次替换（一键全部应用）能正确链式叠加。
  const applyTextReplacement = useCallback((key: string, original: string, suggested: string) => {
    if (!original || original === suggested) return
    setResumeData((prev) => replaceInResume(prev, key, original, suggested))
  }, [])

  /** 批量替换：一次 setResumeData 应用所有条目，避免循环多次 setState 引发重复渲染 / React 警告 */
  const applyTextReplacements = useCallback((items: { key: string; original: string; suggested: string }[]) => {
    const valid = items.filter((it) => it.original && it.original !== it.suggested)
    if (valid.length === 0) return
    setResumeData((prev) => valid.reduce((acc, it) => replaceInResume(acc, it.key, it.original, it.suggested), prev))
  }, [])

  // ============ 菜单/布局 ============
  const updateMenuSections = useCallback((sections: MenuSection[]) => {
    const sectionIds = new Set(sections.map((s) => s.id))
    setResumeData((prev) => {
      const cleanedCustomData = Object.entries(prev.customData || {}).reduce<Record<string, CustomItem[]>>(
        (acc, [sectionId, items]) => {
          if (sectionIds.has(sectionId)) acc[sectionId] = items
          return acc
        },
        {}
      )
      return { ...prev, menuSections: sections, customData: cleanedCustomData }
    })
  }, [])

  const reorderSections = useCallback((sections: MenuSection[]) => {
    const updatedSections = sections.map((s, index) => ({ ...s, order: index }))
    setResumeData((prev) => ({ ...prev, menuSections: updatedSections }))
  }, [])

  const toggleSectionVisibility = useCallback((id: string) => {
    setResumeData((prev) => ({
      ...prev,
      menuSections: prev.menuSections.map((s) =>
        s.id === id ? { ...s, enabled: !s.enabled } : s
      ),
    }))
  }, [])

  // ============ 全局设置 ============
  const updateGlobalSettings = useCallback((settings: Partial<GlobalSettings>) => {
    setResumeData((prev) => ({
      ...prev,
      globalSettings: { ...prev.globalSettings, ...settings },
    }))
  }, [])

  // ============ 自定义模块 ============
  const addCustomSection = useCallback(() => {
    const customId = `custom_${Date.now()}`
    const newSection: MenuSection = {
      id: customId,
      title: '自定义模块',
      icon: '📝',
      enabled: true,
      order: resumeData.menuSections.length,
    }
    setResumeData((prev) => ({
      ...prev,
      menuSections: [...prev.menuSections, newSection],
      customData: { ...prev.customData, [customId]: [createEmptyCustomItem()] },
    }))
  }, [resumeData.menuSections.length])

  const addCustomItem = useCallback((sectionId: string) => {
    setResumeData((prev) => {
      const items = prev.customData[sectionId] || []
      return {
        ...prev,
        customData: {
          ...prev.customData,
          [sectionId]: [...items, createEmptyCustomItem()],
        },
      }
    })
  }, [])

  const updateCustomItem = useCallback((sectionId: string, item: CustomItem) => {
    setResumeData((prev) => {
      const items = prev.customData[sectionId] || []
      return {
        ...prev,
        customData: {
          ...prev.customData,
          [sectionId]: items.map((it) => (it.id === item.id ? normalizeCustomItem(item) : it)),
        },
      }
    })
  }, [])

  const deleteCustomItem = useCallback((sectionId: string, itemId: string) => {
    setResumeData((prev) => {
      const items = prev.customData[sectionId] || []
      return {
        ...prev,
        customData: {
          ...prev.customData,
          [sectionId]: items.filter((it) => it.id !== itemId),
        },
      }
    })
  }, [])

  const reorderCustomItems = useCallback((sectionId: string, items: CustomItem[]) => {
    setResumeData((prev) => ({
      ...prev,
      customData: {
        ...prev.customData,
        [sectionId]: items,
      },
    }))
  }, [])

  return {
    resumeData,
    setResumeData,
    activeSection,
    setActiveSection,
    currentResumeId,
    setCurrentId,
    isDataLoaded,  // 数据是否已加载完成
    // 基本信息
    updateBasicInfo,
    // 项目
    updateProject,
    deleteProject,
    reorderProjects,
    // 工作经历
    updateWorkExperience,
    deleteWorkExperience,
    reorderWorkExperiences,
    // 实习经历
    updateExperience,
    deleteExperience,
    reorderExperiences,
    // 教育
    updateEducation,
    deleteEducation,
    reorderEducations,
    // 开源
    updateOpenSource,
    deleteOpenSource,
    reorderOpenSources,
    // 奖项
    updateAward,
    deleteAward,
    reorderAwards,
    // 技能
    updateSelfEvaluation,
    updateSkillContent,
    // JD 优化逐条/批量应用
    applyTextReplacement,
    applyTextReplacements,
    // 菜单
    updateMenuSections,
    reorderSections,
    toggleSectionVisibility,
    // 设置
    updateGlobalSettings,
    addCustomSection,
    addCustomItem,
    updateCustomItem,
    deleteCustomItem,
    reorderCustomItems,
  }
}
