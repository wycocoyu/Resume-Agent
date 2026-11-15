/**
 * 行内 HTML 白名单序列化(替代 RM 的 isomorphic-dompurify,零依赖)。
 * 仅保留 strong/b/em/i/u/a,a 的 href 限 http/https/mailto/tel;其余标签拍平为纯文本。
 */

const INLINE_TAGS = new Set(['STRONG', 'B', 'EM', 'I', 'U', 'A', 'CODE'])

export function escapeText(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeAttr(value: string): string {
  return escapeText(value).replace(/"/g, '&quot;')
}

/** 递归序列化节点为仅含白名单行内标签的 HTML 片段(块级标签拍平) */
export function inlineNodeHtml(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return escapeText(node.textContent || '')
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const el = node as HTMLElement
  const inner = Array.from(el.childNodes).map(inlineNodeHtml).join('')
  if (INLINE_TAGS.has(el.tagName)) {
    if (el.tagName === 'A') {
      const href = el.getAttribute('href') || ''
      if (/^(https?:|mailto:|tel:)/i.test(href)) {
        return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
      }
      return inner
    }
    const tag = el.tagName.toLowerCase()
    return inner ? `<${tag}>${inner}</${tag}>` : ''
  }
  if (el.tagName === 'BR') return ' '
  // 块级标签:拍平,只保留内容
  return inner
}

/** 清洗任意 HTML 字符串为安全的行内片段 */
export function sanitizeInlineHtml(html: string): string {
  if (!html) return ''
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(doc.body.childNodes).map(inlineNodeHtml).join('').trim()
}
