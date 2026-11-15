/**
 * 编辑区三列布局（在 WorkspaceLayout 的基础上）：
 * 第一列：模块选择（窄，约 150px）
 * 第二列：详细编辑面板
 * 第三列：预览面板（可拖拽调整宽度）
 */
import { useState, useCallback, useRef, type ReactNode } from "react";
import { cn } from "../../../lib/utils";
import EditPanel from "./EditPanel";
import PreviewPanel from "./PreviewPanel";
import SidePanel from "./SidePanel";
import SettingsDrawer, { type SettingsDrawerTab } from "./SidePanel/SettingsDrawer";
import type {
  ResumeData,
  MenuSection,
  GlobalSettings,
  BasicInfo,
  Project,
  Experience,
  Education,
  OpenSource,
  Award,
  CustomItem,
} from "./types";
import type { PDFRenderMode } from "@/services/pdfRenderMode";
import { applyTemplatePreset, withSettingsDefaults } from "../../Builder/settings";
import type { TemplateSelection } from "./SidePanel";

interface EditPreviewLayoutProps {
  resumeData: ResumeData;
  setResumeData: (updater: ResumeData | ((prev: ResumeData) => ResumeData)) => void;
  activeSection: string;
  setActiveSection: (id: string) => void;
  toggleSectionVisibility: (id: string) => void;
  updateMenuSections: (sections: MenuSection[]) => void;
  reorderSections: (sections: MenuSection[]) => void;
  updateGlobalSettings: (settings: Partial<GlobalSettings>) => void;
  addCustomSection: () => void;
  updateBasicInfo: (info: Partial<BasicInfo>) => void;
  updateProject: (project: Project) => void;
  deleteProject: (id: string) => void;
  reorderProjects: (projects: Project[]) => void;
  updateExperience: (experience: Experience) => void;
  deleteExperience: (id: string) => void;
  reorderExperiences: (experiences: Experience[]) => void;
  updateWorkExperience?: (experience: Experience) => void;
  deleteWorkExperience?: (id: string) => void;
  reorderWorkExperiences?: (experiences: Experience[]) => void;
  updateEducation: (education: Education) => void;
  deleteEducation: (id: string) => void;
  reorderEducations: (educations: Education[]) => void;
  updateOpenSource: (openSource: OpenSource) => void;
  deleteOpenSource: (id: string) => void;
  reorderOpenSources: (openSources: OpenSource[]) => void;
  updateAward: (award: Award) => void;
  deleteAward: (id: string) => void;
  reorderAwards: (awards: Award[]) => void;
  addCustomItem: (sectionId: string) => void;
  updateCustomItem: (sectionId: string, item: CustomItem) => void;
  deleteCustomItem: (sectionId: string, itemId: string) => void;
  updateSelfEvaluation: (content: string) => void;
  updateSkillContent: (content: string) => void;
  handleAIImport: (section: string) => void;
  pdfBlob: Blob | null;
  loading: boolean;
  progress: string;
  renderError?: string | null;
  autoRenderPending?: boolean;
  renderMode?: PDFRenderMode;
  canUseRemoteRender?: boolean;
  setRenderMode?: (mode: PDFRenderMode) => void;
  handleRender: () => void;
  handleDownload: () => void;
  /** 顶栏操作按钮群(保存/皮肤/导入/导出),转发进预览工具栏右侧 */
  toolbarActions?: ReactNode;
}

// 拖拽分隔线组件（用 RAF 节流，避免高频 setState 导致抖动）
function DragHandle({
  onDragStart,
  onDragEnd,
  className,
}: {
  onDragStart?: (clientX: number) => void;
  onDragEnd?: () => void;
  className?: string;
}) {
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    onDragStart?.(e.clientX);
  }, [onDragStart]);

  return (
    <div
      className={cn(
        "w-1 cursor-ew-resize group relative shrink-0 transition-colors",
        "bg-slate-200 dark:bg-slate-800",
        "hover:bg-slate-400 dark:hover:bg-slate-600",
        "active:bg-slate-500 dark:active:bg-slate-500",
        className,
      )}
      style={{
        cursor: "ew-resize",
        touchAction: "none",
      }}
      onMouseDown={handleMouseDown}
    >
      {/* 扩大可点击区域 */}
      <div className="absolute inset-y-0 -left-2 -right-2 cursor-ew-resize" />
    </div>
  );
}

