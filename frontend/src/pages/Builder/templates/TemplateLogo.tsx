/**
 * 模板内公司 / 学校 Logo 小图 —— HTML 模板共用。
 *
 * url 由 adapter 用 getLogoUrl(companyLogo) / getSchoolLogoUrl(schoolLogo) 解析后传入，
 * 无 url（未设 Logo / logos 未加载）则不渲染，不占位、不报错。
 * 导出 PDF 时随 DOM 被 html2pdf 一并抓取，无需后端参与。
 */
import React from 'react'

interface TemplateLogoProps {
  url?: string
  src?: string
  size?: number
  alt?: string
  className?: string
}

export const TemplateLogo: React.FC<TemplateLogoProps> = ({ url, src, size = 20, alt = 'logo', className }) => {
  const resolvedUrl = url || src
  if (!resolvedUrl) return null
  return (
    <img
      src={resolvedUrl}
      alt={alt}
      style={{ width: size, height: size, objectFit: 'contain' }}
      className={className ? `inline-block align-middle mr-1.5 shrink-0 ${className}` : 'inline-block align-middle mr-1.5 shrink-0'}
    />
  )
}

export default TemplateLogo
