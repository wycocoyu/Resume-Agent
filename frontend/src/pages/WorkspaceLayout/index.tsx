/**
 * 工作区布局容器
 * 左侧固定边栏（工作区切换），右侧动态内容区
 */
import { useState, useEffect, useRef, type MouseEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Edit,
  FileText,
  Settings,
  ChevronDown,
  LogIn,
  LogOut,
  Bot,
  Shield,
  Sun,
  Moon,
  Zap,
  Palette,
  LayoutGrid,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/Avatar";
import { LATEST_CHANGELOG } from "@/data/changelog";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/hooks/useTheme";
import { getCurrentResumeId } from "@/services/resumeStorage";
import { RecentSessions } from "@/components/sidebar/RecentSessions";
import SkinPickerModal from "@/pages/Workspace/v2/components/SkinPickerModal";
import { canUseAdminFeature, getApiBaseUrl, useRuntimeFeatures } from "@/lib/runtimeEnv";
import { getAuthHeaders as buildAuthHeaders } from "@/lib/authHeaders";

// 工作区类型
type WorkspaceType =
  | "edit"
  | "agent"
  | "myResumes"
  | "settings"
  | "templates"
  | "admin";

function getAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return buildAuthHeaders(extra);
}

/** 复刻参考图：圆角矩形 + 内竖线（左窄右宽），细描边 */
function SidebarToggleIcon({
  expand = false,
  className,
}: {
  expand?: boolean;
  className?: string;
}) {
  const lineX = expand ? 17 : 7; // 展开态：线偏右；收起态：线偏左
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect x="2" y="4" width="20" height="16" rx="3" ry="3" />
      <line x1={lineX} y1="6" x2={lineX} y2="18" />
    </svg>
  );
}

export type AgentSessionHandlers = {
  currentSessionId: string | null;
  sessionsRefreshKey?: number;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  onDeleteSession: (sessionId: string) => Promise<void> | void;
  onRenameSession: (sessionId: string, title: string) => Promise<void> | void;
};

interface WorkspaceLayoutProps {
  children: React.ReactNode;
  agentSession?: AgentSessionHandlers;
}

