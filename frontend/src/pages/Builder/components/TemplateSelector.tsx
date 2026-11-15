/**
 * 模板缩略图选择器 —— 移植自 Resume-Matcher components/builder/template-selector.tsx。
 * 差异:5 套模板(去双栏两套);label 硬编码(去 next-intl);token 换算为 arbitrary class。
 */
import React from 'react'
import { type TemplateType, TEMPLATE_OPTIONS } from '../settings'

interface TemplateSelectorProps {
  value: TemplateType
  onChange: (template: TemplateType) => void
}

export const TemplateSelector: React.FC<TemplateSelectorProps> = ({ value, onChange }) => {
  return (
    <div className="flex flex-wrap gap-3">
      {TEMPLATE_OPTIONS.map((template) => (
        <button
          key={template.id}
          onClick={() => onChange(template.id)}
          className={`group flex flex-col items-center p-3 border-2 transition-all ${
            value === template.id
              ? 'border-blue-700 bg-white shadow-[3px_3px_0px_0px_#1D4ED8]'
              : 'border-black bg-white hover:bg-[#F0F0E8] hover:shadow-[2px_2px_0px_0px_#000000]'
          }`}
          title={template.description}
        >
          {/* Template Thumbnail */}
          <div className="w-16 h-20 mb-2 flex items-center justify-center">
            <TemplateThumbnail type={template.id} isActive={value === template.id} />
          </div>

          {/* Template Name */}
          <span
            className={`font-mono text-[10px] uppercase tracking-wider font-bold ${
              value === template.id ? 'text-blue-700' : 'text-[#444850]'
            }`}
          >
            {template.name}
          </span>
        </button>
      ))}
    </div>
  )
}

/**
 * Template Thumbnail —— CSS 画的迷你版式预览(移植自 RM,保留 5 款)。
 */
interface TemplateThumbnailProps {
  type: TemplateType
  isActive: boolean
}

