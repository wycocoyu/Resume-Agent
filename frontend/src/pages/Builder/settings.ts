/**
 * 模板设置系统 —— 移植自 Resume-Matcher lib/types/template-settings.ts。
 * RM 全部 7 套模板已齐(双栏两套于 2026-07-08 补齐)。
 */
import type React from 'react'

export type AsuVariantId =
  | 'asu-01'
  | 'asu-02'
  | 'asu-03'
  | 'asu-04'
  | 'asu-05'
  | 'asu-06'
  | 'asu-07'
  | 'asu-08'
  | 'asu-09'
  | 'asu-10'
  | 'asu-11'
  | 'asu-12'
  | 'asu-13'
  | 'asu-14'
  | 'asu-15'
  | 'asu-16'
  | 'asu-17'
  | 'asu-18'

export type TemplateType =
  | 'swiss-single'
  | 'swiss-two-column'
  | 'modern'
  | 'modern-two-column'
  | 'latex'
  | 'clean'
  | 'vivid'
  | 'asu-tech'
  | AsuVariantId

export type PageSize = 'A4' | 'LETTER'

export type AccentColor = 'blue' | 'green' | 'orange' | 'red'

export type SpacingLevel = 1 | 2 | 3 | 4 | 5

export type HeaderFontFamily = 'serif' | 'sans-serif' | 'mono'
export type BodyFontFamily = 'serif' | 'sans-serif' | 'mono'

export interface MarginSettings {
  top: number // 5-25mm
  bottom: number
  left: number
  right: number
}

export interface SpacingSettings {
  section: SpacingLevel
  item: SpacingLevel
  lineHeight: SpacingLevel
}

export interface FontSizeSettings {
  base: SpacingLevel
  headerScale: SpacingLevel
  headerFont: HeaderFontFamily
  bodyFont: BodyFontFamily
}

export interface TemplateSettings {
  template: TemplateType
  pageSize: PageSize
  margins: MarginSettings
  spacing: SpacingSettings
  fontSize: FontSizeSettings
  compactMode: boolean
  showContactIcons: boolean
  accentColor: AccentColor
}

export const DEFAULT_TEMPLATE_SETTINGS: TemplateSettings = {
  template: 'latex',
  pageSize: 'A4',
  margins: { top: 10, bottom: 10, left: 10, right: 10 },
  spacing: { section: 3, item: 2, lineHeight: 3 },
  fontSize: { base: 3, headerScale: 3, headerFont: 'serif', bodyFont: 'serif' },
  compactMode: false,
  showContactIcons: false,
  accentColor: 'blue',
}

export const PAGE_SIZE_INFO: Record<PageSize, { name: string; dimensions: string }> = {
  A4: { name: 'A4', dimensions: '210 × 297 mm' },
  LETTER: { name: 'US Letter', dimensions: '8.5 × 11 in' },
}

export const SECTION_SPACING_MAP: Record<SpacingLevel, string> = {
  1: '0.375rem', // 6px
  2: '0.625rem', // 10px
  3: '1rem', // 16px - default
  4: '1.25rem', // 20px
  5: '1.5rem', // 24px
}

export const ITEM_SPACING_MAP: Record<SpacingLevel, string> = {
  1: '0.125rem', // 2px
  2: '0.25rem', // 4px - default
  3: '0.5rem', // 8px
  4: '0.75rem', // 12px
  5: '1rem', // 16px
}

export const LINE_HEIGHT_MAP: Record<SpacingLevel, number> = {
  1: 1.15,
  2: 1.25,
  3: 1.35, // default
  4: 1.45,
  5: 1.55,
}

export const FONT_SIZE_MAP: Record<SpacingLevel, string> = {
  1: '11px',
  2: '12px',
  3: '14px', // default
  4: '15px',
  5: '16px',
}

export const HEADER_SCALE_MAP: Record<SpacingLevel, number> = {
  1: 1.5,
  2: 1.75,
  3: 2, // default
  4: 2.25,
  5: 2.5,
}

export const SECTION_HEADER_SCALE_MAP: Record<SpacingLevel, number> = {
  1: 1.0,
  2: 1.1,
  3: 1.2, // default
  4: 1.3,
  5: 1.4,
}

export const HEADER_FONT_MAP: Record<HeaderFontFamily, string> = {
  serif: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif',
  'sans-serif': 'ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"',
  mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
}

