/**
 * Resume 分发器 —— 移植自 Resume-Matcher components/dashboard/resume-component.tsx。
 * 差异:无 i18n label props。RM 全部 7 套模板已齐(双栏两套于 2026-07-08 补齐)。
 */
import React from 'react'
import type { BuilderResumeData } from '../types'
import {
  type TemplateSettings,
  DEFAULT_TEMPLATE_SETTINGS,
  settingsToCssVars,
} from '../settings'
import { ResumeLatex } from './ResumeLatex'
import { ResumeSingleColumn } from './ResumeSingleColumn'
import { ResumeTwoColumn } from './ResumeTwoColumn'
import { ResumeModern } from './ResumeModern'
import { ResumeModernTwoColumn } from './ResumeModernTwoColumn'
import { ResumeClean } from './ResumeClean'
import { ResumeVivid } from './ResumeVivid'
import { ResumeAsuTech } from './ResumeAsuTech'
import { ResumeAsuVariant } from './ResumeAsuVariant'
import type { AsuVariantId } from '../settings'
import baseStyles from './styles/_base.module.css'

interface ResumeRendererProps {
  resumeData: BuilderResumeData
  settings?: TemplateSettings
  /** 屏幕可视预览用：深色模式下纸张跟随反色（黑底浅字）。
   * 导出用的离屏容器（html2pdf 抓取源）绝不能传 true——导出必须始终是
   * 印刷标准的白底黑字，与当前是否深色模式无关。 */
  themeAware?: boolean
}

export const ResumeRenderer: React.FC<ResumeRendererProps> = ({ resumeData, settings, themeAware = false }) => {
  const mergedSettings: TemplateSettings = {
    ...DEFAULT_TEMPLATE_SETTINGS,
    ...settings,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...settings?.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...settings?.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...settings?.fontSize },
  }

  const cssVars = settingsToCssVars(mergedSettings)
  const showContactIcons = mergedSettings.showContactIcons

  return (
    <div
      className={`${baseStyles['resume-body']} bg-white text-black w-full mx-auto resume-template-${mergedSettings.template} ${
        themeAware ? 'dark:bg-transparent dark:text-[#f5f5f5]' : ''
      }`}
      style={cssVars}
    >
      {mergedSettings.template === 'swiss-single' && (
        <ResumeSingleColumn data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'swiss-two-column' && (
        <ResumeTwoColumn data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'modern' && (
        <ResumeModern data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'modern-two-column' && (
        <ResumeModernTwoColumn data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'latex' && (
        <ResumeLatex data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'clean' && (
        <ResumeClean data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'vivid' && (
        <ResumeVivid data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template === 'asu-tech' && (
        <ResumeAsuTech data={resumeData} showContactIcons={showContactIcons} />
      )}
      {mergedSettings.template.startsWith('asu-') && (
        <ResumeAsuVariant
          data={resumeData}
          variantId={mergedSettings.template as AsuVariantId}
          showContactIcons={showContactIcons}
        />
      )}
    </div>
  )
}

export default ResumeRenderer