export const TemplateThumbnail: React.FC<TemplateThumbnailProps> = ({ type, isActive }) => {
  const lineColor = isActive ? 'bg-blue-700' : 'bg-[#878E99]'
  const borderColor = isActive ? 'border-blue-700' : 'border-[#878E99]'
  const accentColor = isActive ? 'bg-blue-600' : 'bg-blue-400'

  if (type === 'swiss-single') {
    // Single column thumbnail
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header */}
        <div className={`h-2 ${lineColor} w-full`}></div>
        <div className={`h-0.5 ${lineColor} w-3/4`}></div>
        {/* Sections */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-1"></div>
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
        </div>
      </div>
    )
  }

  if (type === 'latex') {
    // LaTeX thumbnail - centered name + Title-Case ruled section headers (serif feel)
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Centered name + contact */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-2/3`}></div>
          <div className={`h-0.5 ${lineColor} w-1/2 opacity-60`}></div>
        </div>
        {/* Sections: each header is a full-width line with a bottom rule */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-0.5 ${lineColor} w-2/5 border-b ${borderColor} pb-1`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-0.5 ${lineColor} w-1/3 border-b ${borderColor} pb-1`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        </div>
      </div>
    )
  }

  if (type === 'clean') {
    // Clean thumbnail - centered light name + large understated gray uppercase headers
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Centered light name + contact line */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-1/2 opacity-70`}></div>
          <div className={`h-0.5 ${lineColor} w-2/3 opacity-40`}></div>
        </div>
        {/* Large gray section headers (taller, lower opacity) + thin rule */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-1 ${lineColor} w-1/2 opacity-30 border-b ${borderColor}`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-1 ${lineColor} w-2/5 opacity-30 border-b ${borderColor}`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        </div>
      </div>
    )
  }

  if (type === 'swiss-two-column') {
    // Swiss two-column thumbnail - full-width header + main/sidebar split with divider
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header */}
        <div className={`h-2 ${lineColor} w-full`}></div>
        <div className={`h-0.5 ${lineColor} w-3/4`}></div>
        {/* Two columns with divider */}
        <div className="flex-1 flex gap-1 mt-1">
          {/* Main column */}
          <div className="w-2/3 space-y-1">
            <div className={`h-0.5 ${lineColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
            <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${lineColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
          </div>
          {/* Divider */}
          <div className={`w-px ${lineColor} opacity-40`}></div>
          {/* Sidebar */}
          <div className="flex-1 space-y-1">
            <div className={`h-0.5 ${lineColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${lineColor} w-full`}></div>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'modern-two-column') {
    // Modern two-column thumbnail - accent underlined header + main/sidebar with accent section heads
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header with accent underline */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-3/4`}></div>
          <div className={`h-0.5 ${accentColor} w-1/3`}></div>
        </div>
        {/* Two columns */}
        <div className="flex-1 flex gap-1 mt-1">
          {/* Main column with accent headers */}
          <div className="w-2/3 space-y-1">
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
            <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
          </div>
          {/* Sidebar with accent headers */}
          <div className="flex-1 space-y-1">
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'vivid') {
    // Vivid thumbnail - two-tone accent name + accent headers + accent arrow bullets
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Two-tone name (left-aligned) */}
        <div className="flex items-center gap-0.5">
          <div className={`h-1.5 ${accentColor} w-1/3`}></div>
          <div className={`h-1.5 ${accentColor} w-1/4 opacity-50`}></div>
        </div>
        <div className={`h-0.5 ${lineColor} w-2/3 opacity-40`}></div>
        {/* Two columns (no divider) */}
        <div className="flex-1 flex gap-1 mt-0.5">
          {/* Left column with arrow ticks */}
          <div className="w-2/3 space-y-0.5">
            <div className={`h-0.5 ${accentColor} w-1/2`}></div>
            <div className="flex items-center gap-0.5">
              <div className={`h-0.5 w-0.5 ${accentColor}`}></div>
              <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
            </div>
            <div className="flex items-center gap-0.5">
              <div className={`h-0.5 w-0.5 ${accentColor}`}></div>
              <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
            </div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-2/5`}></div>
          </div>
          {/* Right column (sidebar) */}
          <div className="w-1/3 space-y-0.5">
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-3/5 opacity-50`}></div>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'asu-tech' || (typeof type === 'string' && type.startsWith('asu-'))) {
    return (
      <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1 flex flex-col gap-0.5`}>
        {/* Header with photo slot indicator */}
        <div className="flex justify-between items-center">
          <div className="space-y-0.5 flex-1">
            <div className={`h-1.5 ${lineColor} w-2/3`}></div>
            <div className={`h-0.5 ${lineColor} w-1/2 opacity-60`}></div>
          </div>
          <div className={`w-2.5 h-3 border ${borderColor} rounded-[1px] opacity-40`}></div>
        </div>
        {/* Section title blue bar */}
        <div className={`h-0.5 ${accentColor} w-full mt-0.5`}></div>
        {/* Company bar indicator */}
        <div className="bg-slate-100 rounded-[2px] p-0.5 flex justify-between items-center">
          <div className={`h-0.5 ${lineColor} w-2/5`}></div>
          <div className={`h-0.5 ${lineColor} w-1/4 opacity-40`}></div>
        </div>
        {/* Bullets */}
        <div className="space-y-0.5 pl-1">
          <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-3/5 opacity-50`}></div>
        </div>
      </div>
    )
  }

  // Modern template thumbnail - with accent color highlights
  return (
    <div className={`w-14 h-[4.5rem] border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
      {/* Header with accent underline */}
      <div className="flex flex-col items-center gap-0.5">
        <div className={`h-2 ${lineColor} w-3/4`}></div>
        <div className={`h-0.5 ${accentColor} w-1/3`}></div>
      </div>
      {/* Sections with accent headers */}
      <div className="flex-1 space-y-1 mt-1">
        <div className={`h-0.5 ${accentColor} w-full`}></div>
        <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
        <div className="h-0.5"></div>
        <div className={`h-0.5 ${accentColor} w-full`}></div>
        <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
      </div>
    </div>
  )
}