export default function WorkspaceLayout({
  children,
  agentSession,
}: WorkspaceLayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, user, logout, openModal } = useAuth();
  const { isDark, setTheme } = useTheme();
  const [showLogoutMenu, setShowLogoutMenu] = useState(false);
  // 用户菜单「界面皮肤」入口：打开皮肤选择框（NEO / 清新）
  const [showSkinPicker, setShowSkinPicker] = useState(false);
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState(0);
  const logoutMenuRef = useRef<HTMLDivElement>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("workspace-sidebar-collapsed") === "1";
    } catch {
      return false;
    }
  });

  const toggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("workspace-sidebar-collapsed", next ? "1" : "0");
      } catch {}
      return next;
    });
  };

  // 根据路径确定当前工作区
  const getCurrentWorkspace = (): WorkspaceType => {
    if (
      location.pathname.startsWith("/workspace/agent") ||
      location.pathname.startsWith("/agent")
    ) {
      return "agent";
    }
    if (location.pathname === "/my-resumes") {
      return "myResumes";
    }
    if (location.pathname === "/settings") {
      return "settings";
    }
    if (location.pathname === "/admin") {
      return "admin";
    }
    if (location.pathname === "/templates") {
      return "templates";
    }
    // /workspace 及其子路径（/new、/:id、旧路由重定向）都算编辑区
    if (location.pathname.startsWith("/workspace")) {
      return "edit";
    }
    return "edit";
  };

  const currentWorkspace = getCurrentWorkspace();
  const { agentEnabled, authEnabled } = useRuntimeFeatures();
  const canUseAgent = isAuthenticated && agentEnabled;
  const canUseAdmin = isAuthenticated && canUseAdminFeature();

  const sidebarWidthPx = sidebarCollapsed ? 96 : 200;

  const navItemClass = (active: boolean) =>
    cn(
      "relative h-11 w-full border text-sm font-medium transition-[color,background-color,border-color] duration-150",
      "rounded-none fresh:rounded-lg font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] focus-visible:ring-inset",
      sidebarCollapsed
        ? "flex items-center justify-center px-0"
        : "flex items-center gap-3 px-3",
      active
        ? "border-black fresh:border-transparent bg-[#4285F4] fresh:bg-blue-50 text-white fresh:text-slate-900 dark:border-white dark:bg-[#2A2A2A] dark:text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-none dark:shadow-[2px_2px_0px_0px_#ffffff]"
        : "border-transparent text-slate-700 dark:text-slate-200 hover:bg-[#E5E5E0] fresh:hover:bg-slate-50 fresh:hover:text-slate-900 dark:hover:bg-[#2A2A2A]",
    );

  // 点击外部区域关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: globalThis.MouseEvent) => {
      if (
        logoutMenuRef.current &&
        !logoutMenuRef.current.contains(event.target as Node)
      ) {
        setShowLogoutMenu(false);
      }
    };

    if (showLogoutMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [showLogoutMenu]);

  const resolveWorkspacePath = (workspace: WorkspaceType): string => {
    if (workspace === "agent") {
      const currentResumeId = getCurrentResumeId();
      // 只有正在「编辑简历」页时进 AI 助手才带上当前简历（承接编辑上下文）；
      // 从我的简历 / 设置等其它页进则开新会话，不硬塞上一次编辑过的简历。
      const fromEditor = location.pathname.startsWith("/workspace");
      return currentResumeId && fromEditor
        ? `/agent/${currentResumeId}`
        : "/agent/new";
    }
    if (workspace === "myResumes") return "/my-resumes";
    if (workspace === "settings") return "/settings";
    if (workspace === "admin") return "/admin";
    if (workspace === "templates") return "/templates";
    // 「编辑简历」解析到具体简历：有 current 就带上 id 明确加载那一份，
    // 没有则明确新建——不再走裸 /workspace 依赖全局草稿「猜」要显示啥
    // （幽灵简历的温床）。current 若指向已删简历，编辑页加载失效兜底会
    // 重置为空白（见 useResumeData.resetEditorToBlank），不会显示旧简历。
    const editResumeId = getCurrentResumeId();
    return editResumeId ? `/workspace/${editResumeId}` : "/workspace/new";
  };

  const handleWorkspaceChange = (
    workspace: WorkspaceType,
    e?: MouseEvent<HTMLButtonElement>,
  ) => {
    const targetPath = resolveWorkspacePath(workspace);
    if (e?.metaKey || e?.ctrlKey) {
      window.open(targetPath, "_blank", "noopener,noreferrer");
      return;
    }
    navigate(targetPath);
  };

  const handleSelectSession = (sessionId: string) => {
    if (!canUseAgent) return;
    if (agentSession?.onSelectSession) {
      agentSession.onSelectSession(sessionId);
      return;
    }
    navigate(`/agent/new?sessionId=${sessionId}`, { replace: true });
  };

  const handleCreateSession = () => {
    if (!canUseAgent) return;
    if (agentSession?.onCreateSession) {
      agentSession.onCreateSession();
      return;
    }
    navigate("/agent/new", { state: { forceNew: Date.now() } });
  };

  const deleteSession = async (sessionId: string) => {
    if (!canUseAgent) return;
    if (agentSession?.onDeleteSession) {
      await agentSession.onDeleteSession(sessionId);
      return;
    }
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/api/agent/history/${sessionId}`,
        { method: "DELETE", headers: getAuthHeaders() },
      );
      if (!resp.ok) throw new Error(`Failed to delete session: ${resp.status}`);
      setSessionsRefreshKey((prev) => prev + 1);
    } catch (error) {
      console.error("Failed to delete session:", error);
    }
  };

  const renameSession = async (sessionId: string, title: string) => {
    if (!canUseAgent) return;
    if (agentSession?.onRenameSession) {
      await agentSession.onRenameSession(sessionId, title);
      return;
    }
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/api/agent/history/sessions/${sessionId}/title`,
        {
          method: "PUT",
          headers: getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ title }),
        },
      );
      if (!resp.ok) throw new Error(`Failed to rename session: ${resp.status}`);
      setSessionsRefreshKey((prev) => prev + 1);
    } catch (error) {
      console.error("Failed to rename session:", error);
    }
  };

  const sidebarCurrentSessionId =
    agentSession?.currentSessionId ??
    ((new URLSearchParams(location.search).get("sessionId") ||
      (location.pathname.startsWith("/agent/")
        ? location.pathname.split("/").pop()
        : null)) as string | null);

  const sidebarSessionsRefreshKey =
    agentSession?.sessionsRefreshKey ?? sessionsRefreshKey;

  return (
    <div className="flex h-dvh overflow-hidden bg-[#F0F0E8] font-sans selection:bg-[#4285F4] selection:text-white fresh:bg-slate-50 dark:bg-[#1C1C1C]">
      {/* 左侧固定边栏 */}
      <aside
        className={cn(
          "shrink-0 bg-[#F0F0E8] fresh:bg-white dark:bg-[#1C1C1C] border-r-2 fresh:border-r border-black fresh:border-slate-200 dark:border-white flex flex-col transition-[width] duration-200",
          sidebarCollapsed ? "w-24" : "w-[200px]",
        )}
      >
        {/* Logo + 收缩按钮：收起时合并，展开时并列 */}
        <div className="border-b-2 fresh:border-b border-black fresh:border-slate-200 dark:border-white shrink-0 px-3 py-2.5">
          {!sidebarCollapsed ? (
            <div className="flex h-9 items-center justify-between gap-2 w-full">
              <button
                type="button"
                className="group shrink-0 flex items-center gap-2.5 min-w-0 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4]"
                onClick={() => navigate("/")}
                aria-label="返回首页"
              >
                <div className="w-8 h-8 bg-[#4285F4] rounded-none fresh:rounded-md flex items-center justify-center border border-black fresh:border-blue-500 dark:border-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-none dark:shadow-[2px_2px_0px_0px_#ffffff] transition-colors group-hover:bg-[#3367D6] shrink-0">
                  <span className="text-white font-mono fresh:font-sans font-black text-xs not-italic">
                    CV
                  </span>
                </div>
                <span className="text-black dark:text-white font-mono fresh:font-hero font-bold text-sm uppercase fresh:normal-case tracking-wide fresh:tracking-tight truncate">
                  CocoCV
                </span>
              </button>
              <button
                type="button"
                onClick={toggleSidebar}
                className={cn(
                  "h-9 w-9 inline-flex items-center justify-center rounded-none fresh:rounded-md transition-colors shrink-0",
                  "text-slate-600 dark:text-slate-300 hover:bg-[#E5E5E0] fresh:hover:bg-slate-100 dark:hover:bg-[#2A2A2A]",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4]",
                )}
                title="收起侧边栏"
                aria-label="收起侧边栏"
              >
                <SidebarToggleIcon className="w-5 h-5" />
              </button>
            </div>
          ) : (
            <div className="relative group h-9 w-full flex items-center justify-center">
              {/* 收起态默认状态：仅 Logo */}
              <div className="flex items-center justify-center transition-opacity duration-200 group-hover:opacity-0 w-full">
                <div className="w-8 h-8 bg-[#4285F4] rounded-none fresh:rounded-md flex items-center justify-center border border-black fresh:border-blue-500 dark:border-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-none dark:shadow-[2px_2px_0px_0px_#ffffff] shrink-0">
                  <span className="text-white font-mono fresh:font-sans font-black text-xs not-italic">
                    CV
                  </span>
                </div>
              </div>

              {/* 收起态悬停状态：展开按钮 */}
              <button
                type="button"
                onClick={toggleSidebar}
                className="absolute inset-0 flex items-center justify-center rounded-none fresh:rounded-md opacity-0 group-hover:opacity-100 transition-all duration-200 bg-[#E5E5E0] fresh:bg-slate-100/90 dark:bg-[#2A2A2A]/90 text-black dark:text-white"
                title="展开侧边栏"
                aria-label="展开侧边栏"
              >
                <SidebarToggleIcon expand className="w-5 h-5" />
              </button>
            </div>
          )}
        </div>

        {/* 工作区切换：收缩时仅隐藏文字，图标与 padding 不变 */}
        <div className="flex-1 flex flex-col min-h-0 py-4 px-2.5">
          {!sidebarCollapsed && (
            <div className="mb-2 px-2 text-[11px] font-mono fresh:font-sans font-bold uppercase tracking-[0.14em] text-slate-500 fresh:tracking-wide">
              工作区
            </div>
          )}
          <nav
            className={cn(
              "space-y-1 flex flex-col shrink-0",
              sidebarCollapsed ? "items-center" : "",
            )}
            aria-label="工作区导航"
          >
            {/* 编辑区 */}
            <button
              onClick={(e) => handleWorkspaceChange("edit", e)}
              className={navItemClass(currentWorkspace === "edit")}
              title="编辑区"
              aria-current={currentWorkspace === "edit" ? "page" : undefined}
            >
              {currentWorkspace === "edit" && (
                <span className="absolute inset-y-2.5 left-0 hidden w-0.5 bg-[#4285F4] fresh:block fresh:rounded-r-full" />
              )}
              <Edit className={cn("w-5 h-5 shrink-0", currentWorkspace === "edit" && "text-white fresh:text-[#3367D6]")} />
              {!sidebarCollapsed && (
                <span>编辑简历</span>
              )}
            </button>

            {/* AI 对话区 */}
            {agentEnabled && (
              <button
                onClick={(e) => handleWorkspaceChange("agent", e)}
                className={navItemClass(currentWorkspace === "agent")}
                title="AI 助手"
                aria-current={currentWorkspace === "agent" ? "page" : undefined}
              >
                {currentWorkspace === "agent" && (
                  <span className="absolute inset-y-2.5 left-0 hidden w-0.5 bg-[#4285F4] fresh:block fresh:rounded-r-full" />
                )}
                <Bot className={cn("w-5 h-5 shrink-0", currentWorkspace === "agent" && "text-white fresh:text-[#3367D6]")} />
                {!sidebarCollapsed && (
                  <span>AI 助手</span>
                )}
              </button>
            )}

            {/* 我的简历 */}
            <button
              onClick={(e) => handleWorkspaceChange("myResumes", e)}
              className={navItemClass(currentWorkspace === "myResumes")}
              title="我的简历"
              aria-current={currentWorkspace === "myResumes" ? "page" : undefined}
            >
              {currentWorkspace === "myResumes" && (
                <span className="absolute inset-y-2.5 left-0 hidden w-0.5 bg-[#4285F4] fresh:block fresh:rounded-r-full" />
              )}
              <FileText className={cn("w-5 h-5 shrink-0", currentWorkspace === "myResumes" && "text-white fresh:text-[#3367D6]")} />
              {!sidebarCollapsed && (
                <span>我的简历</span>
              )}
            </button>

            {/* 模板广场 */}
            <button
              onClick={(e) => handleWorkspaceChange("templates", e)}
              className={navItemClass(currentWorkspace === "templates")}
              title="模板广场"
              aria-current={currentWorkspace === "templates" ? "page" : undefined}
            >
              {currentWorkspace === "templates" && (
                <span className="absolute inset-y-2.5 left-0 hidden w-0.5 bg-[#4285F4] fresh:block fresh:rounded-r-full" />
              )}
              <LayoutGrid className={cn("w-5 h-5 shrink-0", currentWorkspace === "templates" && "text-white fresh:text-[#3367D6]")} />
              {!sidebarCollapsed && (
                <span>模板广场</span>
              )}
            </button>

            {canUseAdmin && (
              <button
                onClick={(e) => handleWorkspaceChange("admin", e)}
                className={navItemClass(currentWorkspace === "admin")}
                title="后台管理系统"
                aria-current={currentWorkspace === "admin" ? "page" : undefined}
              >
                {currentWorkspace === "admin" && (
                  <span className="absolute inset-y-2.5 left-0 hidden w-0.5 bg-[#4285F4] fresh:block fresh:rounded-r-full" />
                )}
                <Shield className={cn("w-5 h-5 shrink-0", currentWorkspace === "admin" && "text-white fresh:text-[#3367D6]")} />
                {!sidebarCollapsed && (
                  <span>后台管理系统</span>
                )}
              </button>
            )}
          </nav>

          {/* 分隔线 */}
          {/* 历史会话 - 常驻显示 */}
          {!sidebarCollapsed && canUseAgent && (
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden border-t border-black fresh:border-slate-200 dark:border-white mt-3 pt-3">
              <RecentSessions
                currentSessionId={sidebarCurrentSessionId}
                onSelectSession={handleSelectSession}
                onCreateSession={handleCreateSession}
                onDeleteSession={deleteSession}
                onRenameSession={renameSession}
                refreshKey={sidebarSessionsRefreshKey}
              />
            </div>
          )}
        </div>

        {/* 底部：主题切换 + 登录组件（与导航风格统一） */}
        <div className="py-3 px-2.5 border-t-2 fresh:border-t border-black fresh:border-slate-200 dark:border-white">
          {/* 深色 / 浅色切换：仅管理员可见（登录态下移入用户下拉，未登录时保留此处） */}
          {!isAuthenticated && canUseAdminFeature() && (
            <button
              type="button"
              onClick={() => setTheme(isDark ? "light" : "dark")}
              className={cn(
                "w-full rounded-none fresh:rounded-md font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all duration-100 mb-2",
                "border border-black fresh:border-slate-200 dark:border-white bg-[#F0F0E8] fresh:bg-slate-50 dark:bg-[#2A2A2A] text-black dark:text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff] hover:bg-[#E5E5E0] dark:hover:bg-[#333333] hover:translate-x-[1px] fresh:hover:translate-x-0 hover:translate-y-[1px] fresh:hover:translate-y-0 hover:shadow-none fresh:hover:shadow-sm active:translate-x-[2px] active:translate-y-[2px]",
                sidebarCollapsed
                  ? "flex flex-col items-center justify-center gap-1 py-2.5"
                  : "flex items-center gap-2.5 py-2.5 px-2.5",
              )}
              title={isDark ? "切换到浅色模式" : "切换到深色模式"}
            >
              {isDark ? (
                <Sun className="w-5 h-5 shrink-0" />
              ) : (
                <Moon className="w-5 h-5 shrink-0" />
              )}
              {!sidebarCollapsed && (
                <span className="text-sm font-medium">
                  {isDark ? "浅色模式" : "深色模式"}
                </span>
              )}
            </button>
          )}

          <div ref={logoutMenuRef} className="relative">
            {isAuthenticated ? (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowLogoutMenu(!showLogoutMenu)}
                  className={cn(
                    "w-full rounded-none fresh:rounded-md transition-all duration-100 group",
                    "bg-[#F0F0E8] fresh:bg-slate-50 dark:bg-[#2A2A2A] border border-black fresh:border-slate-200 dark:border-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff] hover:bg-[#E5E5E0] dark:hover:bg-[#333333] hover:translate-x-[1px] fresh:hover:translate-x-0 hover:translate-y-[1px] fresh:hover:translate-y-0 hover:shadow-none fresh:hover:shadow-sm",
                    sidebarCollapsed
                      ? "flex flex-col items-center justify-center gap-1 py-3"
                      : "flex items-center gap-3 py-2 px-3",
                  )}
                  title={user?.username || user?.email}
                >
                  <Avatar
                    src={user?.image}
                    name={user?.username}
                    email={user?.email}
                    className="w-9 h-9 group-hover:bg-slate-200 dark:group-hover:bg-slate-700 transition-colors"
                    textClassName="text-sm"
                  />
                  {!sidebarCollapsed && (
                    <div className="flex flex-col items-start min-w-0 flex-1">
                      <span className="text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black dark:text-white truncate w-full text-left">
                        {user?.username || user?.email}
                      </span>
                    </div>
                  )}
                  {!sidebarCollapsed && (
                    <ChevronDown className={cn("w-3.5 h-3.5 text-black dark:text-white transition-transform duration-300", showLogoutMenu && "rotate-180")} />
                  )}
                </button>
                <AnimatePresence>
                  {showLogoutMenu && (
                    <motion.div
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      transition={{ duration: 0.2, ease: "easeOut" }}
                      className={cn(
                        "absolute bottom-full mb-3 bg-[#F0F0E8] fresh:bg-slate-50 dark:bg-[#1C1C1C] border border-black fresh:border-slate-200 dark:border-white rounded-none fresh:rounded-md shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md dark:shadow-[4px_4px_0px_0px_#ffffff] z-[110] p-1.5 min-w-[180px]",
                        sidebarCollapsed ? "left-0" : "left-0 right-0"
                      )}
                    >
                      <div className="px-3 py-2 border-b border-black fresh:border-slate-200 dark:border-white mb-1">
                        <p className="text-[10px] font-mono fresh:font-sans font-bold text-black dark:text-white uppercase fresh:normal-case tracking-wide fresh:tracking-normal">账号管理</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setShowLogoutMenu(false);
                          navigate("/account");
                        }}
                        className={cn(
                          "w-full flex items-center justify-between gap-2.5 px-3 py-2 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all",
                          "text-black dark:text-white hover:bg-[#E5E5E0] dark:hover:bg-[#2A2A2A]",
                        )}
                      >
                        <span className="flex items-center gap-2.5">
                          <Zap className="w-4 h-4 shrink-0 text-[#4285F4]" />
                          账户中心
                        </span>
                        {/* 额度数字 —— 额度迁移期间暂不展示 */}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          setShowLogoutMenu(false);
                          handleWorkspaceChange("settings");
                        }}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3 py-2 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all",
                          "text-black dark:text-white hover:bg-[#E5E5E0] dark:hover:bg-[#2A2A2A]",
                        )}
                      >
                        <Settings className="w-4 h-4 shrink-0" />
                        个人设置
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowLogoutMenu(false);
                          setShowSkinPicker(true);
                        }}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3 py-2 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all",
                          "text-black dark:text-white hover:bg-[#E5E5E0] dark:hover:bg-[#2A2A2A]",
                        )}
                      >
                        <Palette className="w-4 h-4 shrink-0" />
                        界面皮肤
                      </button>
                      {canUseAdmin && (
                        <button
                          type="button"
                          onClick={() => setTheme(isDark ? "light" : "dark")}
                          className={cn(
                            "w-full flex items-center gap-2.5 px-3 py-2 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all",
                            "text-black dark:text-white hover:bg-[#E5E5E0] dark:hover:bg-[#2A2A2A]",
                          )}
                        >
                          {isDark ? <Sun className="w-4 h-4 shrink-0" /> : <Moon className="w-4 h-4 shrink-0" />}
                          {isDark ? "浅色模式" : "深色模式"}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setShowLogoutMenu(false);
                          logout();
                        }}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3 py-2 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal transition-all",
                          "text-black dark:text-white hover:bg-red-700 hover:text-white",
                        )}
                      >
                        <LogOut className="w-4 h-4 shrink-0" />
                        退出登录
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ) : authEnabled ? (
                      <button
                        type="button"
                        onClick={() => openModal("login")}
                        className={cn(
                          "h-11 w-full rounded-none fresh:rounded-md transition-colors duration-150 font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal group",
                          "bg-white fresh:bg-transparent dark:bg-[#2A2A2A] text-slate-700 dark:text-slate-200 border border-black fresh:border-slate-200 dark:border-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-none dark:shadow-[2px_2px_0px_0px_#ffffff]",
                          "hover:bg-[#E5E5E0] fresh:hover:bg-slate-100 dark:hover:bg-[#333333] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] focus-visible:ring-inset",
                          sidebarCollapsed
                            ? "flex items-center justify-center"
                            : "flex items-center gap-3 px-3",
                        )}
                        title="登录 / 注册"
                      >
                        <LogIn className="w-4 h-4 shrink-0 text-[#3367D6]" />
                        {!sidebarCollapsed && (
                          <span className="text-sm font-medium">登录 / 注册</span>
                        )}
                      </button>
            ) : null}
          </div>
          {!sidebarCollapsed && (
            <div className="flex items-center justify-center gap-2 mt-2.5 px-2">
              <span className="text-[10px] font-mono fresh:font-sans font-medium text-black/45 dark:text-white/50 uppercase fresh:normal-case tracking-wide fresh:tracking-normal">VERSION {LATEST_CHANGELOG.version}</span>
            </div>
          )}
        </div>
      </aside>

      {/* 右侧内容区：限制最大宽度 = 展开侧边栏时的可用宽度，避免收缩时第三列 PDF 被拉宽 */}
      <main className="relative flex-1 flex flex-col overflow-hidden min-w-0">
        <div
          className="h-full w-full flex flex-col overflow-hidden transition-[max-width] duration-200"
          style={{
            width: "100%",
            maxWidth: `calc(100vw - ${sidebarWidthPx}px)`,
          }}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={currentWorkspace}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              className="h-full w-full flex flex-col"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* 用户菜单「界面皮肤」打开的皮肤选择框（portal 渲染，可点遮罩关闭） */}
      <SkinPickerModal
        open={showSkinPicker}
        onPicked={() => setShowSkinPicker(false)}
        onClose={() => setShowSkinPicker(false)}
      />
    </div>
  );
}
