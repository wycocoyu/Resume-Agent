/**
 * 数据适配层:我方 Workspace v2 ResumeData → BuilderResumeData(RM 模板消费的形状)。
 *
 * 富文本策略:v2 的描述字段是 TipTap HTML(<ul><li><p>…),模板以 bullets(行内 HTML)渲染,
 * 这里用 DOMParser 把块级结构拍平成 bullet 数组,行内 strong/em/u/a 原样保留(渲染时由 SafeHtml 白名单清洗)。
 */
import type { ResumeData } from '../Workspace/v2/types'
import { DEFAULT_MENU_SECTIONS } from '../Workspace/v2/types'
import type {
  BuilderResumeData,
  CustomSection,
  Education,
  Experience,
  PersonalInfo,
  Project,
  SectionMeta,
  SectionType,
} from './types'
import { escapeText, inlineNodeHtml } from './templates/sanitizeHtml'
import { getLogoUrl } from '../Workspace/v2/constants/companyLogos'
import { getSchoolLogoUrl } from '../Workspace/v2/constants/schoolLogos'

const DEFAULT_LOGO_SIZE = 20  // 与 globalSettings.companyLogoSize 默认一致

function collectListItem(liEl: Element, depth: number, out: string[]): void {
  const indent = '  '.repeat(depth)
  const inlineParts: string[] = []
  for (const node of Array.from(liEl.childNodes)) {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const tag = (node as Element).tagName
      if (tag === 'UL' || tag === 'OL') continue
    }
    inlineParts.push(inlineNodeHtml(node))
  }
  const text = inlineParts.join('').trim()
  if (text) {
    out.push(`${indent}${text}`)
  }
  for (const child of Array.from(liEl.children)) {
    if (child.tagName === 'UL' || child.tagName === 'OL') {
      collectNestedListBullets(child, depth + 1, out)
    }
  }
}

function collectNestedListBullets(listEl: Element, depth: number, out: string[]): void {
  for (const child of Array.from(listEl.children)) {
    if (child.tagName === 'LI') {
      collectListItem(child, depth, out)
    }
  }
}

/**
 * TipTap HTML → bullet 数组。
 * 递归提取嵌套 <ul>/<ol>/<li>（按缩进深度保留 `'  '` 前缀），避免外层 <li> 吞并内层列表导致重复；
 * 无列表时按块级 <p> 分段，再退化为整体一条。
 */
export function htmlToBullets(html: string | undefined | null): string[] {
  if (!html || !html.trim()) return []
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const bullets: string[] = []
  const topChildren = Array.from(doc.body.children)
  if (topChildren.length === 0) {
    const raw = Array.from(doc.body.childNodes).map(inlineNodeHtml).join('').trim()
    return raw ? [raw] : []
  }
  for (const child of topChildren) {
    if (child.tagName === 'UL' || child.tagName === 'OL') {
      collectNestedListBullets(child, 0, bullets)
    } else if (child.tagName === 'LI') {
      collectListItem(child, 0, bullets)
    } else {
      const nestedLists = Array.from(child.children).filter(
        (el) => el.tagName === 'UL' || el.tagName === 'OL',
      )
      if (nestedLists.length > 0) {
        const inlineText = Array.from(child.childNodes)
          .filter((n) => !(n.nodeType === Node.ELEMENT_NODE && ['UL', 'OL'].includes((n as Element).tagName)))
          .map(inlineNodeHtml)
          .join('')
          .trim()
        if (inlineText) bullets.push(inlineText)
        for (const nl of nestedLists) {
          collectNestedListBullets(nl, 1, bullets)
        }
      } else {
        const text = inlineNodeHtml(child).trim()
        if (text) bullets.push(text)
      }
    }
  }
  return bullets
}

/** 我方 menuSections id → Builder section 定义 */
const SECTION_KEY_MAP: Record<string, { key: string; sectionType: SectionType }> = {
  basic: { key: 'personalInfo', sectionType: 'personalInfo' },
  education: { key: 'education', sectionType: 'itemList' },
  workExperience: { key: 'fullTimeExperience', sectionType: 'itemList' },
  experience: { key: 'workExperience', sectionType: 'itemList' },
  projects: { key: 'personalProjects', sectionType: 'itemList' },
  openSource: { key: 'openSource', sectionType: 'itemList' },
  skills: { key: 'skills', sectionType: 'stringList' },
  awards: { key: 'awards', sectionType: 'stringList' },
  selfEvaluation: { key: 'summary', sectionType: 'text' },
}

function toPersonalInfo(data: ResumeData): PersonalInfo {
  const { basic } = data
  const blog = basic.blog?.trim()
  const isGithub = Boolean(blog && /github\.com/i.test(blog))
  return {
    name: basic.name || undefined,
    title: basic.title || undefined,
    email: basic.email || undefined,
    phone: basic.phone || undefined,
    location: basic.location || undefined,
    github: isGithub ? blog : undefined,
    website: !isGithub && blog ? blog : undefined,
    photo: basic.photo || undefined,
  }
}

