/**
 * 编辑面板组件（第二列）
 * 根据当前选中的模块动态渲染对应的编辑面板
 */
import { useState } from 'react'
import { Pencil, Check, X } from 'lucide-react'
import { cn } from '../../../../lib/utils'
import type { MenuSection, ResumeData, BasicInfo, Project, Experience, Education, OpenSource, Award, CustomItem, GlobalSettings } from '../types'
import BasicPanel from './BasicPanel'
import ProjectPanel from './ProjectPanel'
import ExperiencePanel from './ExperiencePanel'
import EducationPanel from './EducationPanel'
import SkillPanel from './SkillPanel'
import SelfEvaluationPanel from './SelfEvaluationPanel'
import OpenSourcePanel from './OpenSourcePanel'
import AwardPanel from './AwardPanel'
import CustomPanel from './CustomPanel'

interface EditPanelProps {
  activeSection: string
  menuSections: MenuSection[]
  resumeData: ResumeData
  // 更新回调
  updateBasicInfo: (data: Partial<BasicInfo>) => void
  updateProject: (project: Project) => void
  deleteProject: (id: string) => void
  reorderProjects: (projects: Project[]) => void
  updateExperience: (experience: Experience) => void
  deleteExperience: (id: string) => void
  reorderExperiences: (experiences: Experience[]) => void
  updateWorkExperience?: (experience: Experience) => void
  deleteWorkExperience?: (id: string) => void
  reorderWorkExperiences?: (experiences: Experience[]) => void
  updateEducation: (education: Education) => void
  deleteEducation: (id: string) => void
  reorderEducations: (educations: Education[]) => void
  updateOpenSource: (openSource: OpenSource) => void
  deleteOpenSource: (id: string) => void
  reorderOpenSources: (openSources: OpenSource[]) => void
  updateAward: (award: Award) => void
  deleteAward: (id: string) => void
  reorderAwards: (awards: Award[]) => void
  addCustomItem: (sectionId: string) => void
  updateCustomItem: (sectionId: string, item: CustomItem) => void
  deleteCustomItem: (sectionId: string, itemId: string) => void
  updateSelfEvaluation: (content: string) => void
  updateSkillContent: (content: string) => void
  updateMenuSections: (sections: MenuSection[]) => void
  setResumeData: (updater: import('../types').ResumeData | ((prev: import('../types').ResumeData) => import('../types').ResumeData)) => void
  updateGlobalSettings: (settings: Partial<GlobalSettings>) => void
  // AI 导入回调
  onAIImport?: (section: string) => void
}

