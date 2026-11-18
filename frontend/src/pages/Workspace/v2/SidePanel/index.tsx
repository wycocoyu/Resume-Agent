/**
 * 侧边面板组件（编辑区的第一列）
 * 只保留「布局设置」（模块导航列表）+ 顶部一条「模板/排版」segmented 触发条。
 * 模板选择与排版设置已挪进设置抽屉（SettingsDrawer），由 EditPreviewLayout 以覆盖层渲染。
 */
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Layout, ChevronDown } from 'lucide-react'
import { cn } from '../../../../lib/utils'
import type { MenuSection, GlobalSettings } from '../types'
import LayoutSetting from './LayoutSetting'
import { type TemplateType } from '../../../Builder/settings'
import type { SettingsDrawerTab } from './SettingsDrawer'

/** 统一模板选择：经典 XeLaTeX 或 Builder HTML 模板 */
export type TemplateSelection = { type: 'latex' } | { type: 'html'; template: TemplateType }

interface SidePanelProps {
  menuSections: MenuSection[]
  activeSection: string
  globalSettings: GlobalSettings
  setActiveSection: (id: string) => void
  toggleSectionVisibility: (id: string) => void
  updateMenuSections: (sections: MenuSection[]) => void
  reorderSections: (sections: MenuSection[]) => void
  updateGlobalSettings: (settings: Partial<GlobalSettings>) => void
  addCustomSection: () => void
  /** 当前展开的设置抽屉 tab；null 表示收起（用于 segmented 高亮） */
  settingsDrawer?: SettingsDrawerTab | null
  /** 点击 segmented：同 tab 收起，异 tab 切换/展开 */
  onToggleSettingsDrawer?: (tab: SettingsDrawerTab) => void
}

/**
 * 设置卡片容器，可选折叠（collapsible + defaultExpanded）
 */
export function SettingCard({
  icon: Icon,
  title,
  children,
  collapsible = false,
  defaultExpanded = true,
}: {
  icon: React.ElementType
  title: string
  children: React.ReactNode
  collapsible?: boolean
  defaultExpanded?: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div
      className={cn(
        'rounded-none fresh:rounded-md overflow-hidden',
        'bg-white dark:bg-slate-800/80',
        'border border-slate-200/60 dark:border-slate-700/80',
        'shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff]'
      )}
    >
      {title && (
        <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700/80">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-none fresh:rounded-md bg-[#D7E7FF]/50 dark:bg-slate-700/80 flex items-center justify-center">
                <Icon className="w-4 h-4 text-slate-600 dark:text-slate-300" />
              </div>
              <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 tracking-tight">
                {title}
              </span>
            </div>
            {collapsible && (
              <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
                title={expanded ? '收起' : '展开'}
              >
                <ChevronDown className={cn('w-4 h-4 transition-transform', expanded && 'rotate-180')} />
              </button>
            )}
          </div>
        </div>
      )}
      {(!collapsible || expanded) && (
        <div className={cn('px-4', title ? 'py-4' : 'pt-4 pb-4')}>{children}</div>
      )}
    </div>
  )
}

/** 顶部 segmented 触发条：点「模板 / 排版」展开设置抽屉；再点当前项收起 */
function SettingsSegmented({
  settingsDrawer,
  onToggle,
}: {
  settingsDrawer: SettingsDrawerTab | null
  onToggle: (tab: SettingsDrawerTab) => void
}) {
  const items: { key: SettingsDrawerTab; label: string }[] = [
    { key: 'template', label: '🎨 模板' },
    { key: 'format', label: '⚙ 排版' },
  ]
  return (
    <div className="flex items-stretch border border-black fresh:border-slate-200 dark:border-slate-100 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff]">
      {items.map((item) => {
        const isActive = settingsDrawer === item.key
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onToggle(item.key)}
            className={cn(
              'flex-1 px-3 py-2 text-sm font-bold font-mono fresh:font-sans transition-colors',
              isActive
                ? 'bg-[#4285F4] text-white'
                : 'bg-white text-slate-700 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export function SidePanel({
  menuSections,
  activeSection,
  setActiveSection,
  toggleSectionVisibility,
  updateMenuSections,
  reorderSections,
  addCustomSection,
  settingsDrawer = null,
  onToggleSettingsDrawer,
}: SidePanelProps) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 space-y-4">
        {/* 设置触发条：展开模板 / 排版抽屉 */}
        {onToggleSettingsDrawer && (
          <SettingsSegmented settingsDrawer={settingsDrawer} onToggle={onToggleSettingsDrawer} />
        )}

        {/* 布局设置 */}
        <SettingCard icon={Layout} title="">
          <LayoutSetting
            menuSections={menuSections}
            activeSection={activeSection}
            setActiveSection={setActiveSection}
            toggleSectionVisibility={toggleSectionVisibility}
            updateMenuSections={updateMenuSections}
            reorderSections={reorderSections}
          />

          {/* 添加自定义模块按钮 */}
          <div className="space-y-2 py-4">
            <motion.button
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.9 }}
              onClick={addCustomSection}
              className="flex justify-center w-full rounded-none fresh:rounded-md items-center gap-2 py-2 px-3 text-sm font-medium text-slate-900 bg-blue-50/50 hover:bg-blue-100/50 border border-blue-100/50 transition-colors"
            >
              添加自定义模块
            </motion.button>
          </div>
        </SettingCard>
      </div>
    </div>
  )
}

export default SidePanel
