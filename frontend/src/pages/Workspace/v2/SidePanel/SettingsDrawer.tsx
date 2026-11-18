/**
 * 设置抽屉（Settings Drawer）—— 从轨道右缘 slide 出的 overlay 面板。
 * 承载原先挤在 SidePanel 里的「模板选择」与「排版设置」两块，双 tab 切换。
 * 由 EditPreviewLayout 以 absolute 覆盖层渲染（z 低于列宽拖拽遮罩层 z-[9999]）。
 * 复用现有能力：模板缩略图（TemplateThumbnail）、HTML 排版（FormattingControls）。
 */
import { useState, useRef, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, Check, Minus, Plus, X } from 'lucide-react'
import { cn } from '../../../../lib/utils'
import type { GlobalSettings } from '../types'
import { FormattingControls } from '../../../Builder/components/FormattingControls'
import { TemplateThumbnail } from '../../../Builder/components/TemplateSelector'
import { withSettingsDefaults, TEMPLATE_OPTIONS, type TemplateType } from '../../../Builder/settings'
import type { TemplateSelection } from './index'

const DRAWER_WIDTH = 560

// 自定义下拉：选项在触发按钮下方展开，不占居中弹层
function DropdownSelect<T extends string | number>({
  options,
  value,
  onChange,
  className,
  placeholder,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  className?: string
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const currentLabel = options.find((o) => o.value === value)?.label ?? placeholder ?? String(value)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open])

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'w-full px-3 py-2.5 text-sm rounded-none fresh:rounded-md border text-left flex items-center justify-between gap-2 transition-[border-color,background-color,color] duration-200',
          'border-black fresh:border-slate-200 bg-white text-slate-800',
          'hover:border-black fresh:hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#1a73e8] focus:border-black fresh:focus:border-blue-400',
          open && 'ring-2 ring-[#1a73e8] border-black fresh:border-blue-400'
        )}
      >
        <span className="truncate">{currentLabel}</span>
        <ChevronDown className={cn('w-4 h-4 shrink-0 text-slate-400 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      {open && (
        <div
          className="absolute top-full left-0 right-0 z-50 mt-1 py-1 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-white shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md dark:shadow-[4px_4px_0px_0px_#ffffff] max-h-56 overflow-y-auto"
          role="listbox"
        >
          {options.map((opt) => {
            const isSelected = opt.value === value
            return (
              <button
                key={String(opt.value)}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onChange(opt.value)
                  setOpen(false)
                }}
                className={cn(
                  'w-full px-3 py-2 text-sm text-left flex items-center justify-between gap-2',
                  isSelected
                    ? 'bg-[#1a73e8] text-white'
                    : 'text-slate-700 dark:text-slate-300 hover:bg-[#D7E7FF] dark:hover:bg-slate-700/80'
                )}
              >
                <span className="truncate">{opt.label}</span>
                {isSelected && <Check className="w-4 h-4 shrink-0" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

const MIN_FONT_SIZE = 8
const MAX_FONT_SIZE = 12
const DEFAULT_FONT_SIZE = 11

// 页面边距选项（单位用「英寸」更易读）
const PAGE_MARGIN_OPTIONS: { value: 'tight' | 'compact' | 'standard' | 'relaxed' | 'wide'; label: string }[] = [
  { value: 'tight', label: '极紧 (0.25 英寸)' },
  { value: 'compact', label: '紧凑 (0.3 英寸)' },
  { value: 'standard', label: '标准 (0.4 英寸)' },
  { value: 'relaxed', label: '宽松 (0.5 英寸)' },
  { value: 'wide', label: '很宽 (0.6 英寸)' },
]

// 行间距选项
const LINE_SPACING_OPTIONS = [
  { value: 0.9, label: '0.9 (极紧)' },
  { value: 1.0, label: '1.0 (默认)' },
  { value: 1.1, label: '1.1' },
  { value: 1.15, label: '1.15' },
  { value: 1.2, label: '1.2' },
  { value: 1.3, label: '1.3' },
  { value: 1.5, label: '1.5 (宽松)' },
]

// 经历项间距选项 (LaTeX ex)
const EXPERIENCE_GAP_OPTIONS = [
  { value: 0, label: '无间距 (标准)' },
  { value: 1, label: '1ex' },
  { value: 1.2, label: '1.2ex' },
  { value: 1.5, label: '1.5ex' },
  { value: 2, label: '2ex (宽松)' },
]

// 页面内边距选项 (HTML 模板)
const PAGE_PADDING_OPTIONS = [
  { value: 15, label: '极紧凑 (15PX)' },
  { value: 20, label: '紧凑 (20PX)' },
  { value: 30, label: '适中 (30PX)' },
  { value: 40, label: '标准 (40PX)' },
  { value: 50, label: '宽松 (50PX)' },
]

// 头部空白参数基准（UI 显示 0 对应的内部值）
const HEADER_TOP_GAP_BASELINE = -4
const HEADER_NAME_CONTACT_GAP_BASELINE = 0
const HEADER_BOTTOM_GAP_BASELINE = -1

const normalizeDecimal = (value: number, digits = 2) => Number(value.toFixed(digits))

const inputBaseClass =
  'w-full px-3 py-2.5 text-sm rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-white text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#1a73e8] focus:border-black fresh:focus:border-blue-400 transition-colors'

const labelClass = 'block font-mono fresh:font-sans text-xs font-bold text-[#444850] fresh:text-gray-600 dark:text-slate-300 mb-1.5'

const LINE_SPACING_CUSTOM_VALUE = -1
const LINE_SPACING_WITH_CUSTOM = [
  ...LINE_SPACING_OPTIONS,
  { value: LINE_SPACING_CUSTOM_VALUE as number, label: '自定义...' },
]

function FontSizeControl({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const normalizedValue = Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, Math.round(value || DEFAULT_FONT_SIZE)))
  const [draftValue, setDraftValue] = useState(String(normalizedValue))

  useEffect(() => {
    setDraftValue(String(normalizedValue))
  }, [normalizedValue])

  const commitValue = (rawValue: string) => {
    const trimmedValue = rawValue.trim()
    const parsed = trimmedValue === '' ? Number.NaN : Number(trimmedValue)
    const nextValue = Number.isInteger(parsed)
      ? Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, parsed))
      : normalizedValue
    setDraftValue(String(nextValue))
    if (nextValue !== normalizedValue) onChange(nextValue)
  }

  const adjustValue = (delta: number) => {
    const nextValue = Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, normalizedValue + delta))
    setDraftValue(String(nextValue))
    if (nextValue !== normalizedValue) onChange(nextValue)
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <label className="font-mono fresh:font-sans text-xs font-bold text-[#444850] fresh:text-gray-600 dark:text-slate-300">
          字体大小
        </label>
        <span className="font-mono fresh:font-sans text-[11px] text-slate-400 tabular-nums">8–12 pt</span>
      </div>
      <div className="flex h-10 overflow-hidden rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-white focus-within:ring-2 focus-within:ring-[#1a73e8] fresh:focus-within:border-blue-400">
        <button
          type="button"
          aria-label="减小字体"
          disabled={normalizedValue <= MIN_FONT_SIZE}
          onClick={() => adjustValue(-1)}
          className="grid w-11 shrink-0 place-items-center border-r border-black fresh:border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-white"
        >
          <Minus className="h-4 w-4" />
        </button>
        <div className="flex min-w-0 flex-1 items-center justify-center gap-1">
          <input
            type="number"
            min={MIN_FONT_SIZE}
            max={MAX_FONT_SIZE}
            step={1}
            inputMode="numeric"
            aria-label="字体大小，单位 pt"
            value={draftValue}
            onChange={(event) => {
              const nextDraft = event.target.value
              setDraftValue(nextDraft)
              const parsed = Number(nextDraft)
              if (Number.isInteger(parsed) && parsed >= MIN_FONT_SIZE && parsed <= MAX_FONT_SIZE) {
                onChange(parsed)
              }
            }}
            onBlur={() => commitValue(draftValue)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                commitValue(draftValue)
                event.currentTarget.blur()
              }
            }}
            className="w-8 appearance-none bg-transparent text-center text-sm font-semibold tabular-nums text-slate-800 outline-none [MozAppearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
          <span className="text-xs font-medium text-slate-400">pt</span>
        </div>
        <button
          type="button"
          aria-label="增大字体"
          disabled={normalizedValue >= MAX_FONT_SIZE}
          onClick={() => adjustValue(1)}
          className="grid w-11 shrink-0 place-items-center border-l border-black fresh:border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-white"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-slate-400">影响整份 PDF 的基础字号，默认 11pt</p>
    </div>
  )
}