export function EditPanel({
  activeSection,
  menuSections,
  resumeData,
  updateBasicInfo,
  updateProject,
  deleteProject,
  reorderProjects,
  updateExperience,
  deleteExperience,
  reorderExperiences,
  updateWorkExperience,
  deleteWorkExperience,
  reorderWorkExperiences,
  updateEducation,
  deleteEducation,
  reorderEducations,
  updateOpenSource,
  deleteOpenSource,
  reorderOpenSources,
  updateAward,
  deleteAward,
  reorderAwards,
  addCustomItem,
  updateCustomItem,
  deleteCustomItem,
  updateSelfEvaluation,
  updateSkillContent,
  updateMenuSections,
  setResumeData,
  updateGlobalSettings,
  onAIImport,
}: EditPanelProps) {
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [editTitle, setEditTitle] = useState('')

  // 获取当前模块信息
  const currentSection = menuSections.find((s) => s.id === activeSection)

  // 点击铅笔图标进入编辑模式
  const handleEditClick = () => {
    setEditTitle(currentSection?.title || '')
    setIsEditingTitle(true)
  }

  // 确认编辑：直接用 setResumeData 函数式更新，避免闭包捕获旧 menuSections
  const handleConfirm = () => {
    setResumeData((prev) => ({
      ...prev,
      menuSections: prev.menuSections.map((s) =>
        s.id === activeSection ? { ...s, title: editTitle } : s
      ),
    }))
    setIsEditingTitle(false)
  }

  // 取消编辑
  const handleCancel = () => {
    setIsEditingTitle(false)
    setEditTitle('')
  }

  // 处理 Enter 和 Escape 快捷键
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleConfirm()
    } else if (e.key === 'Escape') {
      handleCancel()
    }
  }

  // 根据 activeSection 渲染对应面板
  const renderFields = () => {
    switch (activeSection) {
      case 'basic':
        return (
          <BasicPanel
            basic={resumeData.basic}
            onUpdate={updateBasicInfo}
            globalSettings={resumeData.globalSettings}
            updateGlobalSettings={updateGlobalSettings}
          />
        )

      case 'skills':
        return (
          <SkillPanel
            skillContent={resumeData.skillContent}
            onUpdate={updateSkillContent}
            onAIImport={onAIImport ? () => onAIImport('skills') : undefined}
            resumeData={resumeData}
          />
        )

      case 'selfEvaluation':
        return (
          <SelfEvaluationPanel
            content={resumeData.selfEvaluation}
            onUpdate={updateSelfEvaluation}
            onAIImport={onAIImport ? () => onAIImport('selfEvaluation') : undefined}
            resumeData={resumeData}
          />
        )

      case 'workExperience':
        return (
          <ExperiencePanel
            experiences={resumeData.workExperience || []}
            onUpdate={updateWorkExperience || updateExperience}
            onDelete={deleteWorkExperience || deleteExperience}
            onReorder={reorderWorkExperiences || reorderExperiences}
            globalSettings={resumeData.globalSettings}
            updateGlobalSettings={updateGlobalSettings}
            onAIImport={onAIImport ? () => onAIImport('workExperience') : undefined}
            resumeData={resumeData}
          />
        )

      case 'experience':
        return (
          <ExperiencePanel
            experiences={resumeData.experience}
            onUpdate={updateExperience}
            onDelete={deleteExperience}
            onReorder={reorderExperiences}
            globalSettings={resumeData.globalSettings}
            updateGlobalSettings={updateGlobalSettings}
            onAIImport={onAIImport ? () => onAIImport('experience') : undefined}
            resumeData={resumeData}
          />
        )

      case 'projects':
        return (
          <ProjectPanel
            projects={resumeData.projects}
            onUpdate={updateProject}
            onDelete={deleteProject}
            onReorder={reorderProjects}
            onAIImport={onAIImport ? () => onAIImport('projects') : undefined}
            resumeData={resumeData}
            globalSettings={resumeData.globalSettings}
            updateGlobalSettings={updateGlobalSettings}
          />
        )

      case 'education':
        return (
          <EducationPanel
            educations={resumeData.education}
            onUpdate={updateEducation}
            onDelete={deleteEducation}
            onReorder={reorderEducations}
            onAIImport={onAIImport ? () => onAIImport('education') : undefined}
            resumeData={resumeData}
          />
        )

      case 'openSource':
        return (
          <OpenSourcePanel
            openSources={resumeData.openSource || []}
            onUpdate={updateOpenSource}
            onDelete={deleteOpenSource}
            onReorder={reorderOpenSources}
            onAIImport={onAIImport ? () => onAIImport('openSource') : undefined}
            globalSettings={resumeData.globalSettings}
            updateGlobalSettings={updateGlobalSettings}
            resumeData={resumeData}
          />
        )

      case 'awards':
        return (
          <AwardPanel
            awards={resumeData.awards || []}
            onUpdate={updateAward}
            onDelete={deleteAward}
            onReorder={reorderAwards}
            onAIImport={onAIImport ? () => onAIImport('awards') : undefined}
            awardsListType={resumeData.globalSettings?.awardsListType || 'unordered'}
            onChangeAwardsListType={(type) => updateGlobalSettings({ awardsListType: type })}
          />
        )

      default:
        if (activeSection?.startsWith('custom')) {
          const items = resumeData.customData[activeSection] || []
          return (
            <CustomPanel
              sectionId={activeSection}
              items={items}
              onCreate={addCustomItem}
              onUpdate={updateCustomItem}
              onDelete={deleteCustomItem}
            />
          )
        }
        return <BasicPanel basic={resumeData.basic} onUpdate={updateBasicInfo} />
    }
  }

  return (
    <div
      className={cn(
        'h-full border-r overflow-y-auto overflow-x-hidden',
        'bg-[#F6F3EC] border-black fresh:bg-[#F1F2F5] fresh:border-slate-200',
        'dark:bg-[#1C1C1C] dark:border-white'
      )}
    >
      <div className="p-4">
        {/* 模块标题 */}
        <div
          className={cn(
            'mb-4 p-4 rounded-none border fresh:border-x-0 fresh:border-t-0',
            'bg-white fresh:bg-transparent border-black fresh:border-slate-200',
            'dark:bg-[#1C1C1C] dark:border-white'
          )}
        >
          <div className="flex items-center gap-2">
            <span className="text-lg">{currentSection?.icon}</span>

            {activeSection === 'basic' ? (
              <span className="text-lg font-semibold text-primary">
                {currentSection?.title}
              </span>
            ) : isEditingTitle ? (
              <div className="flex items-center flex-1 gap-2">
                <input
                  autoFocus
                  className={cn(
                    'flex-1 text-lg font-medium bg-transparent outline-none text-primary',
                    'border-b-2 border-primary pb-1',
                    'px-2 py-1'
                  )}
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  onClick={handleConfirm}
                  className="text-green-600 hover:text-green-700 flex-shrink-0 transition-colors"
                  title="确认"
                >
                  <Check size={18} />
                </button>
                <button
                  onClick={handleCancel}
                  className="text-red-600 hover:text-red-700 flex-shrink-0 transition-colors"
                  title="取消"
                >
                  <X size={18} />
                </button>
              </div>
            ) : (
              <div className="flex items-center flex-1 gap-2">
                <span
                  onClick={handleEditClick}
                  className="text-lg font-semibold text-primary flex-1 cursor-pointer hover:opacity-70 transition-opacity"
                  title="点击编辑标题"
                >
                  {currentSection?.title}
                </span>
                <button
                  onClick={handleEditClick}
                  className="text-primary hover:text-primary/80 flex-shrink-0 transition-colors"
                  title="编辑标题"
                >
                  <Pencil size={18} />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 编辑面板内容 */}
        <div
          className={cn(
            'rounded-none fresh:rounded-md',
            'bg-white border-black fresh:border-slate-200',
            'dark:bg-[#1C1C1C] dark:border-white'
          )}
        >
          {renderFields()}
        </div>
      </div>
    </div>
  )
}

export default EditPanel
