/**
 * 生成自包含、零网络依赖、行内可编辑的 HTML 简历导出文件
 * 规范实现：Issue #46 (Feature 12 & Feature 13)
 */
import type { ResumeData } from '../types'
import { getLogoUrl } from '../constants/companyLogos'
import { getSchoolLogoUrl } from '../constants/schoolLogos'
import { formatBirthDateForHeader, resolveEmploymentStatusForRender } from './birthDateDisplay'
import { stripHtmlTags } from './textUtils'

export interface GenerateHTMLOptions {
  editable?: boolean // 默认 true: 注入 contenteditable 与本地编辑工具栏
  autoOnePage?: boolean // 默认 true: 加载后自动尝试 3-Tier 一页自适应
  themeColor?: string // 主题色覆盖 (默认 #2563eb)
}

function escapeHtml(text?: string | null): string {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

const ALLOWED_RICH_TAGS = new Set(['b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'p', 'br'])

/**
 * 针对简历中富文本字段进行 XSS 白名单清洗
 * 仅允许 <b>, <strong>, <i>, <em>, <u>, <ul>, <ol>, <li>, <p>, <br>，剔除所有危险标签与事件属性
 */
export function sanitizeRichText(html?: string | null): string {
  if (!html) return ''

  if (typeof DOMParser !== 'undefined') {
    try {
      const doc = new DOMParser().parseFromString(html, 'text/html')
      const DANGEROUS_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'NOSCRIPT', 'SVG'])
      const sanitizeNode = (node: Node): string => {
        if (node.nodeType === Node.TEXT_NODE) {
          return escapeHtml(node.textContent || '')
        }
        if (node.nodeType !== Node.ELEMENT_NODE) {
          return ''
        }
        const el = node as HTMLElement
        const tagName = el.tagName.toUpperCase()
        if (DANGEROUS_TAGS.has(tagName)) {
          return ''
        }
        const lower = tagName.toLowerCase()
        const inner = Array.from(el.childNodes).map(sanitizeNode).join('')
        if (ALLOWED_RICH_TAGS.has(lower)) {
          if (lower === 'br') return '<br />'
          return `<${lower}>${inner}</${lower}>`
        }
        return inner
      }
      return Array.from(doc.body.childNodes).map(sanitizeNode).join('')
    } catch {
      // 降级使用正则清洗
    }
  }

  // 针对无 DOMParser 环境（如 Node.js）的确定性正则清洗
  let clean = String(html)
  // 彻底移除高危块级容器标签及其内容
  clean = clean.replace(/<\s*(script|style|iframe|object|embed|noscript)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, '')
  clean = clean.replace(/<\s*(script|style|iframe|object|embed|noscript)\b[^>]*\/?>/gi, '')
  // 移除所有内联事件处理器
  clean = clean.replace(/\son\w+\s*=\s*(?:'[^']*'|"[^"]*"|[^\s>]+)/gi, '')
  // 移除 javascript: 伪协议
  clean = clean.replace(/javascript:[^"'>\s]*/gi, '')

  // 仅保留白名单标签并丢弃标签上的所有属性
  clean = clean.replace(/<\/?([a-zA-Z0-9]+)\b[^>]*>/gi, (match, tag) => {
    const lower = tag.toLowerCase()
    if (ALLOWED_RICH_TAGS.has(lower)) {
      if (lower === 'br') return '<br />'
      return match.startsWith('</') ? `</${lower}>` : `<${lower}>`
    }
    return ''
  })

  return clean
}

/**
 * 校验 URL 仅允许 http:// 或 https:// 协议，拦截 javascript: 等高危伪协议
 */
export function isValidHttpUrl(url?: string | null): boolean {
  if (!url) return false
  const trimmed = url.trim()
  return /^https?:\/\//i.test(trimmed)
}

/**
 * 格式化并安全转义 CSS 字体列表，确保含有空格与特殊字符的字体名称带英文双引号
 */
export function formatFontFamily(customFont?: string): string {
  const defaultFonts = [
    '-apple-system',
    'BlinkMacSystemFont',
    '"Segoe UI"',
    'Roboto',
    '"PingFang SC"',
    '"Microsoft YaHei"',
    '"Helvetica Neue"',
    'sans-serif',
  ]
  if (!customFont) {
    return defaultFonts.join(', ')
  }
  const cleanFont = customFont.trim()
  const quoted = (/[\s,]/.test(cleanFont) && !/^["'].*["']$/.test(cleanFont))
    ? `"${cleanFont}"`
    : cleanFont
  return [quoted, ...defaultFonts].join(', ')
}

// 内联标准矢量 SVG 图标，确保断网离线环境 100% 渲染
const SVG_ICONS = {
  phone: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>`,
  mail: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"></rect><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"></path></svg>`,
  mapPin: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path><circle cx="12" cy="10" r="3"></circle></svg>`,
  globe: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path></svg>`,
  github: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"></path><path d="M9 18c-4.51 2-5-2-7-2"></path></svg>`,
  edit: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"></path></svg>`,
  print: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"></path><rect x="6" y="14" width="12" height="8" rx="1"></rect></svg>`,
  fit: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" x2="21" y1="10" y2="3"></line><line x1="3" x2="10" y1="21" y2="14"></line></svg>`,
  reset: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path></svg>`,
  download: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" x2="12" y1="15" y2="3"></line></svg>`,
}

// 模块生成
function generateSectionHTML(
  section: { id: string; title: string },
  resumeData: ResumeData,
  editableAttr: string
): string {
  const { basic, experience, education, projects, openSource, awards, selfEvaluation, skillContent } = resumeData
  const sectionId = section.id
  const sectionTitle = section.title

  switch (sectionId) {
    case 'basic':
      return ''

    case 'skills':
      if (!skillContent) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content skill-content" ${editableAttr}>${sanitizeRichText(skillContent)}</div>
        </section>
      `

    case 'selfEvaluation':
      if (!selfEvaluation) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content self-evaluation" ${editableAttr}>${sanitizeRichText(selfEvaluation)}</div>
        </section>
      `

    case 'education':
      if (!education || education.length === 0) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content">
            ${education.map(edu => {
              const logoUrl = edu.schoolLogo ? getSchoolLogoUrl(edu.schoolLogo) : null
              const logoSize = edu.schoolLogoSize || 22
              const logoHtml = logoUrl
                ? `<img src="${escapeHtml(logoUrl)}" alt="" style="height:${logoSize}px;max-width:${logoSize * 3}px;object-fit:contain;flex-shrink:0" onerror="this.style.display='none'" />`
                : ''
              return `
                <div class="item education-item">
                  <div class="item-header">
                    <div class="item-title-group">
                      ${logoHtml}
                      <span class="item-title" ${editableAttr}>${escapeHtml(edu.school)}</span>
                      ${edu.major ? `<span class="item-subtitle" ${editableAttr}>${escapeHtml(edu.major)}</span>` : ''}
                      ${edu.degree ? `<span class="item-degree" ${editableAttr}>${escapeHtml(edu.degree)}</span>` : ''}
                    </div>
                    ${edu.startDate || edu.endDate ? `<span class="item-date" ${editableAttr}>${escapeHtml(edu.startDate)} - ${escapeHtml(edu.endDate)}</span>` : ''}
                  </div>
                  ${edu.description ? `<div class="item-description" ${editableAttr}>${sanitizeRichText(edu.description)}</div>` : ''}
                </div>
              `
            }).join('')}
          </div>
        </section>
      `

    case 'experience':
      if (!experience || experience.length === 0) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content">
            ${experience.map(exp => {
              const logoUrl = exp.companyLogo ? getLogoUrl(exp.companyLogo) : null
              const logoSize = exp.companyLogoSize || 22
              const logoHtml = logoUrl
                ? `<img src="${escapeHtml(logoUrl)}" alt="" style="height:${logoSize}px;max-width:${logoSize * 3}px;object-fit:contain;flex-shrink:0" onerror="this.style.display='none'" />`
                : ''
              return `
                <div class="item experience-item">
                  <div class="item-header">
                    <div class="item-title-group">
                      ${logoHtml}
                      <span class="item-title" ${editableAttr}>${escapeHtml(exp.company)}</span>
                      ${exp.position ? `<span class="item-subtitle" ${editableAttr}>${escapeHtml(exp.position)}</span>` : ''}
                      ${exp.department ? `<span class="item-dept" ${editableAttr}>${escapeHtml(exp.department)}</span>` : ''}
                    </div>
                    ${exp.startDate || exp.endDate ? `<span class="item-date" ${editableAttr}>${escapeHtml(exp.startDate)} - ${escapeHtml(exp.endDate)}</span>` : ''}
                  </div>
                  ${exp.description ? `<div class="item-description" ${editableAttr}>${sanitizeRichText(exp.description)}</div>` : ''}
                </div>
              `
            }).join('')}
          </div>
        </section>
      `

    case 'projects':
      if (!projects || projects.length === 0) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content">
            ${projects.map(proj => `
              <div class="item project-item">
                <div class="item-header">
                  <div class="item-title-group">
                    <span class="item-title" ${editableAttr}>${escapeHtml(proj.name)}</span>
                    ${proj.role ? `<span class="item-subtitle" ${editableAttr}>${escapeHtml(proj.role)}</span>` : ''}
                    ${proj.projectLink && isValidHttpUrl(proj.projectLink) ? `<a href="${escapeHtml(proj.projectLink.trim())}" target="_blank" rel="noopener noreferrer" class="item-link no-print">🔗 Link</a>` : ''}
                  </div>
                  ${proj.startDate || proj.endDate ? `<span class="item-date" ${editableAttr}>${escapeHtml(proj.startDate)} - ${escapeHtml(proj.endDate)}</span>` : ''}
                </div>
                ${proj.description ? `<div class="item-description" ${editableAttr}>${sanitizeRichText(proj.description)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        </section>
      `

    case 'openSource':
      if (!openSource || openSource.length === 0) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content">
            ${openSource.map(os => `
              <div class="item open-source-item">
                <div class="item-header">
                  <div class="item-title-group">
                    <span class="item-title" ${editableAttr}>${escapeHtml(os.project)}</span>
                    ${os.role ? `<span class="item-subtitle" ${editableAttr}>${escapeHtml(os.role)}</span>` : ''}
                    ${os.stars ? `<span class="item-stars">★ ${escapeHtml(String(os.stars))}</span>` : ''}
                  </div>
                  ${os.startDate || os.endDate ? `<span class="item-date" ${editableAttr}>${escapeHtml(os.startDate)} - ${escapeHtml(os.endDate)}</span>` : ''}
                </div>
                ${os.description ? `<div class="item-description" ${editableAttr}>${sanitizeRichText(os.description)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        </section>
      `

    case 'awards':
      if (!awards || awards.length === 0) return ''
      return `
        <section class="template-section">
          <h2 class="section-title" ${editableAttr}>${escapeHtml(sectionTitle)}</h2>
          <div class="section-content">
            ${awards.map(aw => `
              <div class="item award-item">
                <div class="item-header">
                  <span class="item-title" ${editableAttr}>${escapeHtml(aw.name)}</span>
                  ${aw.date ? `<span class="item-date" ${editableAttr}>${escapeHtml(aw.date)}</span>` : ''}
                </div>
                ${aw.description ? `<div class="item-description" ${editableAttr}>${sanitizeRichText(aw.description)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        </section>
      `

    default:
      return ''
  }
}

export function generateHTML(
  resumeData: ResumeData,
  templateId?: string,
  options?: GenerateHTMLOptions
): string {
  const isEditable = options?.editable ?? true
  const themeColor = options?.themeColor || '#2563eb'
  const editableAttr = isEditable ? 'contenteditable="true" spellcheck="false"' : ''
  const { basic, globalSettings, sectionOrder } = resumeData

  const activeSections = sectionOrder && sectionOrder.length > 0
    ? sectionOrder
    : [
        { id: 'education', title: '教育背景' },
        { id: 'experience', title: '工作经历' },
        { id: 'projects', title: '项目经历' },
        { id: 'openSource', title: '开源经历' },
        { id: 'skills', title: '专业技能' },
        { id: 'awards', title: '荣誉奖项' },
        { id: 'selfEvaluation', title: '自我评价' },
      ]

  const sectionsHtml = activeSections
    .map(sec => generateSectionHTML(sec, resumeData, editableAttr))
    .filter(Boolean)
    .join('\n')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(basic.name || '个人简历')} - 简历导出</title>
  <style>
    :root {
      --theme-color: ${themeColor};
      --section-gap: 16px;
      --item-gap: 10px;
      --page-padding: 32px;
      --line-height: 1.45;
      --list-item-gap: 3px;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: #f1f5f9;
      color: #1e293b;
      font-family: ${formatFontFamily(globalSettings?.fontFamily)};
      line-height: var(--line-height);
      padding: 24px 0 80px 0;
      -webkit-font-smoothing: antialiased;
    }

    /* 纸张容器 (标准 A4 比例) */
    .html-template-container {
      width: 100%;
      max-width: 210mm;
      min-height: 297mm;
      margin: 0 auto;
      background: #ffffff;
      padding: var(--page-padding);
      box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.1), 0 2px 6px -1px rgba(0, 0, 0, 0.06);
      border-radius: 4px;
      position: relative;
    }

    /* 个人基本信息 Header */
    .template-header {
      border-bottom: 2px solid var(--theme-color);
      padding-bottom: 12px;
      margin-bottom: var(--section-gap);
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
    }

    .header-left {
      flex: 1;
      min-width: 0;
    }

    .candidate-name {
      font-size: 24pt;
      font-weight: 700;
      line-height: 1.15;
      color: #0f172a;
      margin-bottom: 4px;
    }

    .candidate-title {
      font-size: 11pt;
      font-weight: 600;
      color: #475569;
      margin-bottom: 8px;
    }

    .contact-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px 12px;
      font-size: 9.5pt;
      color: #475569;
    }

    .contact-item {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .contact-item svg {
      color: var(--theme-color);
    }

    .photo-slot {
      width: 28mm;
      height: 36mm;
      border-radius: 4px;
      overflow: hidden;
      background: #f8fafc;
      flex-shrink: 0;
    }

    .photo-slot img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    /* 章节与条目 */
    .template-section {
      margin-bottom: var(--section-gap);
      break-inside: avoid;
      page-break-inside: avoid;
    }

    .section-title {
      font-size: 12.5pt;
      font-weight: 700;
      color: var(--theme-color);
      border-bottom: 1.5px solid var(--theme-color);
      padding-bottom: 2px;
      margin-bottom: 8px;
    }

    .item {
      margin-bottom: var(--item-gap);
      break-inside: avoid;
      page-break-inside: avoid;
    }

    .item-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 3px;
    }

    .item-title-group {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
    }

    .item-title {
      font-size: 10.5pt;
      font-weight: 700;
      color: #0f172a;
    }

    .item-subtitle, .item-degree, .item-dept {
      font-size: 9.5pt;
      color: #475569;
      font-weight: 500;
    }

    .item-date {
      font-size: 9pt;
      color: #64748b;
      white-space: nowrap;
    }

    .item-description {
      font-size: 9.5pt;
      color: #334155;
      line-height: var(--line-height);
    }

    .item-description ul {
      padding-left: 16px;
      margin: 2px 0;
    }

    .item-description li {
      margin-bottom: var(--list-item-gap);
    }

    /* 行内编辑模式高亮 */
    [contenteditable="true"] {
      outline: none;
      transition: background 0.15s ease, outline 0.15s ease;
      border-radius: 2px;
    }

    body.edit-mode [contenteditable="true"]:hover {
      background-color: rgba(37, 99, 235, 0.05);
      outline: 1px dashed rgba(37, 99, 235, 0.4);
    }

    body.edit-mode [contenteditable="true"]:focus {
      background-color: rgba(37, 99, 235, 0.08);
      outline: 2px solid var(--theme-color);
    }

    /* 本地悬浮工具栏 (零网络依赖) */
    .local-toolbar {
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: #1e293b;
      color: #f8fafc;
      padding: 6px 12px;
      border-radius: 9999px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
      display: flex;
      align-items: center;
      gap: 8px;
      z-index: 9999;
      font-size: 12px;
      font-weight: 500;
      backdrop-filter: blur(8px);
    }

    .local-toolbar button {
      background: transparent;
      border: none;
      color: #f8fafc;
      padding: 6px 10px;
      border-radius: 9999px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s ease;
      font-size: 12px;
    }

    .local-toolbar button:hover {
      background: #334155;
      color: #ffffff;
    }

    .local-toolbar button.active {
      background: var(--theme-color);
      color: #ffffff;
    }

    .toolbar-divider {
      width: 1px;
      height: 16px;
      background: #475569;
    }

    .fit-status-badge {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 9999px;
      background: #334155;
      color: #94a3b8;
    }

    /* A4 打印与另存为 PDF 样式 */
    @page {
      size: A4 portrait;
      margin: 0;
    }

    @media print {
      html, body {
        width: 210mm !important;
        height: 297mm !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #ffffff !important;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
      }

      .no-print, .local-toolbar {
        display: none !important;
      }

      .html-template-container {
        width: 210mm !important;
        max-width: 210mm !important;
        margin: 0 auto !important;
        box-shadow: none !important;
        border-radius: 0 !important;
        padding: var(--page-padding) !important;
      }

      [contenteditable="true"] {
        outline: none !important;
        background: transparent !important;
      }

      .template-header, .template-section, .item {
        break-inside: avoid !important;
        page-break-inside: avoid !important;
      }
    }
  </style>
</head>
<body class="${isEditable ? 'edit-mode' : ''}">

  ${isEditable ? `<!-- 本地悬浮工具栏 (离线可用) -->
  <div class="local-toolbar no-print">
    <button type="button" id="btn-edit-toggle" class="active" onclick="toggleEditMode()">
      ${SVG_ICONS.edit}
      <span>编辑模式</span>
    </button>
    <div class="toolbar-divider"></div>
    <button type="button" id="btn-auto-fit" onclick="runAutoOnePage()">
      ${SVG_ICONS.fit}
      <span>一页自适应</span>
    </button>
    <button type="button" id="btn-reset-fit" onclick="resetOnePage()">
      ${SVG_ICONS.reset}
      <span>重置排版</span>
    </button>
    <span class="fit-status-badge" id="fit-badge">A4 标准</span>
    <div class="toolbar-divider"></div>
    <button type="button" onclick="saveCurrentHTML()">
      ${SVG_ICONS.download}
      <span>保存修改</span>
    </button>
    <button type="button" style="background:var(--theme-color);color:#fff" onclick="printDocument()">
      ${SVG_ICONS.print}
      <span>打印 / 存为 PDF</span>
    </button>
  </div>` : ''}

  <!-- 简历主容器 -->
  <div class="html-template-container" id="resume-container">
    <!-- Header -->
    <header class="template-header">
      <div class="header-left">
        <h1 class="candidate-name" ${editableAttr}>${escapeHtml(basic.name || '姓名')}</h1>
        ${basic.title ? `<div class="candidate-title" ${editableAttr}>${escapeHtml(basic.title)}</div>` : ''}
        <div class="contact-row">
          ${basic.phone ? `<span class="contact-item">${SVG_ICONS.phone} <span ${editableAttr}>${escapeHtml(basic.phone)}</span></span>` : ''}
          ${basic.email ? `<span class="contact-item">${SVG_ICONS.mail} <span ${editableAttr}>${escapeHtml(basic.email)}</span></span>` : ''}
          ${basic.location ? `<span class="contact-item">${SVG_ICONS.mapPin} <span ${editableAttr}>${escapeHtml(basic.location)}</span></span>` : ''}
          ${basic.github ? `<span class="contact-item">${SVG_ICONS.github} <span ${editableAttr}>${escapeHtml(basic.github)}</span></span>` : ''}
          ${basic.website ? `<span class="contact-item">${SVG_ICONS.globe} <span ${editableAttr}>${escapeHtml(basic.website)}</span></span>` : ''}
        </div>
      </div>
      ${basic.photo ? `
        <div class="photo-slot">
          <img src="${escapeHtml(basic.photo)}" alt="Profile" onerror="this.parentElement.style.display='none'" />
        </div>
      ` : ''}
    </header>

    <!-- 动态模块渲染 -->
    <main>
      ${sectionsHtml}
    </main>
  </div>

  <!-- 本地内嵌离线脚本 (含 3-Tier 一页自适应算法) -->
  <script>
    var isEditing = ${isEditable ? 'true' : 'false'};
    function toggleEditMode() {
      isEditing = !isEditing;
      var btn = document.getElementById('btn-edit-toggle');
      if (isEditing) {
        document.body.classList.add('edit-mode');
        if (btn) btn.classList.add('active');
      } else {
        document.body.classList.remove('edit-mode');
        if (btn) btn.classList.remove('active');
      }
    }

    function runAutoOnePage() {
      var container = document.getElementById('resume-container');
      var badge = document.getElementById('fit-badge');
      if (!container) return;

      resetOnePage();
      var targetHeight = 1122.5; // A4 96 DPI
      var originalHeight = container.scrollHeight;

      if (originalHeight <= targetHeight) {
        if (badge) {
          badge.textContent = '无需压缩 (一页)';
          badge.style.color = '#4ade80';
        }
        return;
      }

      // Tier 1: 间距微调
      var spacingSteps = [0.85, 0.70, 0.55, 0.45];
      for (var i = 0; i < spacingSteps.length; i++) {
        var f = spacingSteps[i];
        container.style.setProperty('--section-gap', Math.round(16 * f) + 'px');
        container.style.setProperty('--item-gap', Math.round(10 * f) + 'px');
        container.style.setProperty('--page-padding', Math.round(32 * f) + 'px');
        if (container.scrollHeight <= targetHeight) {
          if (badge) {
            badge.textContent = '已自适应: 间距压缩 (T1)';
            badge.style.color = '#60a5fa';
          }
          return;
        }
      }

      // Tier 2: 行高微调
      var lhSteps = [1.38, 1.30, 1.22];
      for (var j = 0; j < lhSteps.length; j++) {
        container.style.setProperty('--line-height', String(lhSteps[j]));
        if (container.scrollHeight <= targetHeight) {
          if (badge) {
            badge.textContent = '已自适应: 行高压缩 (T2)';
            badge.style.color = '#38bdf8';
          }
          return;
        }
      }

      // Tier 3: 整体缩放
      var currentHeight = container.scrollHeight;
      var rawScale = targetHeight / currentHeight;
      var finalScale = Math.max(0.82, Number(rawScale.toFixed(3)));
      container.style.transform = 'scale(' + finalScale + ')';
      container.style.transformOrigin = 'top center';
      container.style.maxHeight = targetHeight + 'px';
      container.style.overflow = 'hidden';

      if (badge) {
        badge.textContent = '已自适应: 比例缩放 (' + Math.round(finalScale * 100) + '%)';
        badge.style.color = '#fbbf24';
      }
    }

    function resetOnePage() {
      var container = document.getElementById('resume-container');
      var badge = document.getElementById('fit-badge');
      if (!container) return;
      container.style.removeProperty('--section-gap');
      container.style.removeProperty('--item-gap');
      container.style.removeProperty('--page-padding');
      container.style.removeProperty('--line-height');
      container.style.transform = '';
      container.style.transformOrigin = '';
      container.style.maxHeight = '';
      container.style.overflow = '';
      if (badge) {
        badge.textContent = 'A4 标准';
        badge.style.color = '#94a3b8';
      }
    }

    function saveCurrentHTML() {
      var cleanHtml = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
      var blob = new Blob([cleanHtml], { type: 'text/html;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = '${escapeHtml(basic.name || "resume")}_简历_修改版.html';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    function printDocument() {
      window.print();
    }

    // 默认加载完成后若超出 A4 则自动执行一页微调
    window.addEventListener('DOMContentLoaded', function() {
      var container = document.getElementById('resume-container');
      if (container && container.scrollHeight > 1122.5) {
        runAutoOnePage();
      }
    });
  </script>
</body>
</html>`
}

/**
 * 保持向下兼容的原函数入口
 */
export function generateHTMLFile(resumeData: ResumeData): string {
  return generateHTML(resumeData, 'html-classic', { editable: true, autoOnePage: true })
}