export default function EditPreviewLayout(props: EditPreviewLayoutProps) {
  const {
    resumeData,
    setResumeData,
    activeSection,
    setActiveSection,
    toggleSectionVisibility,
    updateMenuSections,
    reorderSections,
    updateGlobalSettings,
    addCustomSection,
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
    handleAIImport,
    pdfBlob,
    loading,
    progress,
    renderError,
    autoRenderPending,
    renderMode = "local",
    canUseRemoteRender = false,
    setRenderMode = () => {},
    handleRender,
    handleDownload,
    toolbarActions,
  } = props;

  // 统一模板选择：经典 → templateType='latex'；HTML 模板 → templateType='html' + builderSettings 应用预设
  const handleSelectTemplate = useCallback(
    (selection: TemplateSelection) => {
      setResumeData((prev) => {
        if (selection.type === "latex") {
          return prev.templateType === "html" ? { ...prev, templateType: "latex" as const } : prev;
        }
        const current = withSettingsDefaults(prev.globalSettings?.builderSettings);
        return {
          ...prev,
          templateType: "html" as const,
          globalSettings: {
            ...prev.globalSettings,
            builderSettings: applyTemplatePreset(current, selection.template) as unknown as Record<
              string,
              unknown
            >,
          },
        };
      });
    },
    [setResumeData],
  );

  // 列宽状态
  const [sidePanelWidth] = useState(280); // 模块选择列宽度（固定；抽屉方案下轨道收窄 300→280）
  const [editPanelWidth, setEditPanelWidth] = useState(700); // 编辑面板宽度（可拖动调整，范围 400-1400px）
  const [isDragging, setIsDragging] = useState(false);

  // 设置抽屉：null=收起；'template'/'format' 展开对应 tab。点同 tab 收起、异 tab 切换
  const [settingsDrawer, setSettingsDrawer] = useState<SettingsDrawerTab | null>(null);
  const toggleSettingsDrawer = useCallback((tab: SettingsDrawerTab) => {
    setSettingsDrawer((prev) => (prev === tab ? null : tab));
  }, []);
  const closeSettingsDrawer = useCallback(() => setSettingsDrawer(null), []);
  const dragStateRef = useRef<{ startX: number; startWidth: number; currentWidth: number } | null>(null);
  const clickEditPanelRef = useRef<HTMLDivElement | null>(null);

  // 拖拽处理 - 调整编辑面板宽度
  const clampEditPanelWidth = useCallback((width: number) => {
    return Math.max(400, Math.min(1400, width));
  }, []);

  const applyEditPanelWidth = useCallback((width: number) => {
    if (clickEditPanelRef.current) {
      clickEditPanelRef.current.style.width = `${width}px`;
    }
  }, []);

  const handleDragStart = useCallback((clientX: number) => {
    dragStateRef.current = {
      startX: clientX,
      startWidth: editPanelWidth,
      currentWidth: editPanelWidth,
    };
    setIsDragging(true);
  }, [editPanelWidth]);

  const handleDragMove = useCallback((clientX: number) => {
    const dragState = dragStateRef.current;
    if (!dragState) return;
    const delta = clientX - dragState.startX;
    const nextWidth = clampEditPanelWidth(dragState.startWidth + delta);
    dragState.currentWidth = nextWidth;
    // 拖动中直接改 DOM，避免每一帧 React 重渲染导致“弹来弹去”
    applyEditPanelWidth(nextWidth);
  }, [applyEditPanelWidth, clampEditPanelWidth]);

  const handleDragEnd = useCallback(() => {
    const dragState = dragStateRef.current;
    if (dragState) {
      setEditPanelWidth(dragState.currentWidth);
    }
    setIsDragging(false);
    dragStateRef.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  const handleEngineChange = useCallback((engine: 'latex' | 'html') => {
    setResumeData((prev) => {
      if (prev.templateType === engine) return prev;
      return { ...prev, templateType: engine };
    });
    try {
      localStorage.setItem('cococv_preferred_render_engine', engine);
    } catch {}
    if (engine === 'latex' && !pdfBlob) {
      handleRender();
    }
  }, [setResumeData, pdfBlob, handleRender]);

  return (
    <div className="flex-1 min-h-0 flex relative z-10 overflow-hidden min-w-0">
      {/* 内容区域 */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex">
              {/* 编辑区：三列布局 */}
              {/* 第一列：模块选择（窄） */}
              <div
                className={cn(
                  "h-full overflow-y-auto shrink-0",
                  "bg-[#F6F3EC] fresh:bg-white dark:bg-slate-900/80",
                  "backdrop-blur-sm fresh:backdrop-blur-none border-r border-slate-200 dark:border-slate-800",
                )}
                style={{ width: sidePanelWidth }}
              >
                <SidePanel
                  menuSections={resumeData.menuSections}
                  activeSection={activeSection}
                  globalSettings={resumeData.globalSettings}
                  setActiveSection={setActiveSection}
                  toggleSectionVisibility={toggleSectionVisibility}
                  updateMenuSections={updateMenuSections}
                  reorderSections={reorderSections}
                  updateGlobalSettings={updateGlobalSettings}
                  addCustomSection={addCustomSection}
                  settingsDrawer={settingsDrawer}
                  onToggleSettingsDrawer={toggleSettingsDrawer}
                />
              </div>

              {/* 分隔线 1 */}
              <div className="w-px bg-slate-200 dark:bg-slate-700 shrink-0" />

              {/* 第二列：编辑面板（固定宽度，拖拽时启用 GPU 合成避免抖动） */}
              <div
                ref={clickEditPanelRef}
                className={cn(
                  "h-full overflow-y-auto shrink-0",
                  "bg-white/80 fresh:bg-white dark:bg-slate-900/80",
                  "backdrop-blur-sm fresh:backdrop-blur-none border-r border-slate-200 dark:border-slate-800",
                )}
                style={{
                  width: editPanelWidth,
                  transition: "none",
                }}
              >
                <EditPanel
                  key={activeSection}
                  activeSection={activeSection}
                  menuSections={resumeData.menuSections}
                  resumeData={resumeData}
                  updateBasicInfo={updateBasicInfo}
                  updateProject={updateProject}
                  deleteProject={deleteProject}
                  reorderProjects={reorderProjects}
                  updateExperience={updateExperience}
                  deleteExperience={deleteExperience}
                  reorderExperiences={reorderExperiences}
                  updateWorkExperience={updateWorkExperience}
                  deleteWorkExperience={deleteWorkExperience}
                  reorderWorkExperiences={reorderWorkExperiences}
                  updateEducation={updateEducation}
                  deleteEducation={deleteEducation}
                  reorderEducations={reorderEducations}
                  updateOpenSource={updateOpenSource}
                  deleteOpenSource={deleteOpenSource}
                  reorderOpenSources={reorderOpenSources}
                  updateAward={updateAward}
                  deleteAward={deleteAward}
                  reorderAwards={reorderAwards}
                  addCustomItem={addCustomItem}
                  updateCustomItem={updateCustomItem}
                  deleteCustomItem={deleteCustomItem}
                  updateSelfEvaluation={updateSelfEvaluation}
                  updateSkillContent={updateSkillContent}
                  updateMenuSections={updateMenuSections}
                  setResumeData={setResumeData}
                  updateGlobalSettings={updateGlobalSettings}
                  onAIImport={handleAIImport}
                />
              </div>

              {/* 分隔线 2（可拖拽调整编辑面板宽度） */}
              <DragHandle
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
              />
          </div>

        {/* 预览面板（始终显示；拖拽时禁用指针避免 iframe 抢占事件） */}
        <div
          className={cn(
            "h-full overflow-hidden flex-1",
            "bg-[#F6F3EC] fresh:bg-slate-100",
          )}
          style={{ pointerEvents: isDragging ? "none" : "auto" }}
        >
          <PreviewPanel
            resumeData={resumeData}
            pdfBlob={pdfBlob}
            loading={loading}
            progress={progress}
            renderError={renderError}
            autoRenderPending={autoRenderPending}
            renderMode={renderMode}
            canUseRemoteRender={canUseRemoteRender}
            onRenderModeChange={setRenderMode}
            onRender={handleRender}
            onDownload={handleDownload}
            onEngineChange={handleEngineChange}
            toolbarActions={toolbarActions}
          />
        </div>
      </div>

      {/* 设置抽屉：覆盖层（z-20，低于列宽拖拽遮罩层 z-[9999]），盖住轨道 + EditPanel 左半，预览始终露出 */}
      <SettingsDrawer
        activeTab={settingsDrawer}
        onToggleTab={toggleSettingsDrawer}
        onClose={closeSettingsDrawer}
        overlayWidth={sidePanelWidth + 1 + editPanelWidth}
        trackWidth={sidePanelWidth}
        templateType={resumeData.templateType}
        globalSettings={resumeData.globalSettings}
        onSelectTemplate={handleSelectTemplate}
        updateGlobalSettings={updateGlobalSettings}
      />

      {/* 拖拽遮罩层：拖动时拦截全屏鼠标事件，避免预览 iframe 抢事件导致宽度回弹 */}
      {isDragging && (
        <div
          className="fixed inset-0 z-[9999] cursor-ew-resize"
          onMouseMove={(e) => handleDragMove(e.clientX)}
          onMouseUp={handleDragEnd}
        />
      )}
    </div>
  );
}