// 行间距控件：自定义下拉 + 自定义输入
function LineSpacingControl({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const isPreset = LINE_SPACING_OPTIONS.some((opt) => opt.value === value)
  const [customMode, setCustomMode] = useState(!isPreset)
  const dropdownValue = customMode ? LINE_SPACING_CUSTOM_VALUE : value

  return (
    <div>
      <label className={labelClass}>行间距</label>
      <div className="flex gap-2">
        <div className="flex-1 min-w-0">
          <DropdownSelect<number>
            options={LINE_SPACING_WITH_CUSTOM}
            value={dropdownValue}
            onChange={(v) => {
              if (v === LINE_SPACING_CUSTOM_VALUE) {
                setCustomMode(true)
              } else {
                setCustomMode(false)
                onChange(v)
              }
            }}
          />
        </div>
        {customMode && (
          <input
            type="number"
            step="0.05"
            min="0.5"
            max="3.0"
            value={value}
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              if (!isNaN(v) && v >= 0.5 && v <= 3.0) onChange(v)
            }}
            className={cn(inputBaseClass, 'w-20')}
          />
        )}
      </div>
    </div>
  )
}

function HeaderGapControl({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <label className="font-mono fresh:font-sans text-xs font-bold text-[#444850] fresh:text-gray-600 dark:text-slate-400">{label}</label>
        <span className="font-mono fresh:font-sans text-xs text-slate-500 dark:text-slate-400 tabular-nums shrink-0">
          {value > 0 ? `+${value}` : value}px
        </span>
      </div>
      <p className="text-[11px] text-slate-500 dark:text-slate-500 leading-snug">{hint}</p>
      <input
        type="range"
        min={-5}
        max={5}
        step={0.5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1 bg-[#E5E5E0] fresh:bg-slate-100 dark:bg-slate-700 rounded-none fresh:rounded-md appearance-none cursor-pointer accent-[#4285F4]
                   [&::-webkit-slider-thumb]:appearance-none
                   [&::-webkit-slider-thumb]:w-3
                   [&::-webkit-slider-thumb]:h-3
                   [&::-webkit-slider-thumb]:bg-[#4285F4]
                   [&::-webkit-slider-thumb]:border-none
                   [&::-webkit-slider-thumb]:cursor-pointer
                   [&::-moz-range-thumb]:w-3
                   [&::-moz-range-thumb]:h-3
                   [&::-moz-range-thumb]:bg-[#4285F4]
                   [&::-moz-range-thumb]:border-none
                   [&::-moz-range-thumb]:cursor-pointer"
      />
    </div>
  )
}

/** 大缩略图模板卡片：复用 TemplateThumbnail（56×72），CSS scale 放大 ~2.7 倍到 ~150×195 */
function LargeTemplateCard({
  active,
  recommended,
  name,
  description,
  thumbnailType,
  onClick,
}: {
  active: boolean
  recommended?: boolean
  name: string
  description: string
  thumbnailType: TemplateType
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={description}
      className={cn(
        'group relative flex flex-col items-center p-3 border-2 fresh:border bg-white transition-all',
        active
          ? 'border-black fresh:border-slate-200 shadow-[3px_3px_0px_0px_#000000] fresh:shadow-md dark:border-white dark:shadow-[3px_3px_0px_0px_#ffffff]'
          : 'border-slate-300 dark:border-slate-600 hover:border-black fresh:hover:border-slate-300 dark:hover:border-white hover:shadow-[2px_2px_0px_0px_#000000] dark:hover:shadow-[2px_2px_0px_0px_#ffffff]'
      )}
    >
      {recommended && (
        <span className="absolute top-1.5 left-1.5 z-10 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-[#4285F4] px-1.5 py-0.5 text-[9px] font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normalr fresh:tracking-normal text-white">
          推荐
        </span>
      )}
      {active && (
        <span className="absolute top-1.5 right-1.5 z-10 w-5 h-5 bg-black dark:bg-white flex items-center justify-center">
          <Check className="w-3.5 h-3.5 text-white dark:text-black" strokeWidth={3} />
        </span>
      )}
      <div className="h-[200px] w-full flex items-center justify-center overflow-hidden">
        <div className="scale-[2.7] origin-center">
          <TemplateThumbnail type={thumbnailType} isActive={active} />
        </div>
      </div>
      <span
        className={cn(
          'mt-3 font-mono fresh:font-sans text-[11px] uppercase fresh:normal-case tracking-wide fresh:tracking-normalr fresh:tracking-normal font-bold',
          active ? 'text-black dark:text-white' : 'text-[#444850] fresh:text-gray-600 dark:text-slate-400'
        )}
      >
        {name}
      </span>
    </button>
  )
}

/** 模板 tab：2 列大缩略图，按渲染引擎分「原生 LaTeX / 在线 HTML」两组 */
function TemplateTab({
  templateType,
  globalSettings,
  onSelectTemplate,
}: {
  templateType?: 'latex' | 'html'
  globalSettings: GlobalSettings
  onSelectTemplate: (selection: TemplateSelection) => void
}) {
  return (
    <div className="space-y-6">
      {/* 组一：原生 LaTeX（服务端 XeLaTeX 引擎） */}
      <div>
        <div className="flex items-center gap-1.5 mb-1">
          <span className="font-mono fresh:font-sans text-[11px] font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normalr fresh:tracking-normal text-black dark:text-white">
            原生精排 · LaTeX
          </span>
          {templateType !== 'html' && <span className="w-1.5 h-1.5 bg-blue-700 shrink-0" />}
        </div>
        <p className="mb-3 font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
          服务端 XeLaTeX 精确排版 · 导出矢量文字 PDF
        </p>
        <div className="grid grid-cols-2 gap-3">
          <LargeTemplateCard
            active={templateType !== 'html'}
            recommended
            name="Classic LaTeX"
            description="经典模板：服务端 XeLaTeX 精确排版，导出矢量 PDF"
            thumbnailType="latex"
            onClick={() => onSelectTemplate({ type: 'latex' })}
          />
        </div>
      </div>

      {/* 组二：在线 HTML 模板（浏览器实时渲染） */}
      <div>
        <div className="flex items-center gap-1.5 mb-1">
          <span className="font-mono fresh:font-sans text-[11px] font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normalr fresh:tracking-normal text-black dark:text-white">
            在线模板 · HTML
          </span>
          {templateType === 'html' && <span className="w-1.5 h-1.5 bg-blue-700 shrink-0" />}
        </div>
        <p className="mb-3 font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
          实时预览 · 模板与排版即改即见 · 前端导出
        </p>
        <div className="grid grid-cols-2 gap-3">
          {TEMPLATE_OPTIONS.map((t) => (
            <LargeTemplateCard
              key={t.id}
              active={
                templateType === 'html' &&
                withSettingsDefaults(globalSettings.builderSettings).template === t.id
              }
              recommended={t.id === 'latex'}
              name={t.id === 'latex' ? 'LaTeX Style' : t.name}
              description={t.description}
              thumbnailType={t.id}
              onClick={() => onSelectTemplate({ type: 'html', template: t.id })}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

/** 排版 tab：按 templateType 分支——HTML 走 FormattingControls，LaTeX 走原生排版卡 */
function FormatTab({
  templateType,
  globalSettings,
  updateGlobalSettings,
}: {
  templateType?: 'latex' | 'html'
  globalSettings: GlobalSettings
  updateGlobalSettings: (settings: Partial<GlobalSettings>) => void
}) {
  const [headerGapExpanded, setHeaderGapExpanded] = useState(true)

  if (templateType === 'html') {
    return (
      <FormattingControls
        settings={withSettingsDefaults(globalSettings.builderSettings)}
        onChange={(next) =>
          updateGlobalSettings({ builderSettings: next as unknown as Record<string, unknown> })
        }
        hideTemplateSection
      />
    )
  }

  return (
    <div className="space-y-5">
      <FontSizeControl
        value={globalSettings.latexFontSize || DEFAULT_FONT_SIZE}
        onChange={(value) => updateGlobalSettings({ latexFontSize: value })}
      />

      {/* 页面边距 */}
      <div>
        <label className={labelClass}>页面边距</label>
        <DropdownSelect
          options={PAGE_MARGIN_OPTIONS}
          value={globalSettings.latexMargin || 'standard'}
          onChange={(v) => updateGlobalSettings({ latexMargin: v })}
        />
      </div>

      {/* 行间距 */}
      <LineSpacingControl
        value={globalSettings.latexLineSpacing || 1.0}
        onChange={(v) => updateGlobalSettings({ latexLineSpacing: v })}
      />

      {/* 经历项间距 */}
      <div>
        <label className={labelClass}>多段实习经历之间的间距</label>
        <DropdownSelect
          options={EXPERIENCE_GAP_OPTIONS}
          value={globalSettings.experienceGap ?? 1}
          onChange={(v) => updateGlobalSettings({ experienceGap: v })}
        />
      </div>

      <div>
        <label className={labelClass}>多段项目经历之间的间距</label>
        <DropdownSelect
          options={EXPERIENCE_GAP_OPTIONS}
          value={globalSettings.projectExperienceGap ?? 1}
          onChange={(v) => updateGlobalSettings({ projectExperienceGap: v })}
        />
      </div>

      {/* 页面内边距 */}
      <div>
        <label className={labelClass}>页面内边距</label>
        <DropdownSelect
          options={PAGE_PADDING_OPTIONS}
          value={globalSettings.pagePadding ?? 40}
          onChange={(v) => updateGlobalSettings({ pagePadding: v })}
        />
      </div>

      {/* 头部间距（LaTeX）：姓名/联系方式区域的三段留白，拖动滑块调整、负值压缩留白 */}
      <div className="rounded-none fresh:rounded-md bg-blue-50/50 dark:bg-slate-800/50 border border-blue-100/50 p-3 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">头部间距</label>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
              调整姓名、联系方式区域上下的留白
            </p>
          </div>
          <button
            type="button"
            onClick={() => setHeaderGapExpanded((v) => !v)}
            className="p-1 rounded hover:bg-blue-100/50 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors shrink-0"
            title={headerGapExpanded ? '收起' : '展开'}
          >
            <ChevronDown className={cn('w-4 h-4 transition-transform', headerGapExpanded && 'rotate-180')} />
          </button>
        </div>
        {headerGapExpanded && (
          <>
            <HeaderGapControl
              label="顶部空白"
              hint="姓名区域到页面最顶端的空白、往左拖更贴顶"
              value={normalizeDecimal((globalSettings.latexHeaderTopGapPx ?? HEADER_TOP_GAP_BASELINE) - HEADER_TOP_GAP_BASELINE)}
              onChange={(v) => updateGlobalSettings({ latexHeaderTopGapPx: normalizeDecimal(HEADER_TOP_GAP_BASELINE + v) })}
            />
            <HeaderGapControl
              label="姓名与联系信息间距"
              hint="姓名和下方邮箱/电话之间的距离"
              value={normalizeDecimal((globalSettings.latexHeaderNameContactGapPx ?? HEADER_NAME_CONTACT_GAP_BASELINE) - HEADER_NAME_CONTACT_GAP_BASELINE)}
              onChange={(v) => updateGlobalSettings({ latexHeaderNameContactGapPx: normalizeDecimal(HEADER_NAME_CONTACT_GAP_BASELINE + v) })}
            />
            <HeaderGapControl
              label="联系信息下方空白"
              hint="邮箱/电话到下一模块（如教育经历）之间的距离"
              value={normalizeDecimal((globalSettings.latexHeaderBottomGapPx ?? HEADER_BOTTOM_GAP_BASELINE) - HEADER_BOTTOM_GAP_BASELINE)}
              onChange={(v) => updateGlobalSettings({ latexHeaderBottomGapPx: normalizeDecimal(HEADER_BOTTOM_GAP_BASELINE + v) })}
            />
          </>
        )}
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400 pt-1">
        调整后简历会自动重新渲染
      </p>
    </div>
  )
}

export type SettingsDrawerTab = 'template' | 'format'

interface SettingsDrawerProps {
  /** 当前展开的 tab；null 表示收起 */
  activeTab: SettingsDrawerTab | null
  /** 点击 tab / segmented：同 tab 收起，异 tab 切换（由父级实现 toggle 语义） */
  onToggleTab: (tab: SettingsDrawerTab) => void
  onClose: () => void
  /** 抽屉左缘对齐轨道左缘；覆盖层宽度 = 轨道 + EditPanel（不含预览列） */
  overlayWidth: number
  /** 抽屉从轨道右缘 slide 出：轨道宽度决定初始位移 */
  trackWidth: number
  templateType?: 'latex' | 'html'
  globalSettings: GlobalSettings
  onSelectTemplate: (selection: TemplateSelection) => void
  updateGlobalSettings: (settings: Partial<GlobalSettings>) => void
}

const TAB_META: { key: SettingsDrawerTab; label: string }[] = [
  { key: 'template', label: '🎨 模板' },
  { key: 'format', label: '⚙ 排版' },
]

export default function SettingsDrawer({
  activeTab,
  onToggleTab,
  onClose,
  overlayWidth,
  trackWidth,
  templateType,
  globalSettings,
  onSelectTemplate,
  updateGlobalSettings,
}: SettingsDrawerProps) {
  // 抽屉右缘从轨道右缘（trackWidth）滑出到 DRAWER_WIDTH，初始位移为负
  const slideOffset = trackWidth - DRAWER_WIDTH

  return (
    <AnimatePresence>
      {activeTab && (
        <motion.div
          key="settings-drawer"
          initial={false}
          className="absolute left-0 top-0 bottom-0 z-20 flex"
          style={{ width: overlayWidth }}
        >
          {/* 抽屉面板 */}
          <motion.div
            initial={{ x: slideOffset }}
            animate={{ x: 0 }}
            exit={{ x: slideOffset }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className={cn(
              'relative h-full flex flex-col shrink-0',
              'bg-white dark:bg-slate-900',
              'border-r-2 fresh:border-r border-black fresh:border-slate-200 dark:border-slate-100',
              'shadow-[4px_0px_16px_-4px_rgba(0,0,0,0.25)]'
            )}
            style={{ width: DRAWER_WIDTH }}
          >
            {/* 抽屉头部：tab（原 segmented）+ 关闭 */}
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
              <div className="flex items-center border border-black fresh:border-slate-200 dark:border-slate-100 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff]">
                {TAB_META.map((t) => {
                  const isActive = activeTab === t.key
                  return (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() => onToggleTab(t.key)}
                      className={cn(
                        'px-4 py-1.5 text-sm font-bold font-mono fresh:font-sans transition-colors',
                        isActive
                          ? 'bg-[#4285F4] text-white'
                          : 'bg-white text-slate-700 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                      )}
                    >
                      {t.label}
                    </button>
                  )
                })}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
                title="收起"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* 抽屉内容：切 tab 即时换，无 slide */}
            <div className="flex-1 overflow-y-auto p-4">
              {activeTab === 'template' ? (
                <TemplateTab
                  templateType={templateType}
                  globalSettings={globalSettings}
                  onSelectTemplate={onSelectTemplate}
                />
              ) : activeTab === 'format' ? (
                <FormatTab
                  templateType={templateType}
                  globalSettings={globalSettings}
                  updateGlobalSettings={updateGlobalSettings}
                />
              ) : null}
            </div>
          </motion.div>

          {/* scrim：EditPanel 未被抽屉盖住的部分，半透明；点击收起。预览列不在覆盖层内，始终明亮 */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="flex-1 bg-black/30 cursor-pointer"
            onClick={onClose}
          />
        </motion.div>
      )}
    </AnimatePresence>
  )
}