export const BODY_FONT_MAP: Record<BodyFontFamily, string> = {
  serif: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif',
  'sans-serif': 'ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"',
  mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
}

export const ACCENT_COLOR_MAP: Record<
  AccentColor,
  { primary: string; light: string; name: string }
> = {
  blue: { primary: '#1D4ED8', light: '#DBEAFE', name: '蓝' },
  green: { primary: '#15803D', light: '#DCFCE7', name: '绿' },
  orange: { primary: '#EA580C', light: '#FED7AA', name: '橙' },
  red: { primary: '#DC2626', light: '#FEE2E2', name: '红' },
}

// Compact mode multiplier (applied to spacing values only, NOT line-height)
export const COMPACT_MULTIPLIER = 0.6

// Line height gets a gentler reduction in compact mode
export const COMPACT_LINE_HEIGHT_MULTIPLIER = 0.92

/**
 * Convert TemplateSettings to CSS custom properties
 */
export function settingsToCssVars(settings?: TemplateSettings): React.CSSProperties {
  const s = settings || DEFAULT_TEMPLATE_SETTINGS
  const compact = s.compactMode ? COMPACT_MULTIPLIER : 1

  const accentColors = ACCENT_COLOR_MAP[s.accentColor]

  return {
    '--section-gap': s.compactMode
      ? `calc(${SECTION_SPACING_MAP[s.spacing.section]} * ${compact})`
      : SECTION_SPACING_MAP[s.spacing.section],
    '--item-gap': s.compactMode
      ? `calc(${ITEM_SPACING_MAP[s.spacing.item]} * ${compact})`
      : ITEM_SPACING_MAP[s.spacing.item],
    // Line-height uses a gentler multiplier to avoid text overlap
    '--line-height': s.compactMode
      ? LINE_HEIGHT_MAP[s.spacing.lineHeight] * COMPACT_LINE_HEIGHT_MULTIPLIER
      : LINE_HEIGHT_MAP[s.spacing.lineHeight],
    '--font-size-base': FONT_SIZE_MAP[s.fontSize.base],
    '--header-scale': HEADER_SCALE_MAP[s.fontSize.headerScale],
    '--section-header-scale': SECTION_HEADER_SCALE_MAP[s.fontSize.headerScale],
    '--header-font': HEADER_FONT_MAP[s.fontSize.headerFont],
    '--body-font': BODY_FONT_MAP[s.fontSize.bodyFont],
    '--margin-top': `${s.margins.top}mm`,
    '--margin-bottom': `${s.margins.bottom}mm`,
    '--margin-left': `${s.margins.left}mm`,
    '--margin-right': `${s.margins.right}mm`,
    '--resume-accent-primary': accentColors.primary,
    '--resume-accent-light': accentColors.light,
  } as React.CSSProperties
}

/**
 * 对不可信的部分设置(localStorage / 简历内嵌 builderSettings)做字段级默认合并。
 */
export function withSettingsDefaults(partial: unknown): TemplateSettings {
  const parsed = (partial && typeof partial === 'object' ? partial : {}) as Partial<TemplateSettings>
  return {
    ...DEFAULT_TEMPLATE_SETTINGS,
    ...parsed,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...parsed.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...parsed.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...parsed.fontSize },
  }
}

export interface TemplateInfo {
  id: TemplateType
  name: string
  description: string
}