function mapExperienceItems(
  items: ResumeData['experience'] | undefined,
  globalLogoSize: number,
  idOffset = 0
): Experience[] {
  return (items || [])
    .filter((item) => item.visible !== false)
    .map((item) => ({
      item,
      description: htmlToBullets(item.details),
    }))
    .filter(({ item, description }) =>
      Boolean(item.company?.trim() || item.position?.trim() || description.length > 0)
    )
    .map(({ item, description }, index) => ({
      id: idOffset + index,
      company: item.company || undefined,
      title: item.position || undefined,
      years: item.date || undefined,
      description,
      // Logo key → COS URL（未设 / 未加载则 undefined，模板条件渲染不出图，不报错）
      companyLogoUrl: item.companyLogo ? getLogoUrl(item.companyLogo) || undefined : undefined,
      companyLogoSize: item.companyLogoSize ?? globalLogoSize,
    }))
}

function toFullTimeExperience(data: ResumeData): Experience[] {
  const globalLogoSize = data.globalSettings?.companyLogoSize ?? DEFAULT_LOGO_SIZE
  return mapExperienceItems(data.workExperience, globalLogoSize, 0)
}

function toInternships(data: ResumeData): Experience[] {
  const globalLogoSize = data.globalSettings?.companyLogoSize ?? DEFAULT_LOGO_SIZE
  const fullTimeCount = (data.workExperience || []).length
  return mapExperienceItems(data.experience, globalLogoSize, fullTimeCount)
}

function toWorkExperience(data: ResumeData): Experience[] {
  return [...toFullTimeExperience(data), ...toInternships(data)]
}

function toEducation(data: ResumeData): Education[] {
  const globalLogoSize = data.globalSettings?.companyLogoSize ?? DEFAULT_LOGO_SIZE
  return data.education
    .filter((item) => item.visible !== false)
    .map((item, index): Education | null => {
      const degreeLine = [item.degree, item.major].filter(Boolean).join(' · ')
      const withGpa = item.gpa ? `${degreeLine} · GPA ${item.gpa}` : degreeLine
      const years = [item.startDate, item.endDate].filter(Boolean).join(' - ')
      const institution = item.school?.trim() || undefined
      const degree = withGpa?.trim() || undefined
      const description = htmlToBullets(item.description)
      if (!institution && !degree && description.length === 0) {
        return null
      }
      return {
        id: index,
        institution,
        degree,
        years: years || undefined,
        description,
        // Logo key → COS URL（未设 / 未加载则 undefined）
        schoolLogoUrl: item.schoolLogo ? getSchoolLogoUrl(item.schoolLogo) || undefined : undefined,
        schoolLogoSize: item.schoolLogoSize ?? globalLogoSize,
      }
    })
    .filter((edu): edu is Education => edu !== null)
}

function toProjects(data: ResumeData): Project[] {
  return data.projects
    .filter((item) => item.visible !== false)
    .map((item, index) => ({
      id: index,
      name: item.name || undefined,
      role: item.role || undefined,
      years: item.date || undefined,
      website: item.link || undefined,
      description: htmlToBullets(item.description),
    }))
}

function toOpenSource(data: ResumeData): Project[] {
  return data.openSource
    .filter((item) => item.visible !== false)
    .map((item, index) => ({
      id: index,
      name: item.name || undefined,
      role: item.role || undefined,
      years: item.date || undefined,
      github: item.repo || undefined,
      description: htmlToBullets(item.description),
    }))
}

function toAwards(data: ResumeData): string[] {
  return data.awards
    .filter((item) => item.visible !== false)
    .map((item) => {
      const head = [
        item.title ? `<strong>${escapeText(item.title)}</strong>` : '',
        item.issuer ? escapeText(item.issuer) : '',
        item.date ? escapeText(item.date) : '',
      ]
        .filter(Boolean)
        .join(' · ')
      const tail = item.description?.trim() ? `:${escapeText(item.description.trim())}` : ''
      return `${head}${tail}`
    })
    .filter(Boolean)
}

function toCustomSections(data: ResumeData): Record<string, CustomSection> {
  const result: Record<string, CustomSection> = {}
  for (const [key, items] of Object.entries(data.customData || {})) {
    if (!Array.isArray(items) || items.length === 0) continue
    result[key] = {
      sectionType: 'itemList',
      items: items
        .filter((item) => item.visible !== false)
        .map((item, index) => ({
          id: index,
          title: item.title || undefined,
          subtitle: item.subtitle || undefined,
          years: item.dateRange || undefined,
          description: htmlToBullets(item.description),
        })),
    }
  }
  return result
}

