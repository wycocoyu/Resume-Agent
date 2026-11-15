/**
 * Safe HTML Renderer —— 移植自 Resume-Matcher components/resume/safe-html.tsx。
 * 差异:清洗改用本地白名单序列化(sanitizeHtml.ts),不引 dompurify 依赖。
 */
import React from 'react'
import { sanitizeInlineHtml } from './sanitizeHtml'

interface SafeHtmlProps {
  /** HTML content to render (will be sanitized) */
  html: string
  /** Additional CSS classes */
  className?: string
  /** Render as a different element (default: span) */
  as?: 'span' | 'div' | 'p'
  /** 内联样式（用于强制字重等，优先级高于 class） */
  style?: React.CSSProperties
}

/**
 * Renders HTML content with XSS protection.
 * Only allows: <strong>, <em>, <u>, <a> tags.
 * Used in resume templates to render formatted bullet points.
 */
export const SafeHtml: React.FC<SafeHtmlProps> = ({ html, className, as: Component = 'span', style }) => {
  if (!html) {
    return null
  }

  const cleanHtml = sanitizeInlineHtml(html)

  return (
    <Component
      className={[
        '[&_a]:text-inherit [&_a]:underline [&_strong]:font-bold [&_strong]:[-webkit-text-stroke:0.3px_currentColor] [&_code]:px-1 [&_code]:py-0 [&_code]:rounded-[2px] [&_code]:bg-[#eef0f3] [&_code]:font-mono [&_code]:text-[0.9em]',
        className,
      ].filter(Boolean).join(' ')}
      style={style}
      dangerouslySetInnerHTML={{ __html: cleanHtml }}
    />
  )
}

/**
 * 渲染带内联 **加粗** markdown 的单行字段（公司名 / 职位 / 学校名）。
 * 编辑区 BoldInput 以 `**文本**` 形式存储加粗，这里转成 <strong> 再走 SafeHtml，
 * 与后端 LaTeX（latex_utils 的 **→\textbf）保持同一份加粗约定。无 ** 时等价于纯文本。
 *
 * weightControlled：字段本身由 class 写死了粗体（如公司名），此时非加粗态和加粗态视觉无
 * 差别。打开后用内联 font-weight:normal 压过 class，让「未加粗=常规、加粗=<strong> 粗体」
 * 真正可区分。仅用于带加粗开关的字段，不影响项目名等默认加粗的字段。
 */
export const InlineBold: React.FC<{
  text?: string
  className?: string
  as?: 'span' | 'div' | 'p'
  weightControlled?: boolean
}> = ({ text, className, as, weightControlled }) => {
  if (!text) return null
  const html = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  return (
    <SafeHtml
      html={html}
      className={className}
      as={as}
      style={weightControlled ? { fontWeight: 'normal' } : undefined}
    />
  )
}

export default SafeHtml
