/**
 * Builder 页面数据类型 —— 移植自 Resume-Matcher 的 ResumeData 形状,
 * 并按我方简历模型扩展(openSource/skills/awards 一等 section)。
 * 来源:reference/projects/Resume-Matcher apps/frontend/components/dashboard/resume-component.tsx
 */

export interface PersonalInfo {
  name?: string
  title?: string
  email?: string
  phone?: string
  location?: string
  website?: string
  linkedin?: string
  github?: string
  /** 用户上传的照片 URL（COS）。模板按需渲染，无则不显示 */
  photo?: string
}

export interface Experience {
  id: number
  title?: string
  company?: string
  location?: string
  years?: string
  /** 公司 Logo URL（adapter 用 getLogoUrl 把 companyLogo key 解析后传入，无则不渲染） */
  companyLogoUrl?: string
  /** 公司 Logo 尺寸(px)，条目优先，缺省取全局 companyLogoSize */
  companyLogoSize?: number
  /** 每条 bullet 是一段行内 HTML(strong/em/u/a),由 SafeHtml 渲染 */
  description?: string[]
}

export interface Education {
  id: number
  institution?: string
  degree?: string
  years?: string
  /** 学校 Logo URL（adapter 用 getSchoolLogoUrl 把 schoolLogo key 解析后传入，无则不渲染） */
  schoolLogoUrl?: string
  /** 学校 Logo 尺寸(px)，条目优先，缺省取全局 companyLogoSize */
  schoolLogoSize?: number
  /** 与 RM 不同:改为 bullets(我方教育描述是富文本列表) */
  description?: string[]
}

export interface Project {
  id: number
  name?: string
  role?: string
  years?: string
  github?: string
  website?: string
  description?: string[]
}

// Section Type for dynamic sections
export type SectionType = 'personalInfo' | 'text' | 'itemList' | 'stringList'

// Section Metadata for dynamic section management
export interface SectionMeta {
  id: string
  key: string
  displayName: string
  sectionType: SectionType
  isDefault: boolean
  isVisible: boolean
  order: number
}

// Generic item for custom item-based sections
export interface CustomSectionItem {
  id: number
  title?: string
  subtitle?: string
  location?: string
  years?: string
  description?: string[]
}

// Custom section data container
export interface CustomSection {
  sectionType: SectionType
  items?: CustomSectionItem[]
  strings?: string[]
  text?: string
}

export interface BuilderResumeData {
  personalInfo?: PersonalInfo
  /** 自我评价:1 条渲染为正文段,多条渲染为 bullets */
  summary?: string[]
  workExperience?: Experience[]
  education?: Education[]
  personalProjects?: Project[]
  /** 开源经历:独立 section,各模板复用 projects 的渲染语言(repo → github pill) */
  openSource?: Project[]
  /** 专业技能:句子型 bullets */
  skills?: string[]
  /** 荣誉奖项:bullets(行内 HTML) */
  awards?: string[]
  sectionMeta?: SectionMeta[]
  customSections?: Record<string, CustomSection>
}

/**
 * 无 sectionMeta 时的默认顺序(与 RM DEFAULT_SECTION_META 同构,按我方模块扩展)
 */
export const DEFAULT_SECTION_META: SectionMeta[] = [
  { id: 'personalInfo', key: 'personalInfo', displayName: '基本信息', sectionType: 'personalInfo', isDefault: true, isVisible: true, order: 0 },
  { id: 'education', key: 'education', displayName: '教育经历', sectionType: 'itemList', isDefault: true, isVisible: true, order: 1 },
  { id: 'workExperience', key: 'workExperience', displayName: '实习经历', sectionType: 'itemList', isDefault: true, isVisible: true, order: 2 },
  { id: 'personalProjects', key: 'personalProjects', displayName: '项目经历', sectionType: 'itemList', isDefault: true, isVisible: true, order: 3 },
  { id: 'openSource', key: 'openSource', displayName: '开源经历', sectionType: 'itemList', isDefault: true, isVisible: true, order: 4 },
  { id: 'skills', key: 'skills', displayName: '专业技能', sectionType: 'stringList', isDefault: true, isVisible: true, order: 5 },
  { id: 'awards', key: 'awards', displayName: '荣誉奖项', sectionType: 'stringList', isDefault: true, isVisible: true, order: 6 },
  { id: 'summary', key: 'summary', displayName: '自我评价', sectionType: 'text', isDefault: true, isVisible: true, order: 7 },
]

/**
 * Get sorted sections (visible only) for rendering.
 * 移植自 RM lib/utils/section-helpers.ts
 */
export function getSortedSections(resumeData: BuilderResumeData): SectionMeta[] {
  const meta = resumeData.sectionMeta?.length ? resumeData.sectionMeta : DEFAULT_SECTION_META
  return [...meta].filter((s) => s.isVisible).sort((a, b) => a.order - b.order)
}

/**
 * Normalize date-range separators for consistent display.
 * 移植自 RM lib/utils.ts formatDateRange
 */
export function formatDateRange(dateString: string | undefined | null): string {
  if (!dateString || typeof dateString !== 'string') return ''

  // Normalize any existing dashes (en-dash, em-dash) to hyphen-minus for ATS compatibility
  let formatted = dateString.replace(/[–—]/g, '-')

  // Normalize spacing around existing hyphens
  formatted = formatted.replace(/\s*-\s*/g, ' - ')

  // Handle "Jun 2025 Aug 2025" pattern (month year month year without separator)
  formatted = formatted.replace(/([A-Za-z]+\.?\s+\d{4})\s+([A-Za-z]+\.?\s+\d{4})/g, '$1 - $2')

  // Handle "2023 2025" pattern (year year without separator)
  formatted = formatted.replace(/(\d{4})\s+(\d{4})/g, '$1 - $2')

  // Handle "Jun 2025 Present" pattern
  formatted = formatted.replace(
    /([A-Za-z]+\.?\s+\d{4})\s+(Present|Current|Now|Ongoing)/gi,
    '$1 - $2'
  )

  return formatted
}