export const TEMPLATE_OPTIONS: TemplateInfo[] = [
  {
    id: 'latex',
    name: 'LaTeX',
    description: 'Classic serif academic layout with ruled section headers',
  },
  {
    id: 'swiss-single',
    name: 'Single Column',
    description: 'Traditional full-width layout with maximum content density',
  },
  {
    id: 'swiss-two-column',
    name: 'Two Column',
    description: 'Swiss two-column layout with sidebar for education and skills',
  },
  {
    id: 'modern',
    name: 'Modern',
    description: 'Colorful accents with customizable theme colors',
  },
  {
    id: 'modern-two-column',
    name: 'Modern 2-Col',
    description: 'Modern accent design in a two-column sidebar layout',
  },
  {
    id: 'clean',
    name: 'Clean',
    description: 'Minimal sans layout with large understated section headers',
  },
  {
    id: 'vivid',
    name: 'Vivid',
    description: 'Colorful two-column layout with accent headers and arrow bullets',
  },
  {
    id: 'asu-tech',
    name: 'ASu 极客单栏',
    description: '标准高密度技术单栏简历，精配公司条目灰色气泡与多层级项目列表',
  },
  {
    id: 'asu-01',
    name: '经典蓝线 (01)',
    description: '深蓝横线标题，单栏紧凑排版',
  },
  {
    id: 'asu-02',
    name: '蓝底色块条 (02)',
    description: '蓝底反白标题色块，单栏明朗结构',
  },
  {
    id: 'asu-03',
    name: '时间轴 (03)',
    description: '左侧经历时间轴连接线，科技感脉络',
  },
  {
    id: 'asu-04',
    name: '深蓝顶幅 (04)',
    description: '深蓝通栏顶幅背景，视觉冲击力强',
  },
  {
    id: 'asu-05',
    name: '灰调侧栏 (05)',
    description: '左侧浅灰背景功能侧栏，右侧主经历',
  },
  {
    id: 'asu-06',
    name: '纯黑时间轴双页 (06)',
    description: '沉稳黑灰时间轴双页设计，适合资深技术',
  },
  {
    id: 'asu-07',
    name: '右侧蓝轨 (07)',
    description: '右侧纵向蓝轨边线，版式独特鲜明',
  },
  {
    id: 'asu-08',
    name: '色块双栏双页 (08)',
    description: '双栏结构双页排版，信息密度充实',
  },
  {
    id: 'asu-09',
    name: '卡片分区双页 (09)',
    description: '模块轻微卡片边框包围，层级井然',
  },
  {
    id: 'asu-10',
    name: '丝带标签 (10)',
    description: '丝带切角标题标签，活泼有致',
  },
  {
    id: 'asu-11',
    name: '衬线分割头 (11)',
    description: '衬线优雅字体与双线分割头',
  },
  {
    id: 'asu-12',
    name: '居中作品集双页 (12)',
    description: '头部居中对齐，作品项目特化双页',
  },
  {
    id: 'asu-13',
    name: '纯黑紧凑侧栏 (13)',
    description: '深黑高对比紧凑侧栏，专业硬核',
  },
  {
    id: 'asu-14',
    name: '蓝线紧凑双栏双页 (14)',
    description: '蓝线主题紧凑双栏双页版式',
  },
  {
    id: 'asu-15',
    name: '色块现代序号 (15)',
    description: '模块标题带圆圈序号微标',
  },
  {
    id: 'asu-16',
    name: '超高密度双栏双页 (16)',
    description: '极端高密度双栏双页技术版式',
  },
  {
    id: 'asu-17',
    name: '纯黑学术风双页 (17)',
    description: '纯黑严谨学术风双页排版',
  },
  {
    id: 'asu-18',
    name: '蓝线现代紧凑双页 (18)',
    description: '现代极简蓝线双页排版',
  },
]

/**
 * Signature font presets for single-typeface templates.
 */
export const TEMPLATE_FONT_PRESETS: Partial<
  Record<TemplateType, { headerFont: HeaderFontFamily; bodyFont: BodyFontFamily }>
> = {
  latex: { headerFont: 'serif', bodyFont: 'serif' },
  clean: { headerFont: 'sans-serif', bodyFont: 'sans-serif' },
}

/**
 * Return settings with the given template applied, seeding the template's signature fonts.
 */
export function applyTemplatePreset(
  settings: TemplateSettings,
  template: TemplateType
): TemplateSettings {
  if (template === 'asu-tech') {
    return {
      ...settings,
      template,
      showContactIcons: true,
      margins: { top: 7, bottom: 8, left: 10, right: 10 },
    }
  }
  if (template.startsWith('asu-')) {
    return {
      ...settings,
      template,
      showContactIcons: true,
      margins:
        template === 'asu-12'
          ? { top: 7, bottom: 8, left: 10, right: 10 }
          : { top: 10, bottom: 10, left: 12, right: 12 },
    }
  }
  const preset = TEMPLATE_FONT_PRESETS[template]
  if (!preset) return { ...settings, template }
  return {
    ...settings,
    template,
    fontSize: { ...settings.fontSize, headerFont: preset.headerFont, bodyFont: preset.bodyFont },
  }
}