function toSectionMeta(data: ResumeData): SectionMeta[] | undefined {
  if (!Array.isArray(data.menuSections) || data.menuSections.length === 0) return undefined
  return data.menuSections.map((section) => {
    const mapped = SECTION_KEY_MAP[section.id]
    if (mapped) {
      return {
        id: section.id,
        key: mapped.key,
        displayName: section.title,
        sectionType: mapped.sectionType,
        isDefault: true,
        isVisible: section.enabled,
        order: section.order,
      }
    }
    // 自定义模块(如 custom_research 竞赛科研)
    return {
      id: section.id,
      key: section.id,
      displayName: section.title,
      sectionType: 'itemList' as SectionType,
      isDefault: false,
      isVisible: section.enabled,
      order: section.order,
    }
  })
}

/** 我方 v2 ResumeData → Builder 数据 */
export function toBuilderResumeData(data: ResumeData): BuilderResumeData {
  return {
    personalInfo: toPersonalInfo(data),
    summary: htmlToBullets(data.selfEvaluation),
    workExperience: toWorkExperience(data),
    fullTimeExperience: toFullTimeExperience(data),
    internships: toInternships(data),
    education: toEducation(data),
    personalProjects: toProjects(data),
    openSource: toOpenSource(data),
    skills: htmlToBullets(data.skillContent),
    awards: toAwards(data),
    customSections: toCustomSections(data),
    sectionMeta: toSectionMeta(data),
  }
}

/**
 * 存储边界的字段级默认合并:未知字段原样保留(templateType/alias/照片等,写回不丢),
 * 缺失字段补默认,menuSections 缺失时种默认模块(编辑区依赖)。
 */
export function normalizeResumeData(raw: unknown): ResumeData {
  const data = (raw && typeof raw === 'object' ? raw : {}) as Partial<ResumeData> &
    Record<string, unknown>
  return {
    ...data,
    id: data.id || '',
    title: data.title || '',
    createdAt: data.createdAt || '',
    updatedAt: data.updatedAt || '',
    templateId: data.templateId ?? null,
    basic: {
      name: '',
      title: '',
      email: '',
      phone: '',
      location: '',
      ...(data.basic || {}),
    },
    education: Array.isArray(data.education) ? data.education : [],
    workExperience: Array.isArray(data.workExperience) ? data.workExperience : [],
    experience: Array.isArray(data.experience) ? data.experience : [],
    projects: Array.isArray(data.projects) ? data.projects : [],
    openSource: Array.isArray(data.openSource) ? data.openSource : [],
    awards: Array.isArray(data.awards) ? data.awards : [],
    customData: data.customData && typeof data.customData === 'object' ? data.customData : {},
    selfEvaluation: typeof data.selfEvaluation === 'string' ? data.selfEvaluation : '',
    skillContent: typeof data.skillContent === 'string' ? data.skillContent : '',
    activeSection: data.activeSection || 'basic',
    draggingProjectId: null,
    menuSections:
      Array.isArray(data.menuSections) && data.menuSections.length > 0
        ? data.menuSections
        : DEFAULT_MENU_SECTIONS.map((section) => ({ ...section })),
    globalSettings: data.globalSettings || {},
  }
}

/** 无简历可载入时的示例数据(v2 形状,可在编辑区体验编辑;不落任何存储) */
export function buildSampleResumeData(): ResumeData {
  return normalizeResumeData({
    basic: {
      name: '王小明',
      title: '后端开发工程师',
      email: 'xiaoming@example.com',
      phone: '138 0000 0000',
      location: '',
      blog: 'github.com/xiaoming',
    },
    education: [
      {
        id: 'sample-edu-1',
        school: '示例大学',
        degree: '本科',
        major: '计算机科学与技术',
        startDate: '2021.09',
        endDate: '2025.06',
        description: '<ul><li><p>主修课程:数据结构、操作系统、计算机网络、数据库系统</p></li></ul>',
      },
    ],
    experience: [
      {
        id: 'sample-exp-1',
        company: '示例科技',
        position: '后端开发实习生',
        date: '2024.06 - 2024.09',
        details:
          '<ul><li><p>参与订单服务拆分,接口 P99 延迟从 <strong>320ms 降至 90ms</strong></p></li><li><p>搭建灰度发布流程,线上事故率下降 60%</p></li></ul>',
      },
    ],
    projects: [
      {
        id: 'sample-proj-1',
        name: '短链服务',
        role: '独立开发',
        date: '2024.03 - 2024.05',
        link: 'github.com/xiaoming/shortlink',
        visible: true,
        description: '<ul><li><p>基于一致性哈希的分布式短链生成,支持 1w QPS</p></li></ul>',
      },
    ],
    skillContent:
      '<ul><li><p>熟悉 Java 并发编程与 JVM 调优</p></li><li><p>熟悉 MySQL 索引与事务,了解分库分表</p></li></ul>',
    awards: [{ id: 'sample-award-1', title: '国家奖学金', date: '2023' }],
  })
}
