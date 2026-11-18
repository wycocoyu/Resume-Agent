import { toast } from '@/lib/toast'
/**
 * AgentChat - 对话页面
 *
 * 使用 SSE (Server-Sent Events) 替代 WebSocket
 *
 * 功能：
 * - AI 输出的 Thought Process（来自后端，折叠面板样式）
 * - 流式输出和打字机效果
 * - Markdown 渲染
 * - 心跳检测和自动重连
 */

import ResumeSelector from "@/components/chat/ResumeSelector";
import SearchResultPanel from "@/components/chat/SearchResultPanel";
import { RecentSessions } from "@/components/sidebar/RecentSessions";
import { useAuth } from "@/contexts/AuthContext";
import { useEnvironment } from "@/contexts/EnvironmentContext";
import { useCLTP } from "@/hooks/useCLTP";
import { useRuntimeFeatures } from "@/lib/runtimeEnv";
import { uploadResumeImageStream } from "@/lib/uploadResumeImageStream";
import { getAuthHeaders as buildAuthHeaders } from "@/lib/authHeaders";
import { hasHeroHandoffImages, takeHeroHandoffImages } from "@/lib/heroHandoff";
import { JdOptimizeChatCard } from "@/components/agent-chat/JdOptimizeChatCard";
import {
  getSessionLimitMessage,
  isSessionLimitExceededResponse,
} from "@/utils/sessionLimits";
import AgentPdfPreviewPanel from "@/components/agent-chat/AgentPdfPreviewPanel";
import { convertToBackendFormat } from "@/pages/Workspace/v2/utils/convertToBackend";
import {
  DEFAULT_MENU_SECTIONS,
  type ResumeData,
} from "@/pages/Workspace/v2/types";
import {
  getResume,
  getAllResumes,
  saveResume,
  setCurrentResumeId,
  syncLocalResumesToCurrentAccount,
} from "@/services/resumeStorage";
import { parseResumeText } from "@/services/resumeParse";
import { highlightsToHtml, groupedHighlightsToHtml, skillsToHtml } from "@/utils/resumeRichtext";
import type { SavedResume } from "@/services/storage/StorageAdapter";
import {
  renderPDFStream,
} from "@/services/api";
import { Message, MessageMeta, type AgentProcessNode } from "@/types/chat";
import type { SSEEvent } from "@/transports/SSETransport";
import {
  Sparkles,
  MessageSquare,
  Bot,
  KeyRound,
} from "lucide-react";
import ChatEmptyState from "@/components/agent-chat/ChatEmptyState";
import ModelSelector, { AGENT_MODELS, DEFAULT_AGENT_MODEL } from "@/components/agent-chat/ModelSelector";
import ByokConfigModal from "@/components/agent-chat/ByokConfigModal";
import {
  BYOK_STORAGE_KEY,
  BYOK_UPDATED_EVENT,
  getAgentRequestHeaders,
  isByokActive,
  loadByokConfig,
  type ByokConfig,
} from "@/services/agentByokConfig";
import {
  appendLocalAgentMessages,
  deleteLocalAgentSession,
  getLocalAgentSession,
  renameLocalAgentSession,
  saveLocalAgentSession,
} from "@/services/agentLocalHistory";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import EnhancedMarkdown from "@/components/chat/EnhancedMarkdown";
import Composer from "@/components/agent-chat/Composer";
import MessageTimeline from "@/components/agent-chat/MessageTimeline";
import ConversationFeedbackBar from "@/components/agent-chat/ConversationFeedbackBar";
import { buildApplyDecisionCopy, buildRejectDecisionCopy } from "@/pages/AgentChat/applyDecisionCopy";
import StreamingLane, {
  buildVisibleConversationRun,
} from "@/components/agent-chat/StreamingLane";
import type { StructuredEventData } from "@/components/agent-chat/StructuredCardRegistry";
import type { DiagnosisToolStructuredData } from "@/types/resumeDiagnosis";
import type { AskQuestionAnswer } from "@/components/agent-chat/AskQuestionContext";
import { useTextStream } from "@/hooks/useTextStream";
import { useToolEventRouter } from "@/hooks/agent-chat/useToolEventRouter";
import { useStreamRunController } from "@/hooks/agent-chat/useStreamRunController";
import { useMessageTimeline } from "@/hooks/agent-chat/useMessageTimeline";
import {
  extractResumeEditDiff as extractResumeEditDiffFromMarkdown,
  normalizeResumePatchValue,
  stripResumeEditMarkdown,
} from "@/utils/resumePatch";
import { classifyStructuredToolPresentation } from "@/utils/toolPresentation";
import {
  buildConversationTurnSnapshot,
  parseConversationTurnSnapshotMap,
} from "@/agent-presentation/ConversationSnapshotAdapter";
import type {
  ConversationRunState,
  ConversationTurnSnapshot,
} from "@/agent-presentation/model";
import { projectLegacyProcessNodes } from "@/agent-presentation/LegacyPresentationAdapter";

import WorkspaceLayout from "@/pages/WorkspaceLayout";
import CustomScrollbar from "@/components/common/CustomScrollbar";
import { useResumeContext, type PendingPatch } from '../../contexts/ResumeContext';
import AIImportModal from "@/pages/Workspace/v2/shared/AIImportModal";

// 报告内容视图组件
// ============================================================================
// 配置（运行时 API 基地址由 useEnvironment 提供，不再使用构建时常量）
// ============================================================================

const SSE_HEARTBEAT_TIMEOUT = 60000; // 60 seconds
// 业务静默超时：多久没收到任何真实业务事件（thought/answer/tool 等，
// 不含后端心跳字节）就判定"LLM 迟迟不返回"并主动断开。整份优化场景下
// token 膨胀会拉长 qwen-max 首字节延迟，实测日志里正常返回也有 55s 的
// case，120s 留出比原方案更宽松的余量，避免误伤慢但正常的响应。
const SSE_MEANINGFUL_TIMEOUT = 120000; // 120 seconds
const HISTORY_APPEND_MODE =
  String(import.meta.env.VITE_AGENT_HISTORY_APPEND_MODE ?? "true").toLowerCase() !==
  "false";

function convertResumeDataToOpenManusFormat(resume: ResumeData) {
  return {
    ...resume,
  };
}

interface ResumePdfPreviewState {
  blob: Blob | null;
  loading: boolean;
  progress: string;
  error: string | null;
}

const EMPTY_RESUME_PDF_STATE: ResumePdfPreviewState = {
  blob: null,
  loading: false,
  progress: "",
  error: null,
};

function toText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  return "";
}

function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => toText(item)).filter((item) => item.length > 0);
  }
  const text = toText(value);
  return text ? [text] : [];
}

function splitDateRange(rawDate: string): {
  startDate: string;
  endDate: string;
} {
  const date = rawDate.trim();
  if (!date) return { startDate: "", endDate: "" };
  const parts = date.split(/\s*[-~至]\s*/).filter(Boolean);
  if (parts.length >= 2) {
    return { startDate: parts[0], endDate: parts.slice(1).join(" - ") };
  }
  return { startDate: date, endDate: "" };
}

/**
 * 发送前对「一堆连续文字」做轻量结构化：把数字编号、仓库标签拆成换行，
 * 既让对话气泡更易读，也让 Agent 更容易解析（例如把项目名/社区名识别出来）。
 * 仅对含编号或「仓库：」标签的较长文本生效，避免误伤普通短消息和小数（2025.06）。
 */
function formatChatInput(text: string): string {
  const looksStructured =
    /\d+\s*[.、]\s*[一-龥A-Za-z]/.test(text) || /仓库\s*[:：]/.test(text);
  if (!looksStructured || text.length < 40) return text;
  return text
    .replace(/\s+(?=\d+\s*[.、]\s*[^\d\s])/g, "\n")
    .replace(/\s+(?=仓库\s*[:：])/g, "\n")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

function normalizeImportedResumeToCanonical(
  source: Record<string, any>,
  opts: { resumeId: string; title: string },
): ResumeData {
  const now = new Date().toISOString();
  const contact = (source.contact || {}) as Record<string, unknown>;
  const educationRaw = Array.isArray(source.education) ? source.education : [];
  const internshipsRaw = Array.isArray(source.internships)
    ? source.internships
    : [];
  const experienceRaw = Array.isArray(source.experience)
    ? source.experience
    : [];
  const projectsRaw = Array.isArray(source.projects) ? source.projects : [];
  const openSourceRaw = Array.isArray(source.openSource)
    ? source.openSource
    : Array.isArray(source.opensource)
      ? source.opensource
      : Array.isArray(source.open_source)
        ? source.open_source
        : [];
  const awardsRaw = Array.isArray(source.awards) ? source.awards : [];
  const skillsRaw = Array.isArray(source.skills) ? source.skills : [];
  const workList = internshipsRaw.length > 0 ? internshipsRaw : experienceRaw;

  const education = educationRaw.map((item: any, index: number) => {
    const title = toText(item?.title || item?.school || item?.name);
    const subtitle = toText(item?.subtitle || item?.major || item?.field);
    const degree = toText(item?.degree);
    const date = toText(item?.date);
    const details = toStringList(item?.details || item?.highlights);
    const range = splitDateRange(date);
    const descriptionText = toText(item?.description);
    return {
      id: item?.id || `edu_${opts.resumeId}_${index}`,
      school: title,
      major: subtitle,
      degree,
      startDate: range.startDate || toText(item?.startDate),
      endDate: range.endDate || toText(item?.endDate),
      description: details.length
        ? highlightsToHtml(details)
        : descriptionText
          ? `<p>${descriptionText}</p>`
          : "",
      visible: true,
    };
  });

  const experience = workList.map((item: any, index: number) => {
    const company = toText(item?.title || item?.company || item?.organization);
    const position = toText(item?.subtitle || item?.position || item?.role);
    const date = toText(item?.date || item?.duration);
    const highlights = toStringList(item?.highlights || item?.details);
    return {
      id: item?.id || `exp_${opts.resumeId}_${index}`,
      company,
      position,
      date,
      details: highlightsToHtml(highlights),
      visible: true,
      companyLogo: toText(item?.logo) || undefined,
      companyLogoSize:
        typeof item?.logoSize === "number" ? item.logoSize : undefined,
    };
  });

  const projects = projectsRaw.map((item: any, index: number) => {
    const name = toText(item?.title || item?.name);
    const role = toText(item?.subtitle || item?.role);
    const date = toText(item?.date);
    const highlights = toStringList(item?.highlights);
    const description = toText(item?.description);
    const htmlParts = [
      description ? `<p>${description}</p>` : "",
      highlights.length ? highlightsToHtml(highlights) : "",
    ].filter(Boolean);
    return {
      id: item?.id || `proj_${opts.resumeId}_${index}`,
      name,
      role,
      date,
      description: htmlParts.join(""),
      visible: true,
      link: toText(item?.link || item?.repoUrl || item?.repo) || undefined,
    };
  });

  const openSource = openSourceRaw.map((item: any, index: number) => {
    const repoItems = toStringList(item?.items || item?.highlights);
    const baseDescription = toText(item?.description);
    const description = [
      baseDescription ? `<p>${baseDescription}</p>` : "",
      repoItems.length ? groupedHighlightsToHtml(repoItems) : "",
    ]
      .filter(Boolean)
      .join("");
    return {
      id: item?.id || `os_${opts.resumeId}_${index}`,
      name: toText(item?.title || item?.name),
      repo: toText(item?.repoUrl || item?.repo) || undefined,
      role: toText(item?.subtitle || item?.role) || undefined,
      date: toText(item?.date) || undefined,
      description,
      visible: true,
    };
  });

  const awards = awardsRaw.map((item: any, index: number) => {
    if (typeof item === "string") {
      return {
        id: `award_${opts.resumeId}_${index}`,
        title: item,
        issuer: "",
        date: "",
        description: "",
        visible: true,
      };
    }
    return {
      id: item?.id || `award_${opts.resumeId}_${index}`,
      title: toText(item?.title || item?.name),
      issuer: toText(item?.issuer || item?.organization),
      date: toText(item?.date),
      description: toText(item?.description),
      visible: true,
    };
  });

  // 专业技能统一转成无序列表 HTML（对象数组 / 字符串都走同一个共享转换，
  // 与其它导入路径 / Agent 编辑链路一致）
  const skillContentFromArray = skillsToHtml(
    skillsRaw.length ? skillsRaw : source.skills,
  );

  return {
    id: opts.resumeId,
    title: opts.title,
    createdAt: toText(source.createdAt) || now,
    updatedAt: now,
    templateId: null,
    templateType: "latex",
    basic: {
      name: toText(source.basic?.name || source.name),
      title: toText(source.basic?.title || source.objective || source.summary),
      email: toText(source.basic?.email || contact.email),
      phone: toText(source.basic?.phone || contact.phone),
      location: toText(source.basic?.location || contact.location),
    },
    education,
    experience,
    projects,
    openSource,
    awards,
    customData: {},
    selfEvaluation: toText(source.selfEvaluation)
      ? toText(source.selfEvaluation)
      : (toText(source.summary) ? `<p>${toText(source.summary)}</p>` : ""),
    skillContent: toText(source.skillContent) || skillContentFromArray,
    activeSection: "basic",
    draggingProjectId: null,
    menuSections: DEFAULT_MENU_SECTIONS.map((section, index) => ({
      ...section,
      order: index,
    })),
    globalSettings: {},
  };
}

export function isWorkspaceResumeData(data: unknown): data is ResumeData {
  if (!data || typeof data !== "object") return false;
  const candidate = data as Partial<ResumeData>;
  return (
    !!candidate.basic &&
    Array.isArray(candidate.education) &&
    Array.isArray(candidate.experience) &&
    Array.isArray(candidate.projects) &&
    Array.isArray(candidate.menuSections)
  );
}

/** 进入 loadedResumes / PDF 预览链路的简历统一成 canonical：
 *  已是工作台格式则原样返回（normalize 对 canonical 有损——canonical 的
 *  description 已是 HTML，重复转换会二次包 <p>，故必须守卫先行，不可无脑转换），
 *  否则按 applyResumeToChat 同款范式补 menuSections 等字段。 */
export function toCanonicalResumeData(
  raw: Record<string, any>,
  resumeId: string,
  title: string,
): ResumeData {
  return isWorkspaceResumeData(raw)
    ? raw
    : normalizeImportedResumeToCanonical(raw, { resumeId, title });
}

/** 快照恢复清洗：把 localStorage 里历史坏 resumeData 逐条转 canonical。
 *  两份 loadSession 恢复块共用，避免只改一处漂移；resumeData 缺失的条目原样保留。 */
function cleanLoadedResumesSnapshot(sLrs: unknown): any[] {
  if (!Array.isArray(sLrs)) return sLrs as any[];
  return sLrs.map((r: any) =>
    r?.resumeData
      ? {
          ...r,
          resumeData: toCanonicalResumeData(
            r.resumeData,
            r.id,
            r.name || "我的简历",
          ),
        }
      : r,
  );
}

function isCreateResumeIntentText(text: string): boolean {
  const normalized = (text || "").trim();
  if (!normalized) return false;
  return /(?:帮我|请|想要|想)?(?:创建|新建|做|生成|弄).{0,8}(?:一份|一个|份)?(?:简历|cv)|(?:创建|新建).{0,4}简历/i.test(
    normalized,
  );
}


function isSelectExistingResumeIntentText(text: string): boolean {
  const normalized = (text || "").trim();
  if (!normalized || isCreateResumeIntentText(normalized)) return false;
  // 「导入我的简历内容：…」是粘贴导入，不是选择已有简历
  if (/^导入(?:我的)?(?:简历|cv)/i.test(normalized)) return false;
  return (
    /^(?:加载|打开|查看|显示|选择).*(?:已有|保存的|我的)?.{0,6}(?:简历|resume|cv)/i.test(
      normalized,
    ) ||
    /^(?:已有|保存的).{0,6}(?:简历|resume|cv)/i.test(normalized) ||
    /^(?:简历|resume|cv).*(?:加载|打开|选择)/i.test(normalized) ||
    /^选择已有简历/i.test(normalized)
  );
}

function isLoadResumeIntentText(text: string): boolean {
  return isSelectExistingResumeIntentText(text);
}

const PASTE_IMPORT_EXPLICIT_RES = [
  /^导入(?:我的)?(?:简历|cv)(?:内容)?\s*[：:]\s*([\s\S]+)/i,
  /^import\s+(?:my\s+)?(?:resume|cv)(?:\s+content)?\s*[：:]\s*([\s\S]+)/i,
];

function isResumeLikePasteText(text: string): boolean {
  let score = 0;
  if (/教育经历|education|大学|学院|硕士|本科|学士/i.test(text)) score += 1;
  if (/实习|工作|项目|经历|internship|experience|project/i.test(text)) score += 1;
  if (/(?:1[3-9]\d{9})|@\w+\.|邮箱|电话|📞|📧/i.test(text)) score += 1;
  if (/求职意向|objective|专业技能|skills/i.test(text)) score += 1;
  return score >= 3 || (score >= 2 && text.length >= 400);
}

/** 从用户消息中提取待解析的简历正文（对话粘贴导入 fast path） */
function extractPasteImportResumeText(text: string): string | null {
  const trimmed = (text || "").trim();
  if (!trimmed) return null;

  for (const pattern of PASTE_IMPORT_EXPLICIT_RES) {
    const explicitMatch = trimmed.match(pattern);
    if (explicitMatch?.[1]?.trim()) {
      const body = explicitMatch[1].trim();
      return body.length >= 50 ? body : null;
    }
  }

  if (trimmed.length < 200) return null;
  if (
    /^(?:帮我|请)?(?:优化|润色|改写|诊断|分析|读取|查看|显示)/i.test(trimmed)
  ) {
    return null;
  }
  // resume-like 的长文本明显是「粘贴的简历正文」，哪怕正文里含「创建简历/生成简历」
  // 这类词（例如把本项目介绍整段粘进来），也应优先走粘贴导入，避免被意图词误判成创建意图。
  if (isResumeLikePasteText(trimmed)) return trimmed;
  if (isSelectExistingResumeIntentText(trimmed)) return null;
  if (isCreateResumeIntentText(trimmed)) return null;
  return null;
}

function resolveImportedResumeDisplayName(data: Record<string, unknown>): string {
  const contact = (data.contact || {}) as Record<string, unknown>;
  return (
    toText(data.name) ||
    toText((data.basic as Record<string, unknown> | undefined)?.name) ||
    toText(contact.name) ||
    "导入的简历"
  );
}

const CREATE_RESUME_GUIDE_TEXT = `好，把你的情况说给我就行 👇 这几个方面想说哪个说哪个（不用全说）：

- **教育经历**：学校、专业、学历、时间
- **实习经历**：公司、岗位、做了什么
- **项目经历**：项目名、你的角色、成果
- **个人经历**：竞赛、开源、社团等
- **自我评价**：技能亮点、求职意向

可以**一次性全发**给我、也可以**一段段拆开**给、或者先说一项（比如「我的教育经历是……」）。有现成的简历文字、直接粘进来也行。`;

interface SearchResultItem {
  position?: number;
  url?: string;
  title?: string;
  description?: string;
  source?: string;
  raw_content?: string;
}

interface SearchStructuredData {
  type: "search";
  query: string;
  results: SearchResultItem[];
  total_results: number;
  metadata?: {
    total_results?: number;
    language?: string;
    country?: string;
    search_time?: string;
    original_query?: string;
    enhanced_query?: string;
  };
}

interface ResumeStructuredData {
  type: "resume" | "resume_selector";
  resume_id?: string;
  user_id?: string;
  name?: string;
  resume_data?: ResumeData;
  required?: boolean;
  message?: string;
  source?: string;
  trigger?: string;
  intent_source?: string;
}

interface ResumeEditDiffStructuredData {
  type: "resume_edit_diff";
  section: "basic" | "internships" | string;
  field: string;
  index?: number;
  before: string;
  after: string;
  patch?: {
    path?: string;
    action?: string;
    value?: unknown;
  };
}

// 简历导入/解析成功卡片下方的「下一步」建议 chip（点击即发送）。
// 首位放整份优化：导入 → 一键整份优化 → 全部应用，是最短的价值闭环。
const IMPORT_NEXT_STEP_SUGGESTIONS = [
  "优化我的整份简历",
  // 暂时下掉这两个入口（前端先不展示），代码保留方便以后恢复
  // "按目标岗位 JD 帮我改简历",
  // "帮我把经历写得更专业",
];

// 历史消息的稳定 ID：基于 (role, content, index) 的确定性哈希（FNV-1a 变体）。
// 保存 ui_state 和恢复会话两侧必须用同一实现，meta / patch 卡才能按 id 挂回历史消息。
function stableMessageId(content: string, role: string, index: number): string {
  const contentForHash = content || `empty-${index}`;
  let hash = 2166136261;
  const str = `${role}:${contentForHash}:${index}`;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash +=
      (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  return `msg-${(hash >>> 0).toString(16).slice(0, 12)}`;
}

/**
 * 从 ConversationRunState.process 提取 Thought 正文。
 * currentThought 的实时派生与 finalize 时的权威读取共用同一投影，避免两处漂移。
 */
function deriveThoughtText(process: ConversationRunState["process"]): string {
  return process
    .filter((node) => node.kind === "thought")
    .map((node) => node.content.trim())
    .filter(Boolean)
    .join("\n\n");
}

// ============================================================================
// 主页面组件
// ============================================================================

export default function CocoChat() {
  const { agentEnabled } = useRuntimeFeatures();
  if (!agentEnabled) {
    return null;
  }
  return <CocoChatContent />;
}

function CocoChatContent() {
  const location = useLocation();
  const navigate = useNavigate();
  const { resumeId } = useParams();
  const { user, isAuthenticated } = useAuth();
  const { apiBaseUrl } = useEnvironment();
  const [byokConfig, setByokConfig] = useState<ByokConfig>(() => loadByokConfig());
  const [byokModalOpen, setByokModalOpen] = useState(false);
  const byokActive = isByokActive(byokConfig);

  useEffect(() => {
    const syncByok = () => setByokConfig(loadByokConfig());
    const handleStorage = (event: StorageEvent) => {
      if (!event.key || event.key === BYOK_STORAGE_KEY) {
        syncByok();
      }
    };
    window.addEventListener(BYOK_UPDATED_EVENT, syncByok);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(BYOK_UPDATED_EVENT, syncByok);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  // 本地↔数据库简历兜底同步:agent 的 list_resumes 只能看见数据库,而
  // 产品级 fallback(DB 写失败保留本地缓存)/后端宕机窗口会造成"Dashboard
  // 看得见、agent 看不见"的分裂(2026-07-13 实测:「郭子」只在 localStorage,
  // 库里 0 份)。既有 sync 只在登录/注册时触发(AuthContext),这里补"进入
  // agent 页"时机;失败静默,不阻塞聊天。
  useEffect(() => {
    if (!isAuthenticated) return;
    void syncLocalResumesToCurrentAccount().catch(() => {});
  }, [isAuthenticated]);

  const getAuthHeaders = useCallback((extra: Record<string, string> = {}) => {
    return buildAuthHeaders(extra);
  }, []);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState(0);
  const [isDesktop, setIsDesktop] = useState(true);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  const [initialSessionResolved, setInitialSessionResolved] = useState(false);
  const [isLoadingResume, setIsLoadingResume] = useState(false);
  const [isLoadingChat, setIsLoadingChat] = useState(false);

  const [conversationId, setConversationId] = useState(() => {
    // 优先从 URL 恢复会话ID；否则先给一个临时ID，后续会在初始化阶段替换为"最新会话"
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const sessionId = params.get("sessionId");
      if (sessionId && sessionId.trim() !== "") {
        return sessionId;
      }
    }
    return `conv-${Date.now()}`;
  });
  const [resumeData, setResumeData] = useState<ResumeData | null>(null);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [loadingResume, setLoadingResume] = useState(true);
  // 应用优化后短暂高亮预览面板（结果直接可见：引导视线看右侧更新）
  const [previewJustUpdated, setPreviewJustUpdated] = useState(false);
  // 预览「视觉隐藏但保持渲染」（display:none 不卸载）：界面看起来是纯 AI
  // 对话，PDF/缩放/滚动状态全保留，展开零等待。入口：面板头部「收起预览」，
  // 恢复：输入框工具条的低调眼睛图标。
  const [previewConcealed, setPreviewConcealed] = useState(false);
  const previewPulseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 简历卡片相关状态
  const [loadedResumes, setLoadedResumes] = useState<
    Array<{
      id: string;
      name: string;
      messageId: string;
      resumeData?: ResumeData;
    }>
  >([]);
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [allowPdfAutoRender, setAllowPdfAutoRender] = useState(false);
  // 从编辑页带 resumeId 跳来时，暂存待选择的简历，弹「继续编辑 / 开启新会话」选择
  const [carryResumePrompt, setCarryResumePrompt] = useState<SavedResume | null>(null);
  const [resumePdfPreview, setResumePdfPreview] = useState<
    Record<string, ResumePdfPreviewState>
  >({});

  // 搜索结果相关状态
  const [searchResults, setSearchResults] = useState<
    Array<{ messageId: string; data: SearchStructuredData }>
  >([]);
  const [resumeEditDiffs, setResumeEditDiffs] = useState<
    Array<{ messageId: string; data: ResumeEditDiffStructuredData }>
  >([]);
  const [diagnosisToolEvents, setDiagnosisToolEvents] = useState<
    Array<{ messageId: string; data: DiagnosisToolStructuredData }>
  >([]);
  const [structuredEvents, setStructuredEvents] = useState<
    Array<{ messageId: string; data: StructuredEventData }>
  >([]);

  const [resumeEditError, setLastError] = useState<{ message: string } | null>(null);

  // ResumeContext integration
  const {
    resume: contextResume,
    pendingPatches,
    pushPatch,
    patchAppliedAt,
    supersedePendingPatches,
    restorePatches,
    rebindCurrentPatches,
    setResume,
  } = useResumeContext();
  const [generatedResume, setGeneratedResume] = useState<{
    resume: any; summary: string
  } | null>(null);
  // Track current assistant message ID for patch association
  const currentAssistantMessageIdRef = useRef<string | null>(null);
  // When resume_patch events are received, skip the old cv_editor_agent edit diff path
  const hasPatchInCurrentStreamRef = useRef(false);
  // 整份优化任务：后端在本请求收尾时发 auto_continue（还有模块没处理完）。
  // 只记下待续跑的 next_user_input，真正发起要等当前这轮完全 finalize
  // 完（见下方 messages 变化触发的 effect）——finalize 期间还在读
  // currentAnswerRef/typewriter，这时候调 sendMessage 会 disconnect 当前
  // 流、把还没读完的内容截断。next_user_input 已经带了 AUTO_CONTINUE_PREFIX
  // 协议前缀（见 optimize_progress.py），必须原样传给 sendMessage，不能再
  // 包一层"系统内部提示"文案——后端靠 startswith 精确匹配这个前缀。
  const pendingAutoContinueRef = useRef<string | null>(null);
  // 防御性上限：后端 ResumeDataStore.MAX_CONTINUE_COUNT 已经会在到顶后停发
  // auto_continue，这里只是兜底，防止后端出 bug 时前端把自己打成死循环。
  const autoContinueFiredCountRef = useRef(0);
  const AUTO_CONTINUE_FRONTEND_CAP = 12;
  // isProcessing 的实时镜像：独立review发现，如果同一次 React commit 里
  // pendingPatches 静默轮 effect 和 auto_continue 续跑 effect 都判定
  // "isProcessing===false"该发，两个都会调 sendMessage——后发的那个会把
  // 先发的流 disconnect 掉。auto_continue 触发时用这个 ref（而不是闭包里的
  // isProcessing）做二次确认，见下方 effect。
  const isProcessingRef = useRef(false);

  const [activeRunId, setActiveRunId] = useState(0);
  const [activeSearchPanel, setActiveSearchPanel] =
    useState<SearchStructuredData | null>(null);

  // 🔧 自动同步选中的简历数据到全局 resumeData，确保右侧 PDF 渲染（用于恢复持久化状态）
  useEffect(() => {
    if (selectedResumeId) {
      const loaded = loadedResumes.find((r) => r.id === selectedResumeId);
      if (loaded?.resumeData) {
        setResumeData(loaded.resumeData);
      }
    } else {
      setResumeData(null);
    }
  }, [selectedResumeId, loadedResumes]);

  const [copiedId, setCopiedId] = useState<string | null>(null);

  // 初始化会话：仅首次进入页面时执行；有 sessionId 用指定会话，否则默认加载最新会话
  useEffect(() => {
    if (hasBootstrappedSessionRef.current) {
      return;
    }

    let mounted = true;
    const params = new URLSearchParams(location.search);
    const explicitSessionId = params.get("sessionId");
    const hasExplicitId = !!explicitSessionId?.trim();
    const forceNew = (location.state as { forceNew?: number } | null)?.forceNew;
    // 从首页 hero 输入框进入（fromHome）时，也跳过「加载最近会话」，直接开一个新对话。
    const fromHome = (location.state as { fromHome?: number } | null)?.fromHome;

    if (forceNew || fromHome || isCreatingNewSessionRef.current) {
      hasBootstrappedSessionRef.current = true;
      setInitialSessionResolved(true);
      return () => {
        mounted = false;
      };
    }

    if (hasExplicitId) {
      const sid = explicitSessionId!.trim();
      setConversationId(sid);
      hasBootstrappedSessionRef.current = true;
      setInitialSessionResolved(true);
      return () => {
        mounted = false;
      };
    }

    // 2026-07-17 身份统一：旧「按 legacy token 自动加载最近会话」路径退役——
    // BetterAuth（cookie 登录）用户此前本就恒走本分支（auth_token 恒空），行为不变：
    // 无显式 sessionId 一律从新对话开始。
    hasBootstrappedSessionRef.current = true;
    setInitialSessionResolved(true);
    return () => {
      mounted = false;
    };
  }, [apiBaseUrl, getAuthHeaders, navigate, location.search, location.state]);

  // 简历选择器状态
  const [showResumeSelector, setShowResumeSelector] = useState(false);
  // Asking 模式:当前轮选择框是否已提交(防重复提交 + 提交后置灰按钮)
  const [askQuestionSubmitted, setAskQuestionSubmitted] = useState(false);
  // 「按 JD 优化简历」交互卡（从首页 chip 进入时打开）
  const [showJdCard, setShowJdCard] = useState(false);
  // ResumeSelector 打开时的初始步骤（「选择已有」直达列表，其余从入口卡片进）
  const [resumeSelectorInitialStep, setResumeSelectorInitialStep] = useState<
    "entry" | "existing"
  >("entry");
  const [aiImportModalOpen, setAiImportModalOpen] = useState(false);
  const currentRunUserInputRef = useRef("");
  // show_resume 触发的"弹选择面板"请求:流式中只标记,回复完整落地后再弹(Bug:提前弹卡)
  const pendingSelectorOpenRef = useRef(false);
  const [pendingResumeInput, setPendingResumeInput] = useState<string>(""); // 暂存用户输入，选择简历后继续处理
  // replay 防重入:记录已发射过的暂存输入(见 replay effect 的守卫注释)
  const replayFiredForInputRef = useRef<string | null>(null);
  const resumeDataRef = useRef<ResumeData | null>(null);

  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPasteImporting, setIsPasteImporting] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<File[]>([]);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const saveInFlightRef = useRef<Promise<void> | null>(null);
  const pendingSaveRef = useRef(false);
  const queuedSaveRef = useRef<{
    sessionId: string;
    messages: Message[];
    shouldRefresh: boolean;
  } | null>(null);
  const scheduledSaveRef = useRef<{
    sessionId: string;
    messages: Message[];
    shouldRefresh: boolean;
  } | null>(null);
  const saveDebounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedKeyRef = useRef<string>("");
  const refreshAfterSaveRef = useRef(false);
  const saveRetryRef = useRef<Record<string, number>>({});
  const saveClientSeqRef = useRef(0);
  const lastPersistedCountBySessionRef = useRef<Record<string, number>>({});
  const appendDisabledBySessionRef = useRef<Record<string, boolean>>({});
  const historyApiUnavailableRef = useRef(false);
  const autoScrollTimerRef = useRef<number | null>(null);
  const { streamRunRef, startNewRun } = useStreamRunController();
  // 完成态去重锁：页面本地状态。其余完成态内容（thought / answer）一律以
  // currentRunState 为权威，不再维护页面级镜像 ref 或完成快照。
  const isFinalizedRef = useRef(false);
  const currentProcessNodesRef = useRef<AgentProcessNode[]>([]);
  const currentRunStateRef = useRef<ConversationRunState | null>(null);
  const lastHandledAnswerCompleteRef = useRef(0);
  const lastDoneRunRef = useRef<number>(-1);
  const lastFinalizedRunRef = useRef<number>(-1);
  const lastFinalizedSignatureRef = useRef("");
  const pendingFinalizeAfterTypewriterRef = useRef(false);
  const prevRouteSessionIdRef = useRef<string | null>(null);
  const isCreatingNewSessionRef = useRef(false);
  const hasBootstrappedSessionRef = useRef(false);
  const { rebindCurrentMessageId } = useMessageTimeline();
  
  const normalizedResume = useMemo(() => {
    if (!resumeData) return null;
    return convertResumeDataToOpenManusFormat(resumeData);
  }, [resumeData]);

  useEffect(() => {
    resumeDataRef.current = resumeData;
  }, [resumeData]);

  const selectedLoadedResume = useMemo(() => {
    if (!selectedResumeId) return null;
    for (let i = loadedResumes.length - 1; i >= 0; i -= 1) {
      if (loadedResumes[i].id === selectedResumeId) {
        return loadedResumes[i];
      }
    }
    return null;
  }, [loadedResumes, selectedResumeId]);

  const selectedResumePdfState = selectedResumeId
    ? resumePdfPreview[selectedResumeId] || EMPTY_RESUME_PDF_STATE
    : EMPTY_RESUME_PDF_STATE;
  const isResumePreviewActive = Boolean(selectedResumeId);

  const updateResumePdfState = useCallback(
    (id: string, patch: Partial<ResumePdfPreviewState>) => {
      setResumePdfPreview((prev) => ({
        ...prev,
        [id]: {
          ...(prev[id] || EMPTY_RESUME_PDF_STATE),
          ...patch,
        },
      }));
    },
    [],
  );

  const pdfRenderAbortRef = useRef<AbortController | null>(null);
  const pdfLoadingRef = useRef<Set<string>>(new Set());

  const renderResumePdfPreview = useCallback(
    async (
      resumeEntry: {
        id: string;
        resumeData?: ResumeData;
      },
      force = false,
    ) => {
      console.log(
        "[DEBUG] renderResumePdfPreview called for:",
        resumeEntry.id,
        "force:",
        force,
        "stack:",
        new Error().stack?.split("\n").slice(2, 5).join(" <- "),
      );
      if (!resumeEntry.resumeData) return;
      const resumeId = resumeEntry.id;

      if (!force && pdfLoadingRef.current.has(resumeId)) {
        console.log(
          "[DEBUG] renderResumePdfPreview skipped (already loading via ref)",
        );
        return;
      }
      if (!force && resumePdfPreview[resumeId]?.blob) {
        console.log(
          "[DEBUG] renderResumePdfPreview skipped (already has blob)",
        );
        return;
      }

      pdfLoadingRef.current.add(resumeId);
      pdfRenderAbortRef.current?.abort();
      const abortController = new AbortController();
      pdfRenderAbortRef.current = abortController;
      const renderTimeoutMs = 120_000;
      const timeoutId = window.setTimeout(() => {
        abortController.abort();
      }, renderTimeoutMs);

      try {
      // 守卫改「先修复再渲染」（2026-07-18）：loadedResumes 写入点有 20 处、
      // 逐入口补 canonical 转换屡漏屡复发——非工作台格式在此咽喉统一转
      // （toCanonicalResumeData 对已 canonical 原样返回，无二次转换损耗），
      // 转完仍不合格才报「不支持」。
      const canonicalData = toCanonicalResumeData(
        resumeEntry.resumeData,
        resumeEntry.id,
        "我的简历",
      );
      if (!isWorkspaceResumeData(canonicalData)) {
        updateResumePdfState(resumeEntry.id, {
          blob: null,
          loading: false,
          progress: "",
          error: "当前简历数据格式不支持 PDF 预览。",
        });
        return;
      }

      updateResumePdfState(resumeEntry.id, {
        loading: true,
        progress: "正在渲染 PDF...",
        error: null,
      });
        const backendData = convertToBackendFormat(canonicalData);
        const renderSessionId = currentSessionId || conversationId;
        const traceId = `sophia-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        console.log("[PDF TRACE] 准备渲染PDF", {
          traceId,
          sessionId: renderSessionId,
          resumeId: resumeEntry.id,
          force,
          selectedResumeId,
          allowPdfAutoRender,
        });
        const blob = await renderPDFStream(
          backendData as any,
          backendData.sectionOrder,
          (progress) => {
            updateResumePdfState(resumeEntry.id, { progress });
          },
          () => {
            updateResumePdfState(resumeEntry.id, { progress: "渲染完成" });
          },
          (error) => {
            updateResumePdfState(resumeEntry.id, { error });
          },
          {
            sessionId: renderSessionId,
            resumeId: resumeEntry.id,
            traceId,
            source: "CocoChat.renderResumePdfPreview",
            trigger: force ? "manual-retry" : "auto-effect",
            signal: abortController.signal,
          },
        );

        updateResumePdfState(resumeEntry.id, {
          blob,
          loading: false,
          progress: "",
          error: null,
        });
      } catch (error) {
        const aborted =
          error instanceof Error && error.name === "AbortError";
        updateResumePdfState(resumeEntry.id, {
          blob: null,
          loading: false,
          progress: "",
          error: aborted
            ? "PDF 渲染超时或已取消，请点击重新渲染。"
            : error instanceof Error
              ? error.message
              : "PDF 渲染失败，请稍后重试。",
        });
      } finally {
        window.clearTimeout(timeoutId);
        pdfLoadingRef.current.delete(resumeId);
        if (pdfRenderAbortRef.current === abortController) {
          pdfRenderAbortRef.current = null;
        }
      }
    },
    [
      updateResumePdfState,
      resumePdfPreview,
      currentSessionId,
      conversationId,
      selectedResumeId,
      allowPdfAutoRender,
    ],
  );

  const upsertSearchResult = useCallback(
    (messageId: string, data: SearchStructuredData) => {
      setSearchResults((prev) => {
        const existingIndex = prev.findIndex(
          (item) => item.messageId === messageId,
        );
        if (existingIndex >= 0) {
          const updated = [...prev];
          updated[existingIndex] = { messageId, data };
          return updated;
        }
        return [...prev, { messageId, data }];
      });
    },
    [],
  );

  const upsertLoadedResume = useCallback(
    (messageId: string, payload: ResumeStructuredData) => {
      const resumeData = payload.resume_data;
      if (!resumeData) return;

      const rawId = payload.resume_id;
      const resumeId =
        typeof rawId === "string" && rawId.trim().length > 0
          ? rawId
          : `resume-${Date.now()}`;
      const resumeName =
        typeof payload.name === "string" && payload.name.trim().length > 0
          ? payload.name
          : "我的简历";
      // 工具 structured 事件（cv_reader 等）可能带无 menuSections 的 agent 内部格式，
      // 入库前统一归一成 canonical，避免右侧 PDF 预览格式守卫拦截。
      const canonical = toCanonicalResumeData(
        resumeData as Record<string, any>,
        resumeId,
        resumeName,
      );

      setLoadedResumes((prev) => {
        const existingIndex = prev.findIndex(
          (item) => item.messageId === messageId,
        );
        const entry = {
          id: resumeId,
          name: resumeName,
          messageId,
          resumeData: canonical,
        };
        if (existingIndex >= 0) {
          const updated = [...prev];
          updated[existingIndex] = entry;
          return updated;
        }
        return [...prev, entry];
      });
    },
    [],
  );

  const upsertResumeEditDiff = useCallback(
    (messageId: string, data: ResumeEditDiffStructuredData) => {
      setResumeEditDiffs((prev) => {
        const existingIndex = prev.findIndex(
          (item) => item.messageId === messageId,
        );
        if (existingIndex >= 0) {
          const updated = [...prev];
          updated[existingIndex] = { messageId, data };
          return updated;
        }
        return [...prev, { messageId, data }];
      });
    },
    [],
  );

  const upsertDiagnosisToolEvent = useCallback(
    (messageId: string, data: DiagnosisToolStructuredData) => {
      setDiagnosisToolEvents((prev) => {
        const existingIndex = prev.findIndex(
          (item) => item.messageId === messageId && item.data.type === data.type,
        );
        if (existingIndex >= 0) {
          const updated = [...prev];
          updated[existingIndex] = { messageId, data };
          return updated;
        }
        return [...prev, { messageId, data }];
      });
    },
    [],
  );

  const upsertStructuredEvent = useCallback(
    (messageId: string, data: StructuredEventData) => {
      setStructuredEvents((prev) => {
        const existingIndex = prev.findIndex(
          (item) => item.messageId === messageId && item.data.type === data.type,
        );
        if (existingIndex >= 0) {
          const updated = [...prev];
          updated[existingIndex] = { messageId, data };
          return updated;
        }
        return [...prev, { messageId, data }];
      });
    },
    [],
  );

  const applyResumeEditDiff = useCallback(
    (diff: ResumeEditDiffStructuredData) => {
      const patchPath = diff.patch?.path || "";
      const patchValue = diff.patch?.value;
      const patchAction = String(diff.patch?.action || "update").toLowerCase();

      // Debug logging to help identify issues
      console.log("[ResumeEdit] Applying diff:", {
        patchPath,
        patchValue,
        patchAction,
        hasBefore: !!diff.before,
        hasAfter: !!diff.after,
        section: diff.section,
        field: diff.field,
        index: diff.index,
      });

      if (!["update", "set", "replace", "edit"].includes(patchAction)) {
        console.warn("[ResumeEdit] Unsupported action:", patchAction);
        setLastError((prev) => ({
          ...prev,
          message: `不支持的操作类型：${patchAction}。仅支持 update、set、replace、edit 操作。`,
        }));
        return;
      }

      if (!patchPath) {
        console.warn("[ResumeEdit] No patch path provided", diff);
        setLastError((prev) => ({
          ...prev,
          message: `简历更新失败：AI未提供修改路径。这通常是因为AI无法确定要修改哪个字段。请尝试更具体的描述，例如："修改腾讯实习的工作经历描述"`,
        }));
        return;
      }

      if (!patchValue && !diff.after) {
        console.warn("[ResumeEdit] No new value provided", diff);
        setLastError((prev) => ({
          ...prev,
          message: `简历更新失败：AI未提供新的内容。请重试。`,
        }));
        return;
      }

      const patchResume = (source: ResumeData): ResumeData => {
        const next = structuredClone(source);
        const parsePathTokens = (path: string): Array<string | number> =>
          path
            .replace(/\[(\d+)\]/g, ".$1")
            .split(".")
            .map((segment) => segment.trim())
            .filter(Boolean)
            .map((segment) =>
              /^\d+$/.test(segment) ? Number(segment) : segment,
            );

        const normalizeRootKey = (
          root: string,
          resume: ResumeData,
        ): string => {
          if (root === "internships" || root === "internship") {
            if (!("internships" in (resume as Record<string, unknown>))) {
              return "experience";
            }
          }
          if (root === "work_experience" || root === "workExperience") {
            return "experience";
          }
          if (root === "basic_info" || root === "profile") {
            return "basic";
          }
          return root;
        };

        const setByPath = (
          target: Record<string, unknown>,
          tokens: Array<string | number>,
          value: unknown,
        ): boolean => {
          if (tokens.length === 0) return false;
          const normalized = [...tokens];
          if (typeof normalized[0] === "string") {
            normalized[0] = normalizeRootKey(normalized[0], next);
          }

          let cursor: any = target;
          for (let i = 0; i < normalized.length - 1; i += 1) {
            const current = normalized[i];
            const upcoming = normalized[i + 1];

            if (typeof current === "number") {
              if (!Array.isArray(cursor)) return false;
              if (
                cursor[current] === undefined ||
                cursor[current] === null ||
                typeof cursor[current] !== "object"
              ) {
                cursor[current] = typeof upcoming === "number" ? [] : {};
              }
              cursor = cursor[current];
              continue;
            }

            if (
              cursor[current] === undefined ||
              cursor[current] === null ||
              typeof cursor[current] !== "object"
            ) {
              cursor[current] = typeof upcoming === "number" ? [] : {};
            }
            cursor = cursor[current];
          }

          const leaf = normalized[normalized.length - 1];
          if (typeof leaf === "number") {
            if (!Array.isArray(cursor)) return false;
            cursor[leaf] = value;
            return true;
          }
          cursor[leaf] = value;
          return true;
        };

        const patchTokens = parsePathTokens(patchPath);
        const nextValueRaw =
          patchValue !== undefined ? patchValue : (diff.after ?? "");
        const nextValue = normalizeResumePatchValue(
          nextValueRaw,
          patchPath,
          diff.field,
        );
        if (patchTokens.length > 0) {
          const applied = setByPath(
            next as Record<string, unknown>,
            patchTokens,
            nextValue,
          );
          if (applied) return next;
        }

        const fallbackField = (typeof diff.field === "string" ? diff.field : "").trim();
        if (diff.section === "basic" && fallbackField) {
          setByPath(
            next as Record<string, unknown>,
            ["basic", fallbackField],
            normalizeResumePatchValue(
              diff.after ?? "",
              `basic.${fallbackField}`,
              fallbackField,
            ),
          );
          return next;
        }

        if (
          fallbackField &&
          typeof diff.index === "number" &&
          Number.isInteger(diff.index)
        ) {
          const sectionKey =
            diff.section === "internships" ? "experience" : diff.section;
          const applied = setByPath(
            next as Record<string, unknown>,
            [sectionKey, diff.index, fallbackField],
            normalizeResumePatchValue(
              diff.after ?? "",
              `${sectionKey}[${diff.index}].${fallbackField}`,
              fallbackField,
            ),
          );
          if (applied) return next;
        }

        const normalizeComparable = (value: unknown): string =>
          String(value || "")
            .replace(/<[^>]+>/g, " ")
            .replace(/&nbsp;/gi, " ")
            .replace(/&amp;/gi, "&")
            .replace(/&lt;/gi, "<")
            .replace(/&gt;/gi, ">")
            .replace(/\s+/g, "")
            .trim()
            .toLowerCase();

        const beforeNeedle = normalizeComparable(diff.before || "");
        if (beforeNeedle.length >= 4) {
          const candidateRoots = Array.from(
            new Set(
              [
                String(diff.section || ""),
                diff.section === "internships" ? "experience" : "",
                "experience",
                "internships",
              ]
                .map((root) => normalizeRootKey(root, next))
                .filter(Boolean),
            ),
          );

          for (const rootKey of candidateRoots) {
            const collection = (next as Record<string, unknown>)[
              rootKey
            ] as unknown;
            if (!Array.isArray(collection)) continue;

            for (let i = 0; i < collection.length; i += 1) {
              const item = collection[i] as Record<string, unknown>;
              if (!item || typeof item !== "object") continue;
              const candidateField = fallbackField || "details";
              const candidateValue = item[candidateField];
              const candidateComparable = normalizeComparable(candidateValue);
              if (
                !candidateComparable ||
                (!candidateComparable.includes(beforeNeedle) &&
                  !beforeNeedle.includes(candidateComparable))
              ) {
                continue;
              }

              const applied = setByPath(
                next as Record<string, unknown>,
                [rootKey, i, candidateField],
                normalizeResumePatchValue(
                  diff.after ?? "",
                  `${rootKey}[${i}].${candidateField}`,
                  candidateField,
                ),
              );
              if (applied) {
                console.log("[AgentChat] Applied resume diff via before-match fallback", {
                  rootKey,
                  index: i,
                  field: candidateField,
                });
                return next;
              }
            }
          }
        }

        if (patchPath) {
          console.warn("[AgentChat] Failed to apply resume patch path", {
            patchPath,
            patchAction,
            section: diff.section,
            field: diff.field,
            index: diff.index,
            before: diff.before?.substring(0, 100),
            after: diff.after?.substring(0, 100),
          });
          // Show user-friendly error message in the chat
          setLastError((prev) => ({
            ...prev,
            message: `简历更新失败：无法找到路径 "${patchPath}"。请确保简历中包含该字段，或尝试重新描述需要修改的内容。`,
          }));
        } else {
          console.warn("[AgentChat] Missing patch path in resume diff", {
            section: diff.section,
            field: diff.field,
            index: diff.index,
          });
          setLastError((prev) => ({
            ...prev,
            message: `简历更新失败：缺少路径信息。AI响应格式不正确，请重试或重新描述需求。`,
          }));
        }
        return next;
      };

      setLoadedResumes((prev) => {
        if (prev.length === 0) return prev;
        const targetId = selectedResumeId || prev[0]?.id;
        if (!targetId) return prev;
        return prev.map((item) => {
          if (item.id !== targetId || !item.resumeData) return item;
          return { ...item, resumeData: patchResume(item.resumeData) };
        });
      });

      setResumeData((prev) => (prev ? patchResume(prev) : prev));
      setResumePdfPreview((prev) => {
        const targetId = selectedResumeId || Object.keys(prev)[0];
        if (!targetId) return prev;
        return {
          ...prev,
          [targetId]: {
            ...(prev[targetId] || EMPTY_RESUME_PDF_STATE),
            blob: null,
            loading: false,
            progress: "",
            error: null,
          },
        };
      });
      setResumeError(null);
      setAllowPdfAutoRender(true);
    },
    [selectedResumeId],
  );

  const { handleSSEEvent } = useToolEventRouter<
    SearchStructuredData,
    ResumeStructuredData,
    ResumeEditDiffStructuredData,
    DiagnosisToolStructuredData,
    StructuredEventData
  >({
    runId: activeRunId,
    onDone: () => {
      lastDoneRunRef.current = streamRunRef.current;
      pendingFinalizeAfterTypewriterRef.current = true;
    },
    onError: (message) => setResumeError(message),
    onShowResumeSelector: () => {
      const text = currentRunUserInputRef.current.trim();
      if (isCreateResumeIntentText(text)) {
        return;
      }
      // 「我要选择一份已有简历」「展示简历」这类纯"选择/看面板"意图不暂存：
      // 它的完成形态就是选择动作本身，选完 replay 重发只会再次触发
      // show_resume（Agent 答"面板已经打开了"，陷入循环）。选完后由
      // handleResumeSelect 发起「我选择了「XX」」完整一轮自然衔接
      // （2026-07-15 选择简历对话化）。带实质意图的输入（"帮我优化简历"）
      // 仍暂存 replay。
      const isPureSelectIntent =
        isSelectExistingResumeIntentText(text) ||
        /^(?:我要|我想|想要|帮我)?(?:选择?|挑|换|展示|看看)一?份?(?:已有|现有|保存的)?.{0,6}(?:简历|resume|cv)$/i.test(
          text,
        );
      if (text && !isPureSelectIntent) {
        // 新一发弹药装填:清除防重入记录(同文案的两次独立 show_resume 是合法场景)
        replayFiredForInputRef.current = null;
        setPendingResumeInput(text);
      }
      // show_resume 的 tool_result 到达时正文往往还在流式输出,此时立即弹面板
      // 会"话没说完 UI 就跳"。这里只做标记,等本轮回复完整落地后(下方
      // flushPendingResumeSelector 的 effect)再真正弹出。
      pendingSelectorOpenRef.current = true;
    },
    onResumeUpdated: (resumeData) => {
      // 后端推送完整的更新后简历 JSON，更新 loadedResumes 本地副本（用于 PDF 渲染）。
      // ResumeContext 已通过 resume_patch 事件独立处理字段更新，无需重复合并。
      // 后端 store 数据可能是无 menuSections 的 agent 内部格式，入口统一归一成
      // canonical，避免右侧 PDF 预览的格式守卫拦截报「不支持 PDF 预览」。
      setLoadedResumes((prev) => {
        if (prev.length === 0) return prev;
        const targetId = selectedResumeId || prev[0]?.id;
        return prev.map((item) =>
          item.id === targetId
            ? {
                ...item,
                resumeData: toCanonicalResumeData(
                  resumeData as Record<string, any>,
                  item.id,
                  item.name,
                ),
              }
            : item,
        );
      });
      // 清空 PDF blob 以触发重新渲染
      setResumePdfPreview((prev) => {
        const targetId = selectedResumeId || Object.keys(prev)[0];
        if (!targetId) return prev;
        return {
          ...prev,
          [targetId]: { ...EMPTY_RESUME_PDF_STATE },
        };
      });
      setAllowPdfAutoRender(true);
    },
    upsertSearchResult,
    upsertLoadedResume,
    upsertResumeEditDiff: (messageId: string, data: ResumeEditDiffStructuredData) => {
      if (hasPatchInCurrentStreamRef.current) {
        console.log("[AgentChat] Skipping old editDiff — resume_patch path is active");
        return;
      }
      upsertResumeEditDiff(messageId, data);
    },
    upsertDiagnosisToolEvent,
    upsertStructuredEvent: (messageId: string, data: StructuredEventData) => {
      if (data.type === "ask_question") {
        setAskQuestionSubmitted(false);
      }
      // 主动读简历链路:get_resume_detail 加载简历后把简历展开到右侧预览。
      // SSE 只携带 {id,name}(完整简历含 PII 不进
      // 事件流/本地持久化,Codex review P2),前端凭 id 走已鉴权接口取详情,
      // 再复用 applyResumeToChat 的选简历落地链路。
      if (data.type === "resume_loaded") {
        const r = (data as any).resume as
          | { id?: string; name?: string }
          | undefined;
        if (r?.id) {
          void (async () => {
            try {
              const saved = await getResume(r.id!);
              if (saved) await applyResumeToChat(saved);
            } catch (err) {
              console.warn("[AgentChat] resume_loaded 取详情失败:", err);
            }
          })();
        }
        return;
      }
      if (classifyStructuredToolPresentation(data.type) === "process_only") return;
      upsertStructuredEvent(messageId, data);
    },
    applyResumeEditDiff: (data: ResumeEditDiffStructuredData) => {
      if (hasPatchInCurrentStreamRef.current) {
        console.log("[AgentChat] Skipping old applyEditDiff — resume_patch path is active");
        return;
      }
      applyResumeEditDiff(data);
    },
  });

  const [selectedModel, setSelectedModel] = useState<string>(() => {
    const saved = localStorage.getItem("agent_model");
    // 记忆值必须仍在可选列表内，否则回默认（模型列表演进后防孤儿值）
    return saved && AGENT_MODELS.some((m) => m.value === saved)
      ? saved
      : DEFAULT_AGENT_MODEL;
  });
  const handleModelChange = useCallback((m: string) => {
    setSelectedModel(m);
    try {
      localStorage.setItem("agent_model", m);
    } catch {
      /* ignore */
    }
  }, []);

  const {
    currentRunState,
    isProcessing,
    lastError,
    lastErrorCode,
    answerCompleteCount,
    sendMessage,
    finalizeStream,
    cancelStream,
  } = useCLTP({
    conversationId,
    baseUrl: apiBaseUrl,
    heartbeatTimeout: SSE_HEARTBEAT_TIMEOUT,
    meaningfulTimeout: SSE_MEANINGFUL_TIMEOUT,
    resumeData: normalizedResume,
    model: selectedModel,
    isAuthenticated,
    onSSEEvent: useCallback((event: SSEEvent) => {
      // Intercept resume_patch and resume_generated events before routing
      if ((event as any).type === 'resume_patch') {
        hasPatchInCurrentStreamRef.current = true;
        const patch = (event as any).data ?? {}
        pushPatch({
          patch_id:   patch.patch_id   ?? `patch-${Date.now()}`,
          // 与 resumeEditDiffs 一致，用 'current' 标记当前流式消息，
          // finalize 时再通过 rebindCurrentPatches 绑定到真实 message_id。
          message_id: 'current',
          paths:      patch.paths      ?? [],
          before:     patch.before     ?? {},
          after:      patch.after      ?? {},
          summary:    patch.summary    ?? '',
          operation:  patch.operation  ?? 'set',
        });
        return;
      }
      if ((event as any).type === 'resume_generated') {
        const data = (event as any).data ?? {}
        setGeneratedResume({ resume: data.resume, summary: data.summary ?? '' });
        return;
      }
      if ((event as any).type === 'suggestions') {
        return;
      }
      if ((event as any).type === 'auto_continue') {
        // 只记录，不在这里发——本请求的收尾内容（AgentEndEvent/answer）还没
        // 走完，现在调 sendMessage 会 disconnect 掉当前还没读完的流。
        // 真正触发在下面 messages 变化的 effect 里，等这轮真正 finalize 完。
        const payload = (event as any).data ?? {}
        const nextInput =
          typeof payload?.next_user_input === 'string' ? payload.next_user_input : '';
        if (nextInput) {
          pendingAutoContinueRef.current = nextInput;
        }
        return;
      }
      handleSSEEvent(event);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [handleSSEEvent, pushPatch]),
  });
  const currentThought = useMemo(
    () => deriveThoughtText(currentRunState.process),
    [currentRunState.process],
  );
  const currentProcessNodes = useMemo(
    () => projectLegacyProcessNodes(currentRunState.process),
    [currentRunState.process],
  );
  const currentAnswer = currentRunState.response.sourceText;

  // 完成态权威读取：直接取最新 currentRunState（reducer 在 sourceCompleted 后
  // 保留 process/response，直到下一轮 startNewRun 或 finalizeStream 才清空），
  // 替代此前的 currentThoughtRef / currentAnswerRef 页面镜像。stable identity，
  // 可安全用于其它 callback/effect 而不进依赖数组。
  const readLiveThought = useCallback(
    () =>
      currentRunStateRef.current
        ? deriveThoughtText(currentRunStateRef.current.process)
        : "",
    [],
  );
  const readLiveAnswer = useCallback(
    () => currentRunStateRef.current?.response.sourceText ?? "",
    [],
  );

  useEffect(() => {
    isProcessingRef.current = isProcessing;
  }, [isProcessing]);

  // 停止生成：通知后端中止当前流，并立即结束本地流式状态。
  // 必须定义在 useCLTP 之后——deps 里的 cancelStream 在其上方会触发 TDZ。
  // 弹出 show_resume 请求的简历选择面板。有存过简历就直达"选择已有"列表
  // (独立review发现的老bug:以前无条件走"entry"入口页),查询失败保底 entry。
  const flushPendingResumeSelector = useCallback(() => {
    if (!pendingSelectorOpenRef.current) return;
    pendingSelectorOpenRef.current = false;
    setResumeError(null);
    void (async () => {
      let hasSavedResumes = false;
      try {
        const saved = await getAllResumes();
        hasSavedResumes = saved.length > 0;
      } catch (err) {
        console.warn("[AgentChat] getAllResumes failed, fallback to entry step:", err);
      }
      setResumeSelectorInitialStep(hasSavedResumes ? "existing" : "entry");
      setShowResumeSelector(true);
    })();
  }, []);

  // 本轮流式收到 done 且不再 processing 后才弹面板;messages 变化(finalize
  // 落消息、打字机播完)会再触发一次,保证面板出现在完整回复之后。
  useEffect(() => {
    if (isProcessing) return;
    if (lastDoneRunRef.current !== streamRunRef.current) return;
    flushPendingResumeSelector();
  }, [isProcessing, messages, flushPendingResumeSelector]);

  const handleStopGeneration = useCallback(() => {
    const sid = currentSessionId || conversationId;
    if (sid) {
      void fetch(`${apiBaseUrl}/api/agent/stream/stop/${sid}`, {
        method: "POST",
        headers: getAgentRequestHeaders(),
      }).catch(() => {});
    }
    cancelStream("user_stop", "已停止生成。");
  }, [apiBaseUrl, currentSessionId, conversationId, cancelStream]);

  // 保存会话ID到 localStorage
  useEffect(() => {
    if (conversationId && typeof window !== "undefined") {
      const lastSessionKey = `last_session_${window.location.pathname}`;
      localStorage.setItem(lastSessionKey, conversationId);
    }
  }, [conversationId]);

  // 🔧 持久化 UI 预览状态（简历、报告等）
  useEffect(() => {
    // 所有会话（含前端生成的 conv-xxx）都持久化右侧简历展示状态，
    // 这样切走再切回同一会话时能恢复"正在展示的简历"，而不是变空白。
    if (!conversationId) return;
    // 切换会话时会先清空当前 UI，真正的全空态不能反向覆盖旧会话。
    // 但“没有加载简历”的问候轮仍有 TurnSnapshot，必须持久化。
    if (
      !selectedResumeId &&
      loadedResumes.length === 0 &&
      messages.length === 0 &&
      diagnosisToolEvents.length === 0 &&
      structuredEvents.length === 0 &&
      pendingPatches.length === 0
    ) {
      return;
    }

    // 消息 meta（收尾卡/导入卡/chip）与 diff 卡按「稳定 id」持久化：
    // 活跃期消息 id 是临时随机值，恢复时会按 (role, content, index) 重新生成稳定 id，
    // 所以这里保存时就换算成稳定 id，恢复后才能挂回对应消息。
    const activeIdToStableId = new Map<string, string>();
    const messageMetas: Record<string, MessageMeta> = {};
    const messageProcessNodes: Record<string, AgentProcessNode[]> = {};
    const messageTurnSnapshots: Record<string, ConversationTurnSnapshot> = {};
    messages.forEach((msg, index) => {
      const stableId = stableMessageId(msg.content || "", msg.role, index);
      if (msg.id) activeIdToStableId.set(msg.id, stableId);
      if (msg.meta) messageMetas[stableId] = msg.meta;
      if (msg.processNodes?.length) {
        messageProcessNodes[stableId] = msg.processNodes;
      }
      if (msg.turnSnapshot) {
        messageTurnSnapshots[stableId] = {
          ...msg.turnSnapshot,
          messageId: stableId,
        };
      }
    });
    const persistedPatches = pendingPatches
      .filter((p) => p.message_id !== "current") // 进行中的这轮由流式收尾 rebind 后再存
      .map((p) => ({
        ...p,
        message_id: activeIdToStableId.get(p.message_id) || p.message_id,
      }));

    const uiState = {
      selectedResumeId,
      loadedResumes: loadedResumes.map((r) => ({
        id: r.id,
        name: r.name,
        messageId: r.messageId,
        resumeData: r.resumeData, // 右侧 PDF 预览渲染需要
      })),
      diagnosisToolEvents,
      structuredEvents,
      messageMetas,
      messageProcessNodes,
      messageTurnSnapshots,
      pendingPatches: persistedPatches,
    };
    try {
      localStorage.setItem(`ui_state:${conversationId}`, JSON.stringify(uiState));
    } catch (e) {
      // localStorage 超限：清掉其它会话的 ui_state（旧会话回看退化为纯文本，主流程无损）后重试一次
      try {
        const staleKeys: string[] = [];
        for (let i = 0; i < localStorage.length; i++) {
          const key = localStorage.key(i);
          if (key?.startsWith("ui_state:") && key !== `ui_state:${conversationId}`) {
            staleKeys.push(key);
          }
        }
        staleKeys.forEach((key) => localStorage.removeItem(key));
        localStorage.setItem(`ui_state:${conversationId}`, JSON.stringify(uiState));
      } catch (retryError) {
        console.warn("[AgentChat] 持久化 UI 状态失败:", retryError);
      }
    }
  }, [conversationId, selectedResumeId, loadedResumes, diagnosisToolEvents, structuredEvents, messages, pendingPatches]);

  // 说明：
  // 进入 AI 页面时，conversationId 只允许由两处决定：
  // 1) URL 中的 sessionId
  // 2) 初始化时探测到的“最新会话”
  // 这里明确不再使用 resumeId 覆盖 conversationId，避免初始化阶段发生会话抖动。

  useEffect(() => {
    let mounted = true;
    const loadResume = async () => {
      if (!resumeId) {
        // 如果没有 resumeId，不报错，只是不加载简历
        setLoadingResume(false);
        setResumeData(null);
        setResumeError(null);
        return;
      }
      setLoadingResume(true);
      setResumeError(null);
      try {
        const resume = await getResume(resumeId);
        if (!mounted) return;
        if (!resume) {
          setResumeError("未找到对应的简历");
          setResumeData(null);
        } else {
          // 从编辑页带 resumeId 过来：先不自动落地，弹选择让用户决定
          // 「继续编辑这份」还是「开启新会话」（见空态区选择卡片）。
          setCarryResumePrompt(resume);
        }
      } catch (error) {
        if (!mounted) return;
        setResumeError("加载简历失败");
      } finally {
        if (mounted) setLoadingResume(false);
      }
    };
    loadResume();
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId, user?.id]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const media = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(media.matches);
    update();

    if (media.addEventListener) {
      media.addEventListener("change", update);
    } else {
      media.addListener(update);
    }

    return () => {
      if (media.removeEventListener) {
        media.removeEventListener("change", update);
      } else {
        media.removeListener(update);
      }
    };
  }, []);

  useEffect(() => {
    if (isDesktop) {
    }
  }, [isDesktop]);

  useEffect(() => {
    if (!allowPdfAutoRender) return;
    if (!selectedLoadedResume) return;
    void renderResumePdfPreview(selectedLoadedResume);
  }, [
    selectedLoadedResume,
    renderResumePdfPreview,
    allowPdfAutoRender,
  ]);

  // 会话ID确定后，仅加载“当前选中会话”的消息内容
  useEffect(() => {
    // 等待初始化阶段确定最终会话ID后再加载
    if (!initialSessionResolved) {
      return;
    }

    // If createNewSession is in progress, skip any session loading to avoid
    // restoring stale session data from the old URL sessionId.
    if (isCreatingNewSessionRef.current) {
      return;
    }

    const routeSessionId =
      new URLSearchParams(location.search).get("sessionId")?.trim() || null;
    const isEphemeralConversation =
      !routeSessionId && conversationId.startsWith("conv-");

    // /agent/new 的本地临时会话不走后端加载，避免 404 Session not found
    if (isEphemeralConversation) {
      if (currentSessionId !== conversationId) {
        setCurrentSessionId(conversationId);
      }
      setResumeError(null);
      return;
    }

    // 如果已经加载了当前会话ID，不重复加载
    if (currentSessionId === conversationId) {
      return;
    }

    let mounted = true;
    const autoLoadSession = async () => {
      try {
        // 尝试加载会话历史
        // 防御性检查：确保 conversationId 不为空
        if (!conversationId || conversationId.trim() === "") {
          console.warn(
            "[AgentChat] Cannot load session: conversationId is empty",
          );
          return;
        }
        let data: { messages?: any[]; total?: number } | null = null;
        if (!isAuthenticated) {
          const localSession = getLocalAgentSession(conversationId);
          if (!localSession) {
            if (conversationId.startsWith("conv-")) {
              setCurrentSessionId(conversationId);
              setResumeError(null);
            } else {
              setResumeError("会话加载失败：未找到本地会话记录");
            }
            return;
          }
          data = {
            messages: localSession.messages,
            total: localSession.messages.length,
          };
        } else {
          const resp = await fetch(
            `${apiBaseUrl}/api/agent/history/sessions/${conversationId}`,
            {
              headers: getAuthHeaders(),
            },
          );
          if (!mounted) return;
          if (!resp.ok) {
            let detail = `HTTP ${resp.status} ${resp.statusText}`;
            try {
              const errData = await resp.clone().json();
              if (errData?.detail?.message) {
                detail = errData.detail.message;
              } else if (typeof errData?.detail === "string") {
                detail = errData.detail;
              } else if (errData?.error_message) {
                detail = errData.error_message;
              }
            } catch {
              // ignore json parse errors
            }
            // 会话不存在，使用新的会话ID
            console.log(
              `[AgentChat] Session ${conversationId} load failed: ${detail}`,
            );
            setResumeError(`会话加载失败：${detail}`);
            return;
          }
          data = await resp.json();
        }
        if (!mounted || !data) return;
        setResumeError(null);

        // 🔧 恢复 UI 数据（包含右侧选中态），避免“展示简历后又自动消失”。
        let savedMessageMetas: Record<string, MessageMeta> | null = null;
        let savedMessageProcessNodes: Record<string, AgentProcessNode[]> | null = null;
        let savedMessageTurnSnapshots: Record<string, ConversationTurnSnapshot> | null = null;
        try {
          const savedUiState = localStorage.getItem(
            `ui_state:${conversationId}`,
          );
          if (savedUiState) {
            const {
              loadedResumes: sLrs,
              selectedResumeId: savedSelectedResumeId,
              diagnosisToolEvents: savedDiagnosisToolEvents,
              structuredEvents: savedStructuredEvents,
              messageMetas: sMetas,
              messageProcessNodes: sProcessNodes,
              messageTurnSnapshots: sTurnSnapshots,
              pendingPatches: sPatches,
            } = JSON.parse(savedUiState);
            // 恢复已加载列表的元数据，数据会在后续逻辑中通过消息或重新加载补齐；
            // 清洗历史坏快照：上线前落盘的 agent 格式 resumeData 恢复时转 canonical
            const cleanedLrs = cleanLoadedResumesSnapshot(sLrs);
            if (Array.isArray(cleanedLrs) && cleanedLrs.length > 0) {
              setLoadedResumes(cleanedLrs);
            }
            if (Array.isArray(savedDiagnosisToolEvents)) {
              setDiagnosisToolEvents(savedDiagnosisToolEvents);
            }
            if (Array.isArray(savedStructuredEvents)) {
              setStructuredEvents(savedStructuredEvents);
            }
            if (sMetas && typeof sMetas === "object") {
              savedMessageMetas = sMetas;
            }
            if (sProcessNodes && typeof sProcessNodes === "object") {
              savedMessageProcessNodes = sProcessNodes;
            }
            if (sTurnSnapshots && typeof sTurnSnapshots === "object") {
              savedMessageTurnSnapshots =
                parseConversationTurnSnapshotMap(sTurnSnapshots);
            }
            // 恢复 diff 对比卡（含已应用/已拒绝终态），让历史会话能看到「改过什么」；
            // 同时把恢复的简历同步进 ResumeContext，pending 卡恢复后仍可正常「应用」
            if (Array.isArray(sPatches) && sPatches.length > 0) {
              restorePatches(sPatches);
              const sel =
                (Array.isArray(cleanedLrs) &&
                  (cleanedLrs.find((r: any) => r.id === savedSelectedResumeId) ||
                    cleanedLrs[cleanedLrs.length - 1])) ||
                null;
              if (sel?.resumeData) setResume(sel.resumeData);
            }
            if (
              typeof savedSelectedResumeId === "string" &&
              savedSelectedResumeId.trim() !== ""
            ) {
              setSelectedResumeId(savedSelectedResumeId);
              setAllowPdfAutoRender(true);
            } else {
              setSelectedResumeId(null);
              setAllowPdfAutoRender(false);
            }
          }
        } catch (e) {
          console.warn("[AgentChat] Failed to restore UI state:", e);
        }

        // 过滤 tool 角色消息（与 loadSession 一致）：index 语义两侧对齐，meta/patch 按稳定 id 挂回才不错位
        const userVisibleMessages = (data.messages || []).filter(
          (m: any) => m.role === "user" || m.role === "assistant",
        );

        const loadedMessages: Message[] = userVisibleMessages.map(
          (m: any, index: number) => {
            const rawContent = m.content;
            const content =
              typeof rawContent === "string"
                ? rawContent
                : rawContent != null
                ? JSON.stringify(rawContent)
                : "";
            const id = stableMessageId(content, m.role || "unknown", index);
            return {
              id,
              role: m.role === "user" ? "user" : "assistant",
              content,
              thought: m.thought || undefined,
              timestamp: new Date().toISOString(),
              meta: savedMessageMetas?.[id],
              processNodes: savedMessageProcessNodes?.[id],
              turnSnapshot: savedMessageTurnSnapshots?.[id],
            };
          },
        );

        const dedupedMessages = dedupeLoadedMessages(loadedMessages);
        if (!mounted) return;
        setMessages(dedupedMessages);
        setCurrentSessionId(conversationId);
        lastPersistedCountBySessionRef.current[conversationId] =
          typeof data?.total === "number"
            ? data.total
            : dedupedMessages.length;
        console.log(
          `[AgentChat] Auto-loaded session ${conversationId} with ${dedupedMessages.length} messages`,
        );
      } catch (error) {
        console.error("[AgentChat] Failed to auto-load session:", error);
      }
    };

    autoLoadSession();
    return () => {
      mounted = false;
    };
  }, [conversationId, currentSessionId, initialSessionResolved, apiBaseUrl, getAuthHeaders, isAuthenticated, location.search]); // 仅在会话确定后加载

  useEffect(() => {
    if (resumeData) {
      setResume(resumeData);
    }
  }, [resumeData, setResume]);

  useEffect(() => {
    if (!lastError) return;
    setResumeError(lastError);
  }, [lastError]);

  // When a patch is applied via ResumeContext, also update local resumeData and
  // loadedResumes so the PDF re-renders with the new content.
  useEffect(() => {
    if (!patchAppliedAt) return;

    // context.resume 是补丁「应用/撤销」后的权威当前态：应用后=已并入全部 applied 补丁，
    // 撤销后=应用前快照。直接同步到本地预览态（resumeData + loadedResumes），既覆盖应用、
    // 也天然覆盖撤销回退——修复此前 toast 撤销只回退 Context/DB、右侧预览却不回灌的 bug。
    // （patchAppliedAt 与 contextResume 在同一次提交里一起变，effect 闭包取到的是新值）
    if (contextResume) {
      setResumeData(contextResume);
      setLoadedResumes(prev => {
        const targetId = selectedResumeId || prev[0]?.id;
        if (!targetId) return prev;
        return prev.map(item =>
          item.id === targetId && item.resumeData
            ? { ...item, resumeData: contextResume }
            : item,
        );
      });
    }

    setResumePdfPreview(prev => {
      const targetId = selectedResumeId || Object.keys(prev)[0];
      if (!targetId) return prev;
      return { ...prev, [targetId]: { ...EMPTY_RESUME_PDF_STATE } };
    });
    setAllowPdfAutoRender(true);
    // 结果直接可见：短暂高亮预览面板，引导视线看右侧刚更新
    setPreviewJustUpdated(true);
    if (previewPulseTimerRef.current) clearTimeout(previewPulseTimerRef.current);
    previewPulseTimerRef.current = setTimeout(() => setPreviewJustUpdated(false), 1600);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patchAppliedAt]);

  useEffect(() => {
    if (answerCompleteCount <= 0 || !resumeId) {
      return;
    }
    // If there are pending patches waiting for user approval, skip auto-refresh.
    // The PDF will re-render when the user clicks Apply (patchAppliedAt effect).
    if (pendingPatches.some(p => p.status === 'pending')) {
      return;
    }

    let mounted = true;

    // 🔧 改进：延迟刷新，确保后端持久化已完成
    const refreshResume = async () => {
      // 延迟 500ms 后刷新，给后端持久化时间
      await new Promise((resolve) => setTimeout(resolve, 500));

      if (!mounted) return;

      try {
        const resume = await getResume(resumeId);
        if (!mounted) return;
        if (resume) {
          const resolvedUserId = user?.id ?? (resume as any).user_id ?? null;
          const resumeDataWithMeta = {
            ...(resume.data || {}),
            resume_id: resume.id,
            user_id: resolvedUserId,
            _meta: {
              resume_id: resume.id,
              user_id: resolvedUserId,
            },
          };
          setResumeData(resumeDataWithMeta as ResumeData);
          setResume(resumeDataWithMeta as ResumeData);
          setLoadedResumes((prev) => {
            const targetId = selectedResumeId || resumeId;
            if (!targetId) return prev;
            const exists = prev.some((item) => item.id === targetId);
            if (!exists) return prev;
            return prev.map((item) =>
              item.id === targetId
                ? { ...item, resumeData: resumeDataWithMeta as ResumeData }
                : item,
            );
          });
          console.log(
            "[AgentChat] Resume data refreshed after agent completion",
          );
        }
      } catch (error) {
        console.error("[AgentChat] Failed to refresh resume data:", error);
      }
    };

    refreshResume();
    return () => {
      mounted = false;
    };
  }, [answerCompleteCount, resumeId, user?.id, pendingPatches]);

  const isHtmlTemplate = resumeData?.templateType === "html";

  // Auto-scroll to bottom (throttled to reduce layout thrash during streaming)
  useEffect(() => {
    // 选择器打开时不跟随流式输出滚动，避免页面一直被“拽”到底部
    if (showResumeSelector) return;
    if (autoScrollTimerRef.current !== null) {
      window.clearTimeout(autoScrollTimerRef.current);
    }
    autoScrollTimerRef.current = window.setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: isProcessing ? "auto" : "smooth",
        block: "end",
      });
      autoScrollTimerRef.current = null;
    }, isProcessing ? 90 : 140);
  }, [messages, currentThought, currentAnswer, isProcessing, showResumeSelector]);

  useEffect(() => {
    return () => {
      if (autoScrollTimerRef.current !== null) {
        window.clearTimeout(autoScrollTimerRef.current);
        autoScrollTimerRef.current = null;
      }
    };
  }, []);

  // 打开「展示简历」选择器时滚到对话底部，确保卡片在可视区域内。
  useEffect(() => {
    if (!showResumeSelector) return;
    const timer = window.setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, 120);
    return () => {
      window.clearTimeout(timer);
    };
  }, [showResumeSelector]);

  useEffect(() => {
    currentProcessNodesRef.current = currentProcessNodes;
  }, [currentProcessNodes]);

  useEffect(() => {
    currentRunStateRef.current = currentRunState;
  }, [currentRunState]);

  /**
   * Finalize current message and add to history
   */
  const finalizeMessage = useCallback(() => {
    if (lastFinalizedRunRef.current === streamRunRef.current) {
      return;
    }
    // 防止重复调用
    if (isFinalizedRef.current) {
      console.log("[AgentChat] finalizeMessage already called, skipping");
      // 仅在没有活跃流内容时兜底释放，避免误清空下一条消息。
      if (
        !isProcessing &&
        !readLiveThought().trim() &&
        !readLiveAnswer().trim()
      ) {
        finalizeStream();
        window.setTimeout(() => {
          isFinalizedRef.current = false;
        }, 80);
      }
      return;
    }

    isFinalizedRef.current = true;

    // currentRunState 是完成态权威（reducer 在 sourceCompleted 后保留内容），
    // 直接取最新 run state；闭包里的 currentThought/currentAnswer 作为同值兜底。
    const thoughtStateValue = currentThought.trim();
    const answerStateValue = currentAnswer.trim();
    const resolvedThought = readLiveThought().trim() || thoughtStateValue;
    const answer = readLiveAnswer().trim() || answerStateValue;
    const thought =
      resolvedThought.trim() === "正在思考..." ? "" : resolvedThought;

    console.log("[AgentChat] finalizeMessage called", {
      thoughtLength: thought.length,
      answerLength: answer.length,
      thoughtStateLength: thoughtStateValue.length,
      answerStateLength: answerStateValue.length,
      streamRun: streamRunRef.current,
    });

    if (!thought && !answer) {
      if (isProcessing) {
        // 若已收到当前轮 done，但内容为空（常见于 agent_error），主动收口本轮，避免重复触发警告。
        if (lastDoneRunRef.current === streamRunRef.current) {
          pendingFinalizeAfterTypewriterRef.current = false;
          lastFinalizedRunRef.current = streamRunRef.current;
          finalizeStream();
          window.setTimeout(() => {
            isFinalizedRef.current = false;
          }, 120);
          return;
        }
        console.warn("[AgentChat] finalizeMessage called with NO content while still processing. This might be a race condition.");
        // 新一轮流式开始后，可能收到上一轮延迟 done，直接忽略，避免清空当前轮状态。
        isFinalizedRef.current = false;
        return;
      }
      console.log("[AgentChat] No content to finalize, just resetting state");
      pendingFinalizeAfterTypewriterRef.current = false;
      lastFinalizedRunRef.current = streamRunRef.current;
      finalizeStream();
      setTimeout(() => {
        isFinalizedRef.current = false;
      }, 100);
      return;
    }

    const currentEditDiff = resumeEditDiffs.find(
      (entry) => entry.messageId === "current",
    )?.data as
      | {
          before?: string;
          after?: string;
        }
      | undefined;
    const markdownEditDiff = extractResumeEditDiffFromMarkdown(answer || "");
    const latestUserMessage = [...messages]
      .reverse()
      .find((item) => item.role === "user")?.content || "";
    const normalizedLatestUserMessage = latestUserMessage.trim();
    const replaceTargetMatch = normalizedLatestUserMessage.match(
      /(?:改成|改为|变成|改到)\s*["“]?([^"”\s，。,！!？?]+)["”]?/i,
    );
    const requestedReplacement = replaceTargetMatch?.[1]?.trim() || "";
    const hasEditIntent = /(?:把|将|帮我|请)?(?:我的)?(?:名字|姓名|公司|职位|学校|电话|邮箱).*(?:改成|改为|变成)|(?:改成|改为|变成)/.test(
      normalizedLatestUserMessage,
    );
    const diffAfterValue = (
      currentEditDiff?.after ||
      markdownEditDiff?.after ||
      ""
    ).trim();
    const answerLooksLikeEditDiff = Boolean(markdownEditDiff);
    const isStaleEditDiffResponse =
      (answerLooksLikeEditDiff || Boolean(diffAfterValue)) &&
      ((!hasEditIntent &&
        /(?:你好|hello|hi|谢谢|加载简历|查看简历)/i.test(
          normalizedLatestUserMessage,
        )) ||
        (requestedReplacement &&
          Boolean(diffAfterValue) &&
          diffAfterValue !== requestedReplacement));

    if (isStaleEditDiffResponse) {
      console.warn("[AgentChat] stale edit diff response ignored", {
        latestUserMessage: normalizedLatestUserMessage,
        requestedReplacement,
        diffAfterValue,
      });
      pendingFinalizeAfterTypewriterRef.current = false;
      setSearchResults((prev) => prev.filter((item) => item.messageId !== "current"));
      setLoadedResumes((prev) => prev.filter((item) => item.messageId !== "current"));
      setResumeEditDiffs((prev) => prev.filter((item) => item.messageId !== "current"));
      setDiagnosisToolEvents((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      finalizeStream();
      window.setTimeout(() => {
        isFinalizedRef.current = false;
      }, 120);
      return;
    }

    const finalizeSignature = `${streamRunRef.current}::${thought}::${answer}`;
    if (lastFinalizedSignatureRef.current === finalizeSignature) {
      console.log("[AgentChat] Duplicate finalize signature skipped");
      pendingFinalizeAfterTypewriterRef.current = false;
      finalizeStream();
      window.setTimeout(() => {
        isFinalizedRef.current = false;
      }, 120);
      return;
    }
    lastFinalizedSignatureRef.current = finalizeSignature;

    refreshAfterSaveRef.current = true;
    pendingSaveRef.current = true;
    // Use the pre-generated ID from sendUserTextMessage so resume patches can reference it
    const uniqueId = currentAssistantMessageIdRef.current ?? `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    currentAssistantMessageIdRef.current = null;
    const completedAt = new Date().toISOString();
    const newMessage: Message = {
      id: uniqueId,
      role: "assistant",
      content: answer || "",
      timestamp: completedAt,
    };
    if (thought) {
      newMessage.thought = thought;
    }
    if (currentProcessNodesRef.current.length > 0) {
      newMessage.processNodes = currentProcessNodesRef.current;
    }
    if (currentRunStateRef.current) {
      newMessage.turnSnapshot = buildConversationTurnSnapshot(
        buildVisibleConversationRun(
          currentRunStateRef.current,
          stripResumeEditMarkdown,
        ),
        { messageId: uniqueId, completedAt },
      );
    }

    setSearchResults((prev) => rebindCurrentMessageId(prev, uniqueId));
    setLoadedResumes((prev) => rebindCurrentMessageId(prev, uniqueId));
    setResumeEditDiffs((prev) => rebindCurrentMessageId(prev, uniqueId));
    setDiagnosisToolEvents((prev) => rebindCurrentMessageId(prev, uniqueId));
    setStructuredEvents((prev) => rebindCurrentMessageId(prev, uniqueId));
    // 把当前流式 patch 绑定到这条 finalize 后的 assistant 消息上
    rebindCurrentPatches(uniqueId);

    setMessages((prev) => {
      const last = prev[prev.length - 1];
      const lastContent = typeof last?.content === "string" ? last.content : "";
      const lastThought = typeof (last as any)?.thought === "string" ? (last as any).thought : "";
      if (
        last &&
        last.role === "assistant" &&
        lastContent.trim() === newMessage.content.trim() &&
        lastThought.trim() ===
          (newMessage.thought || "").trim()
      ) {
        console.log("[AgentChat] Duplicate assistant message skipped");
        return prev;
      }
      const updated = [...prev, newMessage];
      console.log("[AgentChat] Messages updated", { count: updated.length });

      return updated;
    });
    lastFinalizedRunRef.current = streamRunRef.current;

    // Clear transient stream buffers only after message finalization work has been enqueued.
    pendingFinalizeAfterTypewriterRef.current = false;

    finalizeStream();
  }, [
    finalizeStream,
    currentAnswer,
    currentThought,
    resumeEditDiffs,
    messages,
    loadedResumes,
    selectedResumeId,
  ]);

  const finalizeAfterTypewriter = useCallback(() => {
    if (!pendingFinalizeAfterTypewriterRef.current) {
      return;
    }

    pendingFinalizeAfterTypewriterRef.current = false;

    finalizeMessage();

    window.setTimeout(() => {
      isFinalizedRef.current = false;
    }, 150);
  }, [finalizeMessage]);

  const refreshSessions = useCallback(() => {
    setSessionsRefreshKey((prev) => prev + 1);
  }, []);

  const checkCanCreateSession = useCallback(async (): Promise<boolean> => {
    // 2026-07-17 身份统一：该客户端预检原本仅对 legacy JWT 用户生效（BetterAuth
    // 用户 auth_token 恒空、恒直接放行），行为保持不变；会话上限由后端
    // session_limits 权威兜底。
    return true;
  }, []);

  // 检测并加载简历
  const detectAndLoadResume = useCallback(
    async (input: string, messageId: string) => {
      // 检查是否已经为这条消息加载过简历
      if (loadedResumes.some((r) => r.messageId === messageId)) {
        return;
      }

      // 检测简历加载的关键词
      const resumeLoadPatterns = [
        /(?:加载|打开|查看|显示)(?:我的|这个|一份)?(?:简历|CV)/,
        /(?:简历|CV)(?:名称|ID)?[:：]\s*([^\n]+)/,
      ];

      let resumeIdOrName: string | null = null;
      for (const pattern of resumeLoadPatterns) {
        const match = input.match(pattern);
        if (match) {
          if (match[1]) {
            // 提取了简历名称或ID
            resumeIdOrName = match[1].trim();
          } else {
            // 只是检测到关键词，没有具体名称
            resumeIdOrName = "";
          }
          break;
        }
      }

      // 如果没有检测到关键词，直接返回
      if (resumeIdOrName === null) {
        return;
      }

      try {
        let resume: any = null;
        let resumeName = "";

        if (resumeIdOrName === "") {
          // 没有指定具体简历，尝试获取用户的第一份简历
          const allResumes = await getAllResumes();
          if (allResumes.length > 0) {
            resume = allResumes[0];
            resumeName = resume.name || "我的简历";
          } else {
            console.log("[AgentChat] 用户没有简历");
            return;
          }
        } else {
          // 尝试通过ID或名称查找简历
          const allResumes = await getAllResumes();
          resume = allResumes.find(
            (r) => r.id === resumeIdOrName || r.name === resumeIdOrName,
          );

          if (!resume) {
            // 如果找不到，尝试直接通过ID获取
            resume = await getResume(resumeIdOrName);
          }

          if (resume) {
            resumeName = resume.name || resumeIdOrName;
          } else {
            console.log("[AgentChat] 未找到简历:", resumeIdOrName);
            return;
          }
        }

        if (resume) {
          const resolvedUserId = user?.id ?? (resume as any).user_id ?? null;
          const resumeDataWithMeta = {
            ...(resume.data || {}),
            resume_id: resume.id,
            user_id: resolvedUserId,
            alias: resume.alias,
            _meta: {
              resume_id: resume.id,
              user_id: resolvedUserId,
            },
          };

          // 添加到加载的简历列表
          setLoadedResumes((prev) => [
            ...prev,
            {
              id: resume.id,
              name: resumeName,
              messageId,
              resumeData: resumeDataWithMeta as ResumeData,
            },
          ]);

          console.log("[AgentChat] 检测到简历加载:", resume.id, resumeName);
        }
      } catch (err) {
        console.error("[AgentChat] 加载简历失败:", err);
      }
    },
    [loadedResumes, user?.id],
  );

  const buildSavePayload = useCallback((messagesToSave: Message[]) => {
    return messagesToSave.map((msg) => ({
      role: msg.role,
      content: msg.content,
      thought: msg.thought,
    }));
  }, []);

  const computeLastMessageHash = useCallback((messagesToSave: Message[]) => {
    if (!messagesToSave.length) return "";
    const last = messagesToSave[messagesToSave.length - 1];
    const raw = `${last.role}|${last.content || ""}|${last.thought || ""}`;
    let hash = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      hash ^= raw.charCodeAt(i);
      hash +=
        (hash << 1) +
        (hash << 4) +
        (hash << 7) +
        (hash << 8) +
        (hash << 24);
    }
    return (hash >>> 0).toString(16);
  }, []);

  const persistSessionSnapshot = useCallback(
    async (
      sessionId: string,
      messagesToSave: Message[],
      shouldRefresh = false,
    ) => {
      // 如果消息列表为空，则不执行持久化，避免在数据库中产生空会话
      if (!messagesToSave || messagesToSave.length === 0) {
        return;
      }
      if (historyApiUnavailableRef.current) {
        return;
      }

      // 验证 sessionId，如果为空则生成新的会话 ID
      let validSessionId = sessionId;
      if (!validSessionId || validSessionId.trim() === "") {
        // 如果为空，使用 conversationId 或生成新的
        validSessionId = conversationId || `conv-${Date.now()}`;
        if (validSessionId !== conversationId) {
          setConversationId(validSessionId);
        }
        console.log(`[AgentChat] Generated new session ID: ${validSessionId}`);
      }

      const payload = buildSavePayload(messagesToSave);
      const payloadKey = JSON.stringify(payload);
      if (payloadKey === lastSavedKeyRef.current) {
        return;
      }
      const clientSaveSeq = ++saveClientSeqRef.current;
      const lastMessageHash = computeLastMessageHash(messagesToSave);

      if (!isAuthenticated) {
        const knownPersistedCount =
          lastPersistedCountBySessionRef.current[validSessionId] ?? 0;
        const canTryAppend =
          HISTORY_APPEND_MODE &&
          knownPersistedCount > 0 &&
          knownPersistedCount <= messagesToSave.length &&
          Boolean(getLocalAgentSession(validSessionId));

        if (canTryAppend) {
          const deltaMessages = messagesToSave.slice(knownPersistedCount);
          if (deltaMessages.length > 0) {
            appendLocalAgentMessages(
              validSessionId,
              buildSavePayload(deltaMessages),
            );
          }
        } else {
          saveLocalAgentSession(validSessionId, payload);
        }
        lastPersistedCountBySessionRef.current[validSessionId] =
          messagesToSave.length;
        lastSavedKeyRef.current = payloadKey;
        if (shouldRefresh) {
          refreshSessions();
        }
        return;
      }

      if (saveInFlightRef.current) {
        queuedSaveRef.current = {
          sessionId: validSessionId,
          messages: messagesToSave,
          shouldRefresh,
        };
        return;
      }

      saveInFlightRef.current = (async () => {
        try {
          const fullSave = async () => {
            const resp = await fetch(
              `${apiBaseUrl}/api/agent/history/sessions/${validSessionId}/save`,
              {
                method: "POST",
                headers: getAuthHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({
                  messages: payload,
                  client_save_seq: clientSaveSeq,
                  last_message_hash: lastMessageHash,
                }),
              },
            );
            if (resp.ok) {
              lastPersistedCountBySessionRef.current[validSessionId] =
                messagesToSave.length;
            }
            return resp;
          };

          let resp: Response;
          const knownPersistedCount =
            lastPersistedCountBySessionRef.current[validSessionId] ?? 0;
          const appendDisabled =
            appendDisabledBySessionRef.current[validSessionId] === true;
          const canTryAppend =
            HISTORY_APPEND_MODE &&
            !appendDisabled &&
            knownPersistedCount > 0 &&
            knownPersistedCount <= messagesToSave.length;

          if (canTryAppend) {
            const deltaMessages = messagesToSave.slice(knownPersistedCount);
            if (deltaMessages.length === 0) {
              lastSavedKeyRef.current = payloadKey;
              return;
            }
            resp = await fetch(
              `${apiBaseUrl}/api/agent/history/sessions/${validSessionId}/append`,
              {
                method: "POST",
                headers: getAuthHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({
                  base_seq: knownPersistedCount,
                  messages_delta: buildSavePayload(deltaMessages),
                  client_save_seq: clientSaveSeq,
                  last_message_hash: lastMessageHash,
                }),
              },
            );

            // base_seq 冲突时自动回退到 full snapshot save
            if (resp.status === 409) {
              appendDisabledBySessionRef.current[validSessionId] = true;
              resp = await fullSave();
            } else if (resp.ok) {
              const body = await resp
                .clone()
                .json()
                .catch(() => null as any);
              if (typeof body?.new_seq === "number") {
                lastPersistedCountBySessionRef.current[validSessionId] =
                  body.new_seq;
              } else {
                lastPersistedCountBySessionRef.current[validSessionId] =
                  messagesToSave.length;
              }
            }
          } else {
            resp = await fullSave();
          }

          if (!resp.ok) {
            if (resp.status === 404) {
              historyApiUnavailableRef.current = true;
              queuedSaveRef.current = null;
              scheduledSaveRef.current = null;
              return;
            }
            let errorDetail = "";
            let parsedError: unknown = null;
            try {
              const raw = await resp.clone().text();
              if (raw) {
                try {
                  parsedError = JSON.parse(raw);
                  const parsed = parsedError as {
                    message?: string;
                    detail?: string | { message?: string };
                  };
                  errorDetail =
                    parsed?.message ||
                    (typeof parsed?.detail === "string"
                      ? parsed.detail
                      : parsed?.detail?.message) ||
                    raw;
                } catch {
                  errorDetail = raw;
                }
              }
            } catch {
              // ignore parse errors
            }
            if (isSessionLimitExceededResponse(resp.status, parsedError)) {
              toast.error(getSessionLimitMessage());
              queuedSaveRef.current = null;
              scheduledSaveRef.current = null;
              return;
            }
            console.error(
              `[AgentChat] Failed to save session: ${resp.status}${
                errorDetail ? ` - ${String(errorDetail).slice(0, 300)}` : ""
              }`,
            );
            const retryCount = (saveRetryRef.current[payloadKey] || 0) + 1;
            if (retryCount <= 2) {
              saveRetryRef.current[payloadKey] = retryCount;
              queuedSaveRef.current = {
                sessionId: validSessionId,
                messages: messagesToSave,
                shouldRefresh,
              };
              setTimeout(() => {
                if (!saveInFlightRef.current && queuedSaveRef.current) {
                  const next = queuedSaveRef.current;
                  queuedSaveRef.current = null;
                  void persistSessionSnapshot(
                    next.sessionId,
                    next.messages,
                    next.shouldRefresh,
                  );
                }
              }, 800 * retryCount);
            }
            return;
          }
          lastSavedKeyRef.current = payloadKey;
          delete saveRetryRef.current[payloadKey];
          if (shouldRefresh) {
            refreshSessions();
          }
        } catch (error) {
          console.error("[AgentChat] Failed to save session snapshot:", error);
          const retryCount = (saveRetryRef.current[payloadKey] || 0) + 1;
          if (retryCount <= 2) {
            saveRetryRef.current[payloadKey] = retryCount;
            queuedSaveRef.current = {
              sessionId: validSessionId,
              messages: messagesToSave,
              shouldRefresh,
            };
            setTimeout(() => {
              if (!saveInFlightRef.current && queuedSaveRef.current) {
                const next = queuedSaveRef.current;
                queuedSaveRef.current = null;
                void persistSessionSnapshot(
                  next.sessionId,
                  next.messages,
                  next.shouldRefresh,
                );
              }
            }, 800 * retryCount);
          }
        } finally {
          saveInFlightRef.current = null;
          if (queuedSaveRef.current) {
            const next = queuedSaveRef.current;
            queuedSaveRef.current = null;
            void persistSessionSnapshot(
              next.sessionId,
              next.messages,
              next.shouldRefresh,
            );
          }
        }
      })();
      await saveInFlightRef.current;
    },
    [
      conversationId,
      buildSavePayload,
      computeLastMessageHash,
      getAuthHeaders,
      isAuthenticated,
      refreshSessions,
    ],
  );

  const schedulePersistSessionSnapshot = useCallback(
    (sessionId: string, messagesToSave: Message[], shouldRefresh = false) => {
      if (!sessionId || sessionId.trim() === "" || messagesToSave.length === 0) {
        return;
      }

      if (!isAuthenticated) {
        if (saveDebounceTimerRef.current) {
          clearTimeout(saveDebounceTimerRef.current);
          saveDebounceTimerRef.current = null;
        }
        scheduledSaveRef.current = null;
        void persistSessionSnapshot(sessionId, messagesToSave, shouldRefresh);
        return;
      }

      const existing = scheduledSaveRef.current;
      scheduledSaveRef.current = {
        sessionId,
        messages: messagesToSave,
        shouldRefresh: shouldRefresh || Boolean(existing?.shouldRefresh),
      };

      if (saveDebounceTimerRef.current) {
        clearTimeout(saveDebounceTimerRef.current);
      }
      saveDebounceTimerRef.current = setTimeout(() => {
        const pending = scheduledSaveRef.current;
        scheduledSaveRef.current = null;
        saveDebounceTimerRef.current = null;
        if (!pending) return;
        void persistSessionSnapshot(
          pending.sessionId,
          pending.messages,
          pending.shouldRefresh,
        );
      }, 1800);
    },
    [isAuthenticated, persistSessionSnapshot],
  );

  const flushScheduledSave = useCallback(async () => {
    if (saveDebounceTimerRef.current) {
      clearTimeout(saveDebounceTimerRef.current);
      saveDebounceTimerRef.current = null;
    }
    const pending = scheduledSaveRef.current;
    scheduledSaveRef.current = null;
    if (pending) {
      await persistSessionSnapshot(
        pending.sessionId,
        pending.messages,
        pending.shouldRefresh,
      );
    }
  }, [persistSessionSnapshot]);

  const waitForPendingSave = useCallback(async () => {
    await flushScheduledSave();
    if (saveInFlightRef.current) {
      await saveInFlightRef.current;
    }
    if (pendingSaveRef.current) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (saveInFlightRef.current) {
        await saveInFlightRef.current;
      }
    }
  }, [flushScheduledSave]);

  useEffect(() => {
    if (!pendingSaveRef.current) {
      return;
    }
    pendingSaveRef.current = false;
    const shouldRefresh = refreshAfterSaveRef.current;
    refreshAfterSaveRef.current = false;
    // 验证 conversationId 不为空且消息不为空
    if (conversationId && conversationId.trim() !== "" && messages.length > 0) {
      schedulePersistSessionSnapshot(conversationId, messages, shouldRefresh);
    } else {
      console.log(
        "[AgentChat] Skipping save: conversationId is empty or no messages",
      );
    }
  }, [conversationId, messages, schedulePersistSessionSnapshot]);

  const saveCurrentSession = useCallback(() => {
    if (isProcessing || readLiveThought() || readLiveAnswer()) {
      pendingSaveRef.current = true;
      return;
    }
    // 只有当有消息时才标记需要保存
    if (messages && messages.length > 0) {
      pendingSaveRef.current = true;
      void persistSessionSnapshot(conversationId, messages);
    }
  }, [
    conversationId,
    finalizeMessage,
    isProcessing,
    messages,
    persistSessionSnapshot,
  ]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      const pending = scheduledSaveRef.current;
      if (!pending) return;
      void persistSessionSnapshot(
        pending.sessionId,
        pending.messages,
        pending.shouldRefresh,
      );
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      if (saveDebounceTimerRef.current) {
        clearTimeout(saveDebounceTimerRef.current);
        saveDebounceTimerRef.current = null;
      }
    };
  }, [persistSessionSnapshot]);

  const resetToBlankSession = useCallback(() => {
    isCreatingNewSessionRef.current = true;
    hasBootstrappedSessionRef.current = true;
    setInitialSessionResolved(true);

    pendingSaveRef.current = false;
    queuedSaveRef.current = null;
    scheduledSaveRef.current = null;
    if (saveDebounceTimerRef.current) {
      clearTimeout(saveDebounceTimerRef.current);
      saveDebounceTimerRef.current = null;
    }

    const newId = `conv-${Date.now()}`;
    setMessages([]);
    setCurrentSessionId(newId);
    setConversationId(newId);
    lastPersistedCountBySessionRef.current[newId] = 0;
    lastSavedKeyRef.current = "";
    setSelectedResumeId(null);
    setAllowPdfAutoRender(false);
    setLoadedResumes([]);
    setDiagnosisToolEvents([]);
    setStructuredEvents([]);
    setSearchResults([]);
    setResumeEditDiffs([]);
    setActiveSearchPanel(null);
    setResumePdfPreview({});
    setResumeError(null);
    finalizeStream();

    navigate("/agent/new", { replace: true });
    window.setTimeout(() => {
      isCreatingNewSessionRef.current = false;
    }, 0);
  }, [finalizeStream, navigate]);

  const deleteSession = async (sessionId: string) => {
    const routeSessionId =
      new URLSearchParams(location.search).get("sessionId")?.trim() || null;
    const isActiveSession =
      sessionId === conversationId ||
      sessionId === currentSessionId ||
      sessionId === routeSessionId;

    if (isActiveSession) {
      pendingSaveRef.current = false;
      queuedSaveRef.current = null;
      scheduledSaveRef.current = null;
      if (saveDebounceTimerRef.current) {
        clearTimeout(saveDebounceTimerRef.current);
        saveDebounceTimerRef.current = null;
      }
    }

    try {
      if (!isAuthenticated) {
        deleteLocalAgentSession(sessionId);
      } else {
        const resp = await fetch(
          `${apiBaseUrl}/api/agent/history/${sessionId}`,
          {
            method: "DELETE",
            headers: getAuthHeaders(),
          },
        );
        if (!resp.ok) throw new Error(`Failed to delete session: ${resp.status}`);
      }

      fetch(`${apiBaseUrl}/api/agent/stream/session/${sessionId}`, {
        method: "DELETE",
        headers: getAgentRequestHeaders(),
      }).catch(() => undefined);

      try {
        localStorage.removeItem(`ui_state:${sessionId}`);
      } catch {
        // ignore storage errors
      }
      delete lastPersistedCountBySessionRef.current[sessionId];

      refreshSessions();

      if (isActiveSession) {
        resetToBlankSession();
      }
    } catch (error) {
      console.error("[AgentChat] Failed to delete session:", error);
      toast.error("删除会话失败，请稍后重试");
    }
  };

  const dedupeLoadedMessages = (messages: Message[]) => {
    if (messages.length <= 1) return messages;

    const deduped: Message[] = [];
    const seenByRole = new Map<string, Set<string>>();
    const getSeenSet = (role: string) => {
      const key = role || "unknown";
      if (!seenByRole.has(key)) {
        seenByRole.set(key, new Set<string>());
      }
      return seenByRole.get(key)!;
    };

    for (const msg of messages) {
      const contentKey = (typeof msg.content === "string" ? msg.content : "").trim();
      const roleKey = msg.role || "unknown";
      const seenContents = getSeenSet(roleKey);

      // 用户多次发送相同文本属于正常行为，不能在加载时去重。
      if (roleKey === "user") {
        deduped.push(msg);
        continue;
      }

      // 仅在 assistant 消息中进行扩展去重逻辑，避免误伤 user 消息
      let cleanContent = contentKey;
      if (roleKey === "assistant" && contentKey.includes("Response:")) {
        cleanContent =
          contentKey.split("Response:").pop()?.trim() || contentKey;
      }

      // 检查是否已存在相同或相似的内容（assistant）
      // 检查完全匹配
      if (seenContents.has(contentKey)) {
        console.log(
          "[AgentChat] Duplicate message skipped (exact match):",
          contentKey.slice(0, 50),
        );
        continue;
      }

      if (roleKey === "assistant") {
        // 检查 Response 部分匹配
        if (seenContents.has(cleanContent)) {
          console.log(
            "[AgentChat] Duplicate message skipped (response match):",
            cleanContent.slice(0, 50),
          );
          continue;
        }

        // 检查包含关系：已存在的消息是否包含当前消息的 Response 部分
        let isDuplicate = false;
        for (const seen of seenContents) {
          if (seen.includes(cleanContent) || cleanContent.includes(seen)) {
            console.log(
              "[AgentChat] Duplicate message skipped (contains match):",
              cleanContent.slice(0, 50),
            );
            isDuplicate = true;
            break;
          }
        }
        if (isDuplicate) {
          continue;
        }
      }

      seenContents.add(contentKey);
      if (roleKey === "assistant") {
        seenContents.add(cleanContent); // 同时记录 Response 部分
      }
      deduped.push(msg);
    }

    return deduped;
  };

  const renameSession = async (sessionId: string, title: string) => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    if (!isAuthenticated) {
      renameLocalAgentSession(sessionId, trimmedTitle);
      refreshSessions();
      return;
    }
    try {
      await fetch(
        `${apiBaseUrl}/api/agent/history/sessions/${sessionId}/title`,
        {
          method: "PUT",
          headers: getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ title: trimmedTitle }),
        },
      );
      refreshSessions();
    } catch (error) {
      console.error("[AgentChat] Failed to rename session:", error);
    }
  };

  const loadSession = async (sessionId: string) => {
    if (isLoadingChat) {
      return;
    }
    if (sessionId === currentSessionId) {
      return;
    }
    setIsLoadingSession(true);
    // 先保存当前会话，确保未完成的内容被保存
    saveCurrentSession();
    await waitForPendingSave();

    // 确保切换会话前清除任何待保存标记，防止将新加载的消息误存回服务器
    pendingSaveRef.current = false;

    // 切换会话时先清理右侧和会话关联状态，避免旧会话数据串到新会话
    setSelectedResumeId(null);
    setAllowPdfAutoRender(false);
    setLoadedResumes([]);
    setSearchResults([]);
    setDiagnosisToolEvents([]);
    setStructuredEvents([]);
    setActiveSearchPanel(null);
    setResumePdfPreview({});
    restorePatches([]); // 清掉上一会话的 diff 卡，避免残留错挂

    try {
      let data: { messages?: any[]; total?: number } | null = null;
      if (!isAuthenticated) {
        const localSession = getLocalAgentSession(sessionId);
        if (!localSession) {
          if (!sessionId.startsWith("conv-")) {
            setResumeError("会话加载失败：未找到本地会话记录");
          }
          setCurrentSessionId(sessionId);
          setConversationId(sessionId);
          return;
        }
        data = {
          messages: localSession.messages,
          total: localSession.messages.length,
        };
      } else {
        const resp = await fetch(
          `${apiBaseUrl}/api/agent/history/sessions/${sessionId}`,
          {
            headers: getAuthHeaders(),
          },
        );

        if (!resp.ok) {
          let detail = `HTTP ${resp.status} ${resp.statusText}`;
          try {
            const errData = await resp.clone().json();
            if (errData?.detail?.message) {
              detail = errData.detail.message;
            } else if (typeof errData?.detail === "string") {
              detail = errData.detail;
            } else if (errData?.error_message) {
              detail = errData.error_message;
            }
          } catch {
            // ignore json parse errors
          }
          console.error(
            `[AgentChat] Failed to load session: ${detail}`,
          );
          // For brand-new local sessions (conv-*) that haven't been persisted yet,
          // a 404 is expected — don't show an error to the user.
          if (!(resp.status === 404 && sessionId.startsWith('conv-'))) {
            setResumeError(`会话加载失败：${detail}`);
          }
          // Mark sessionId as "seen" so the URL effect doesn't retry infinitely
          setCurrentSessionId(sessionId);
          // 如果加载失败，不清空当前消息，保持原状态
          return;
        }

        data = await resp.json();
      }
      setResumeError(null);

      // 检查返回的数据格式
      if (!data || !Array.isArray(data.messages)) {
        console.error("[AgentChat] Invalid session data format:", data);
        return;
      }

      // 过滤掉 tool 角色的消息（这些是内部消息，不应该显示给用户）
      const userVisibleMessages = (data.messages || []).filter(
        (m: any) => m.role === "user" || m.role === "assistant",
      );

      // 恢复会话级 UI 状态（包含右侧选中态）
      let savedMessageMetas: Record<string, MessageMeta> | null = null;
      let savedMessageProcessNodes: Record<string, AgentProcessNode[]> | null = null;
      let savedMessageTurnSnapshots: Record<string, ConversationTurnSnapshot> | null = null;
      try {
        const savedUiState = localStorage.getItem(`ui_state:${sessionId}`);
        if (savedUiState) {
          const {
            loadedResumes: sLrs,
            selectedResumeId: savedSelectedResumeId,
            diagnosisToolEvents: savedDiagnosisToolEvents,
            structuredEvents: savedStructuredEvents,
            messageMetas: sMetas,
            messageProcessNodes: sProcessNodes,
            messageTurnSnapshots: sTurnSnapshots,
            pendingPatches: sPatches,
          } = JSON.parse(savedUiState);
          // 清洗历史坏快照（与刷新恢复块同款）：agent 格式 resumeData 转 canonical
          const cleanedLrs = cleanLoadedResumesSnapshot(sLrs);
          if (Array.isArray(cleanedLrs) && cleanedLrs.length > 0) {
            setLoadedResumes(cleanedLrs);
          }
          if (Array.isArray(savedDiagnosisToolEvents)) {
            setDiagnosisToolEvents(savedDiagnosisToolEvents);
          }
          if (Array.isArray(savedStructuredEvents)) {
            setStructuredEvents(savedStructuredEvents);
          }
          if (sMetas && typeof sMetas === "object") {
            savedMessageMetas = sMetas;
          }
          if (sProcessNodes && typeof sProcessNodes === "object") {
            savedMessageProcessNodes = sProcessNodes;
          }
          if (sTurnSnapshots && typeof sTurnSnapshots === "object") {
            savedMessageTurnSnapshots =
              parseConversationTurnSnapshotMap(sTurnSnapshots);
          }
          // 恢复 diff 对比卡（含已应用/已拒绝终态），让历史会话能看到「改过什么」；
          // 同时把恢复的简历同步进 ResumeContext，pending 卡恢复后仍可正常「应用」
          if (Array.isArray(sPatches) && sPatches.length > 0) {
            restorePatches(sPatches);
            const sel =
              (Array.isArray(cleanedLrs) &&
                (cleanedLrs.find((r: any) => r.id === savedSelectedResumeId) ||
                  cleanedLrs[cleanedLrs.length - 1])) ||
              null;
            if (sel?.resumeData) setResume(sel.resumeData);
          }
          if (
            typeof savedSelectedResumeId === "string" &&
            savedSelectedResumeId.trim() !== ""
          ) {
            setSelectedResumeId(savedSelectedResumeId);
            setAllowPdfAutoRender(true);
          }
        }
      } catch (e) {
        console.warn("[AgentChat] Failed to restore session ui data:", e);
      }

      const loadedMessages: Message[] = userVisibleMessages.map(
        (m: any, index: number) => {
          const rawContent = m.content;
          const content =
            typeof rawContent === "string"
              ? rawContent
              : rawContent != null
              ? JSON.stringify(rawContent)
              : "";
          const id = stableMessageId(content, m.role || "unknown", index);
          return {
            id,
            role: m.role === "user" ? "user" : "assistant",
            content,
            thought: m.thought || undefined,
            timestamp: new Date().toISOString(),
            meta: savedMessageMetas?.[id],
            processNodes: savedMessageProcessNodes?.[id],
            turnSnapshot: savedMessageTurnSnapshots?.[id],
          };
        },
      );

      const dedupedMessages = dedupeLoadedMessages(loadedMessages);

      // 只有在成功加载到消息时才更新状态
      if (dedupedMessages.length > 0 || userVisibleMessages.length === 0) {
        setMessages(dedupedMessages);
        setCurrentSessionId(sessionId);
        setConversationId(sessionId);
        lastPersistedCountBySessionRef.current[sessionId] =
          typeof data?.total === "number"
            ? data.total
            : dedupedMessages.length;
        setAllowPdfAutoRender(false);
        // 清理流式状态，避免显示旧会话的流式内容
        finalizeStream();
      } else {
        console.warn(
          "[AgentChat] Loaded session has no valid messages, keeping current state",
        );
      }
    } catch (error) {
      console.error("[AgentChat] Failed to load session:", error);
      // 发生错误时，不清空当前消息，保持原状态
    } finally {
      setIsLoadingSession(false);
    }
  };

  const createNewSession = useCallback(async () => {
    isCreatingNewSessionRef.current = true;
    hasBootstrappedSessionRef.current = true;
    setInitialSessionResolved(true);

    // 先尽量保存当前会话，避免切换后丢失上下文
    saveCurrentSession();
    await waitForPendingSave();

    const canCreate = await checkCanCreateSession();
    if (!canCreate) {
      isCreatingNewSessionRef.current = false;
      return;
    }

    // 确保切换会话前清除任何待保存标记
    pendingSaveRef.current = false;

    const newId = `conv-${Date.now()}`;
    console.log("[AgentChat] Creating new session:", newId);
    setMessages([]);
    setCurrentSessionId(newId);
    setConversationId(newId);
    lastPersistedCountBySessionRef.current[newId] = 0;
    lastSavedKeyRef.current = "";
    setSelectedResumeId(null);
    setAllowPdfAutoRender(false);
    setLoadedResumes([]);
    setDiagnosisToolEvents([]);
    setStructuredEvents([]);
    setSearchResults([]);
    setResumeEditDiffs([]);
    setActiveSearchPanel(null);
    setResumePdfPreview({});
    finalizeStream();

    navigate("/agent/new", { replace: true });

    window.setTimeout(() => {
      isCreatingNewSessionRef.current = false;
    }, 0);

    // 不再立即持久化空会话，只在用户发送第一条消息时才真正创建并入库
    // 这样可以避免用户点击+按钮后没有输入消息就产生空会话
  }, [
    checkCanCreateSession,
    finalizeStream,
    saveCurrentSession,
    waitForPendingSave,
    navigate,
  ]);

  const handleSelectSession = useCallback(
    (sessionId: string) => {
      if (!sessionId) {
        void createNewSession();
        return;
      }
      navigate(`/agent/new?sessionId=${sessionId}`, { replace: true });
    },
    [createNewSession, navigate],
  );

  const handleCreateSession = useCallback(() => {
    void createNewSession();
  }, [createNewSession]);

  // 监听 forceNew state（侧边栏"+"在已处于 /agent/new 时触发）
  const prevForceNewRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    const forceNew = (location.state as { forceNew?: number } | null)?.forceNew;
    if (forceNew && forceNew !== prevForceNewRef.current) {
      prevForceNewRef.current = forceNew;
      void createNewSession();
    }
  }, [location.state, createNewSession]);

  // 监听 URL sessionId 变化并同步会话：
  // - 有 sessionId: 加载该历史会话
  // - 从有 sessionId 切换到无 sessionId（点击左侧 +）: 创建新会话
  useEffect(() => {
    const routeSessionId =
      new URLSearchParams(location.search).get("sessionId")?.trim() || null;
    const previousRouteSessionId = prevRouteSessionIdRef.current;
    prevRouteSessionIdRef.current = routeSessionId;

    if (routeSessionId) {
      if (routeSessionId === currentSessionId) return;
      if (isLoadingSession) return;
      if (isCreatingNewSessionRef.current) return;
      void loadSession(routeSessionId);
      return;
    }

    if (isCreatingNewSessionRef.current) {
      return;
    }

    // 从历史会话 URL 切回 /agent/new（无 sessionId）时，主动创建空白新会话
    if (!isLoadingSession) {
      if (
        previousRouteSessionId ||
        (currentSessionId && !currentSessionId.startsWith("conv-"))
      ) {
        void createNewSession();
      }
    }
  }, [
    location.search,
    currentSessionId,
    isLoadingSession,
    loadSession,
    createNewSession,
  ]);

  const applyResumeToChat = useCallback(
    async (selectedResume: SavedResume, messageId?: string) => {
      const resolvedUserId =
        user?.id ?? (selectedResume as any).user_id ?? null;
      const rawData = (selectedResume.data || {}) as Record<string, unknown>;
      const normalizedBase = isWorkspaceResumeData(rawData)
        ? (rawData as ResumeData)
        : normalizeImportedResumeToCanonical(rawData as Record<string, any>, {
            resumeId: selectedResume.id,
            title: selectedResume.name,
          });
      const resumeDataWithMeta = {
        ...normalizedBase,
        resume_id: selectedResume.id,
        user_id: resolvedUserId,
        alias: selectedResume.alias,
        _meta: {
          resume_id: selectedResume.id,
          user_id: resolvedUserId,
        },
      } as unknown as ResumeData;

      resumeDataRef.current = resumeDataWithMeta;
      setResumeData(resumeDataWithMeta);

      const linkedMessageId = messageId ?? `resume-select-${Date.now()}`;
      setLoadedResumes((prev) => {
        const nextEntry = {
          id: selectedResume.id,
          name: selectedResume.name,
          messageId: linkedMessageId,
          resumeData: resumeDataWithMeta,
        };
        const filtered = prev.filter((item) => item.id !== selectedResume.id);
        return [...filtered, nextEntry];
      });

      setAllowPdfAutoRender(true);
      setSelectedResumeId(selectedResume.id);
      setShowResumeSelector(false);

      // 应用新简历数据后强制重渲 PDF 预览：
      // 粘贴导入 / AI 编辑常是「更新现有简历（同 id）」，selectedResumeId 不变、旧 blob 有缓存，
      // 不 force 的话 renderResumePdfPreview 会命中「already has blob」跳过，导致解析完右侧不刷新（要手动点刷新）。
      void renderResumePdfPreview(
        { id: selectedResume.id, resumeData: resumeDataWithMeta },
        true,
      );

      console.log(
        "[AgentChat] 简历已加载到对话区:",
        selectedResume.id,
        selectedResume.name,
      );
    },
    [user?.id, renderResumePdfPreview],
  );

  // generate_resume 生成的简历：自动落地到右侧预览（生成即所见，复用导入链路）
  useEffect(() => {
    const generated = generatedResume?.resume;
    if (!generated) return;
    void (async () => {
      try {
        const resumeId = `resume_latex_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
        const displayName = resolveImportedResumeDisplayName(
          generated as unknown as Record<string, unknown>,
        );
        const normalized = normalizeImportedResumeToCanonical(
          generated as unknown as Record<string, any>,
          { resumeId, title: `${displayName}的简历` },
        );
        const saved = await saveResume(normalized, resumeId);
        setCurrentResumeId(saved.id);
        await applyResumeToChat(saved);
      } catch (e) {
        console.error("[AgentChat] 生成简历落地预览失败:", e);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generatedResume]);

  // 处理简历选择
  // 从编辑页带 resumeId 跳来时的选择：继续编辑这份 / 开启新会话
  const handleContinueEditCarry = useCallback(() => {
    if (carryResumePrompt) {
      void applyResumeToChat(carryResumePrompt);
      // 加一条引导消息进入对话态，避免继续停在空态卡片
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          role: "assistant",
          content: `已加载「${carryResumePrompt.name || "你的简历"}」，右侧可以看到。建议先一键优化整份，或点下方直接开始 👇`,
          timestamp: new Date().toISOString(),
          // 主动给一个主动作（首个为主 CTA），而不是让用户做「想优化哪部分」的选择题
          meta: { suggestions: ["优化整份简历", "帮我体检一下简历", "只优化某一段"] },
        },
      ]);
    }
    setCarryResumePrompt(null);
  }, [carryResumePrompt, applyResumeToChat]);

  const handleStartNewFromCarry = useCallback(() => {
    setCarryResumePrompt(null);
    navigate("/agent/new");
  }, [navigate]);

  // handleResumeSelect 定义在 sendUserTextMessage 之后（依赖它，提前引用会 TDZ），
  // 见下方「选择简历对话化」实现。

  // 取消简历选择
  const handleResumeSelectorCancel = useCallback(() => {
    setShowResumeSelector(false);
    setPendingResumeInput("");
  }, []);

  const handleImportResume = useCallback(() => {
    setShowResumeSelector(false);
    setPendingResumeInput("");
    setAiImportModalOpen(true);
  }, []);

  const handleAIImportSave = useCallback(
    async (data: Record<string, unknown>) => {
      setAiImportModalOpen(false);
      setShowResumeSelector(false);
      setPendingResumeInput("");
      try {
        const resumeId = `resume_latex_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
        const displayName = resolveImportedResumeDisplayName(data);
        const normalized = normalizeImportedResumeToCanonical(data, {
          resumeId,
          title: `${displayName}的简历`,
        });
        const saved = await saveResume(normalized, resumeId);
        setCurrentResumeId(saved.id);
        await applyResumeToChat(saved);

        const assistantMsg: Message = {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          role: "assistant",
          content: `已通过 AI 智能导入简历「${saved.name}」，右侧可预览。你可以继续告诉我需要优化哪些内容。`,
          timestamp: new Date().toISOString(),
          meta: {
            importSuccess: {
              name: saved.name,
              suggestions: IMPORT_NEXT_STEP_SUGGESTIONS,
            },
          },
        };
        setMessages((prev) => {
          const updated = [...prev, assistantMsg];
          const validConversationId =
            conversationId?.trim() || currentSessionId || `conv-${Date.now()}`;
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
        setResumeError(null);
      } catch (error) {
        console.error("[AgentChat] AI 导入简历失败:", error);
        setResumeError("AI 导入简历失败，请稍后重试。");
      }
    },
    [
      applyResumeToChat,
      conversationId,
      currentSessionId,
      persistSessionSnapshot,
    ],
  );

  // 导入失败重试：按失败消息 id 存重发闭包（图片/文件路径），点「重试」重发同一份文件
  const importRetryMapRef = useRef<Map<string, () => void>>(new Map());
  const handleImportRetry = useCallback((msgId: string) => {
    const retry = importRetryMapRef.current.get(msgId);
    if (retry) {
      importRetryMapRef.current.delete(msgId);
      retry();
    }
  }, []);

  const importPastedResumeInChat = useCallback(
    async (
      userMessage: string,
      resumeText: string,
      userMessageId: string,
      nextMessages: Message[],
      isFirstMessage: boolean,
      validConversationId: string,
    ) => {
      const parsingMsgId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const parseStartedAt = Date.now();
      const parsingAssistantMsg: Message = {
        id: parsingMsgId,
        role: "assistant",
        content: "正在 AI 解析简历内容、请稍候（长文本可能需要几十秒）…",
        timestamp: new Date().toISOString(),
        meta: {
          pasteImportParsing: true,
          parseStartedAt,
        },
      };
      const messagesWithParsing = [...nextMessages, parsingAssistantMsg];
      setMessages(messagesWithParsing);
      await persistSessionSnapshot(
        validConversationId,
        messagesWithParsing,
        isFirstMessage,
      );

      setIsPasteImporting(true);
      setResumeError(null);
      try {
        const parsed = await parseResumeText(apiBaseUrl, resumeText);
        const displayName = resolveImportedResumeDisplayName(parsed);

        const existingResumeId =
          resumeDataRef.current?.id ||
          selectedResumeId ||
          loadedResumes[loadedResumes.length - 1]?.id ||
          null;
        const canUpdateExisting =
          !!existingResumeId &&
          !String(existingResumeId).startsWith("uploaded-pdf-");

        const targetResumeId =
          canUpdateExisting && existingResumeId
            ? String(existingResumeId)
            : `resume_latex_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;

        const normalized = normalizeImportedResumeToCanonical(parsed, {
          resumeId: targetResumeId,
          title: `${displayName}的简历`,
        });
        const saved = await saveResume(normalized, targetResumeId);
        setCurrentResumeId(saved.id);
        await applyResumeToChat(saved, userMessageId);

        const successContent = canUpdateExisting
          ? `已将粘贴内容解析并写入当前简历「${saved.name}」，右侧可预览。如需继续优化某段经历，直接告诉我即可。`
          : `已通过 AI 解析导入简历「${saved.name}」，右侧可预览。你可以继续告诉我需要优化哪些内容。`;

        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: successContent,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importSuccess: {
                      name: saved.name,
                      suggestions: IMPORT_NEXT_STEP_SUGGESTIONS,
                    },
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } catch (error) {
        console.error("[AgentChat] 对话粘贴导入失败:", error);
        const errText =
          error instanceof Error ? error.message : "简历解析失败，请稍后重试。";
        setResumeError(errText);
        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: `简历解析失败：${errText}。你也可以点击「展示简历」→「导入简历」重试。`,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } finally {
        setIsPasteImporting(false);
      }
    },
    [
      apiBaseUrl,
      applyResumeToChat,
      loadedResumes,
      persistSessionSnapshot,
      selectedResumeId,
    ],
  );

  // 图片简历导入：镜像粘贴文本导入链路——先进入对话并显示解析动画，
  // 走视觉识别接口解析后落地渲染右侧预览，全程不发给 Agent、不做诊断分析。
  const importResumeImagesInChat = useCallback(
    async (userMessage: string, imageFiles: File[]) => {
      const picked = imageFiles.slice(0, 2);
      const skipped = imageFiles.length - picked.length;

      // 用户消息（带图片缩略图），立即进入对话视图
      const uniqueId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const attachmentMeta = picked.map((file) => ({
        name: file.name,
        type: file.type,
        size: file.size,
        url: URL.createObjectURL(file),
      }));
      const userMessageEntry: Message = {
        id: uniqueId,
        role: "user",
        content: userMessage.trim() || "解析这份简历图片",
        timestamp: new Date().toISOString(),
        attachments: attachmentMeta,
      };
      const nextMessages = [...messages, userMessageEntry];
      const isFirstMessage = messages.length === 0;
      setMessages(nextMessages);

      let validConversationId = conversationId;
      if (!validConversationId || validConversationId.trim() === "") {
        validConversationId = `conv-${Date.now()}`;
        setConversationId(validConversationId);
      }
      if (!currentSessionId) {
        setCurrentSessionId(validConversationId);
      }
      if (isFirstMessage) {
        await persistSessionSnapshot(validConversationId, nextMessages, true);
      }

      // 解析动画消息
      const parsingMsgId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const parseStartedAt = Date.now();
      const parsingAssistantMsg: Message = {
        id: parsingMsgId,
        role: "assistant",
        content: "正在识别图片中的简历内容、请稍候（约十几秒）…",
        timestamp: new Date().toISOString(),
        meta: { pasteImportParsing: true, parseStartedAt },
      };
      const messagesWithParsing = [...nextMessages, parsingAssistantMsg];
      setMessages(messagesWithParsing);
      await persistSessionSnapshot(
        validConversationId,
        messagesWithParsing,
        isFirstMessage,
      );

      setIsPasteImporting(true);
      setResumeError(null);

      // 右侧预览进入识别态
      const resumeEntryId = `resume_latex_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
      updateResumePdfState(resumeEntryId, {
        loading: true,
        progress: "正在识别图片中的简历内容...",
        error: null,
      });
      setAllowPdfAutoRender(true);
      setSelectedResumeId(resumeEntryId);

      try {
        const formData = new FormData();
        picked.forEach((file) => formData.append("files", file));
        formData.append("model", "glm-ocr");

        const parsedResume = await uploadResumeImageStream({
          apiBaseUrl,
          formData,
          onStatus: (statusText) => {
            updateResumePdfState(resumeEntryId, {
              loading: true,
              progress: statusText,
              error: null,
            });
          },
        });

        const displayName = resolveImportedResumeDisplayName(parsedResume);
        const canonical = normalizeImportedResumeToCanonical(parsedResume, {
          resumeId: resumeEntryId,
          title: `${displayName}的简历`,
        });
        const saved = await saveResume(canonical, resumeEntryId);
        setCurrentResumeId(saved.id);
        await applyResumeToChat(saved, uniqueId);

        const successContent =
          `已识别并导入简历「${saved.name}」，右侧可预览。你可以继续告诉我要优化哪些内容。` +
          (skipped > 0
            ? `（一次最多解析 2 张，已忽略多余 ${skipped} 张）`
            : "");
        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: successContent,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importSuccess: {
                      name: saved.name,
                      suggestions: IMPORT_NEXT_STEP_SUGGESTIONS,
                    },
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } catch (error) {
        console.error("[AgentChat] 图片简历识别失败:", error);
        const errText =
          error instanceof Error ? error.message : "图片识别失败，请稍后重试。";
        setResumeError(errText);
        updateResumePdfState(resumeEntryId, {
          loading: false,
          progress: "",
          error: errText,
        });
        // 存重试闭包：重发同一批图片，失败不静默、一键可重试
        importRetryMapRef.current.set(parsingMsgId, () => {
          void importResumeImagesInChat(userMessage, picked);
        });
        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: `图片识别失败：${errText}`,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importRetry: true,
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } finally {
        setIsPasteImporting(false);
      }
    },
    [
      apiBaseUrl,
      messages,
      conversationId,
      currentSessionId,
      persistSessionSnapshot,
      applyResumeToChat,
      updateResumePdfState,
      setAllowPdfAutoRender,
      setSelectedResumeId,
    ],
  );

  // 纯解析导入简历文件（PDF 走 /api/resume/upload-pdf，图片委托图片链路）——只解析入库并加载到会话，
  // 全程不发给 Agent、不做优化分析。给「按 JD 优化简历」卡的第一步用。
  const importResumeFileInChat = useCallback(
    async (file: File) => {
      if (file.type.startsWith("image/")) {
        await importResumeImagesInChat("解析这份简历", [file]);
        return;
      }
      const uniqueId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const userMessageEntry: Message = {
        id: uniqueId,
        role: "user",
        content: "解析这份简历",
        timestamp: new Date().toISOString(),
        attachments: [{ name: file.name, type: file.type, size: file.size }],
      };
      const nextMessages = [...messages, userMessageEntry];
      const isFirstMessage = messages.length === 0;
      setMessages(nextMessages);

      let validConversationId = conversationId;
      if (!validConversationId || validConversationId.trim() === "") {
        validConversationId = `conv-${Date.now()}`;
        setConversationId(validConversationId);
      }
      if (!currentSessionId) setCurrentSessionId(validConversationId);

      const parsingMsgId = `${Date.now()}-p`;
      const parseStartedAt = Date.now();
      const parsingMsg: Message = {
        id: parsingMsgId,
        role: "assistant",
        content: "正在解析简历文件、请稍候…",
        timestamp: new Date().toISOString(),
        meta: { pasteImportParsing: true, parseStartedAt },
      };
      const withParsing = [...nextMessages, parsingMsg];
      setMessages(withParsing);
      await persistSessionSnapshot(validConversationId, withParsing, isFirstMessage);

      setIsPasteImporting(true);
      setResumeError(null);
      const resumeEntryId = `resume_file_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      updateResumePdfState(resumeEntryId, {
        loading: true,
        progress: "正在解析简历内容...",
        error: null,
      });
      setAllowPdfAutoRender(true);
      setSelectedResumeId(resumeEntryId);

      try {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetch(`${apiBaseUrl}/api/resume/upload-pdf`, {
          method: "POST",
          body: formData,
        });
        if (!response.ok) {
          const errBody = await response.json().catch(() => null);
          const detail =
            errBody && typeof errBody.detail === "string"
              ? errBody.detail
              : `简历解析失败（${response.status}）`;
          throw new Error(detail);
        }
        const data = await response.json();
        const parsedResume = data?.resume;
        if (!parsedResume || typeof parsedResume !== "object") {
          throw new Error("未解析出结构化简历内容，请换 PDF 或改用「粘贴简历文本」。");
        }
        const displayName = resolveImportedResumeDisplayName(parsedResume);
        const canonical = normalizeImportedResumeToCanonical(parsedResume, {
          resumeId: resumeEntryId,
          title: `${displayName}的简历`,
        });
        const saved = await saveResume(canonical, resumeEntryId);
        setCurrentResumeId(saved.id);
        await applyResumeToChat(saved, uniqueId);
        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: `已解析导入简历「${saved.name}」，右侧可预览。`,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importSuccess: {
                      name: saved.name,
                      suggestions: IMPORT_NEXT_STEP_SUGGESTIONS,
                    },
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } catch (error) {
        console.error("[AgentChat] 简历文件解析失败:", error);
        const errText =
          error instanceof Error ? error.message : "简历解析失败，请稍后重试。";
        setResumeError(errText);
        updateResumePdfState(resumeEntryId, { loading: false, progress: "", error: errText });
        // 存重试闭包：重发同一份文件，失败不静默、一键可重试
        importRetryMapRef.current.set(parsingMsgId, () => {
          void importResumeFileInChat(file);
        });
        setMessages((prev) => {
          const updated = prev.map((msg) =>
            msg.id === parsingMsgId
              ? {
                  ...msg,
                  content: `简历解析失败：${errText}`,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importRetry: true,
                  },
                }
              : msg,
          );
          void persistSessionSnapshot(validConversationId, updated, false);
          return updated;
        });
      } finally {
        setIsPasteImporting(false);
      }
    },
    [
      apiBaseUrl,
      messages,
      conversationId,
      currentSessionId,
      persistSessionSnapshot,
      applyResumeToChat,
      updateResumePdfState,
      setAllowPdfAutoRender,
      setSelectedResumeId,
      importResumeImagesInChat,
    ],
  );

  const handleCreateResume = useCallback(() => {
    setShowResumeSelector(false);
    setPendingResumeInput("");
    const assistantMsg: Message = {
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      role: "assistant",
      content: CREATE_RESUME_GUIDE_TEXT,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => {
      const updated = [...prev, assistantMsg];
      const validConversationId =
        conversationId?.trim() || currentSessionId || `conv-${Date.now()}`;
      void persistSessionSnapshot(validConversationId, updated, prev.length === 0);
      return updated;
    });
    setResumeError(null);
  }, [conversationId, currentSessionId, persistSessionSnapshot]);

  const sendUserTextMessage = useCallback(
    async (
      userMessage: string,
      attachments?: File[],
      resumeDataOverride?: ResumeData | null,
      bypassProcessingGuard?: boolean,
      // 静默用户气泡:replay 重发(选简历后带简历重跑原请求)是技术动作,
      // 用户只说过一次话,时间线不该出现第二个一模一样的气泡
      // (2026-07-13 实测截图追踪问题 2)
      silentUserBubble?: boolean,
    ) => {
      if (
        (!userMessage.trim() && (!attachments || attachments.length === 0)) ||
        (!bypassProcessingGuard && (isProcessing || isPasteImporting))
      )
        return;

      // 真实用户主动发的一轮：清掉上一次整份优化任务遗留的自动续跑状态。
      // 独立review发现：不清会导致 (a) 防御性计数跨任务累加，同一个标签页
      // 里第2、3个整份优化任务提前撞上前端防御性上限，被早已收尾的旧任务
      // "borrow"掉续跑额度；(b) 某次 auto_continue 因命中 finalizeMessage
      // 的空内容分支而没被消费，错误地黏到下一条不相关的用户消息后触发。
      // 放在函数最前面、早于所有分支 return，覆盖粘贴导入/创建简历等
      // 不经过 agent stream 的分支。
      pendingAutoContinueRef.current = null;
      autoContinueFiredCountRef.current = 0;

      const trimmedMessage = userMessage.trim();
      const pasteResumeText =
        !attachments || attachments.length === 0
          ? extractPasteImportResumeText(trimmedMessage)
          : null;

      // 粘贴导入优先于 Agent：走 /api/resume/parse 全量结构化
      if (pasteResumeText) {
        const uniqueId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        const userMessageEntry: Message = {
          id: uniqueId,
          role: "user",
          content: userMessage,
          timestamp: new Date().toISOString(),
        };
        const nextMessages = [...messages, userMessageEntry];
        const isFirstMessage = messages.length === 0;
        setMessages(nextMessages);

        let validConversationId = conversationId;
        if (!validConversationId || validConversationId.trim() === "") {
          validConversationId = `conv-${Date.now()}`;
          setConversationId(validConversationId);
        }
        if (!currentSessionId) {
          setCurrentSessionId(validConversationId);
        }
        if (isFirstMessage) {
          await persistSessionSnapshot(
            validConversationId,
            nextMessages,
            true,
          );
        }

        await importPastedResumeInChat(
          userMessage,
          pasteResumeText,
          uniqueId,
          nextMessages,
          isFirstMessage,
          validConversationId,
        );
        return;
      }

      // 发送普通消息时关闭选择器，避免与流式回复叠在一起并反复触发滚动
      if (!isSelectExistingResumeIntentText(trimmedMessage)) {
        setShowResumeSelector(false);
      }

      // 独立review发现的真实bug：这条固定模板回复只按文本正则触发，从不检查
      // 简历面板里是不是已经有简历——用户已经加载/上传过简历，再说一句带
      // "创建/生成简历"字样的话（哪怕本意是别的），也会被这里硬生生打断成
      // 一段罐头文案，完全绕过了后端 manus.py 里本来就有的、真正会检查
      // "当前 context 中还没有简历内容"这个条件的 agent 推理。加一道同款的
      // "面板里已有简历"判断——已经有简历就不走这条快捷方式，让消息正常
      // 发给 agent，由它自己根据真实状态判断怎么回（用户明确要的效果）。
      const hasResumeContextForCreateIntent =
        !!resumeDataRef.current ||
        loadedResumes.some((item) => !!item.resumeData);
      if (
        isCreateResumeIntentText(trimmedMessage) &&
        (!attachments || attachments.length === 0) &&
        !hasResumeContextForCreateIntent
      ) {
        const uniqueId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        const userMessageEntry: Message = {
          id: uniqueId,
          role: "user",
          content: userMessage,
          timestamp: new Date().toISOString(),
        };
        const nextMessages = [...messages, userMessageEntry];
        const isFirstMessage = messages.length === 0;
        setMessages(nextMessages);

        let validConversationId = conversationId;
        if (!validConversationId || validConversationId.trim() === "") {
          validConversationId = `conv-${Date.now()}`;
          setConversationId(validConversationId);
        }
        if (!currentSessionId) {
          setCurrentSessionId(validConversationId);
        }
        const assistantMsg: Message = {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          role: "assistant",
          content: CREATE_RESUME_GUIDE_TEXT,
          timestamp: new Date().toISOString(),
        };
        const finalMessages = [...nextMessages, assistantMsg];
        setMessages(finalMessages);
        await persistSessionSnapshot(
          validConversationId,
          finalMessages,
          isFirstMessage,
        );
        setResumeError(null);
        return;
      }

      const hasResumeContext =
        !!resumeDataRef.current ||
        loadedResumes.some((item) => !!item.resumeData);

      const uniqueId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      currentRunUserInputRef.current = userMessage.trim();
      hasPatchInCurrentStreamRef.current = false;
      pendingSelectorOpenRef.current = false;
      // 新一轮消息开始：把上一轮未处理的 pending patch 标记为 superseded
      supersedePendingPatches();
      setSearchResults((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setLoadedResumes((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setResumeEditDiffs((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setDiagnosisToolEvents((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setStructuredEvents((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );

      // 处理附件元数据
      const attachmentMeta = attachments?.map((file) => ({
        name: file.name,
        type: file.type,
        size: file.size,
      }));

      const userMessageEntry: Message = {
        id: uniqueId,
        role: "user",
        content: userMessage,
        timestamp: new Date().toISOString(),
        attachments: attachmentMeta,
      };
      const nextMessages = silentUserBubble
        ? [...messages]
        : [...messages, userMessageEntry];
      const isFirstMessage = messages.length === 0;

      if (!silentUserBubble) {
        setMessages(nextMessages);
      }
      if (isFirstMessage) {
        // 保持当前会话，不创建新的 conversationId
        // 只有当确实没有 conversationId 时才创建新的
        let validConversationId = conversationId;
        if (!validConversationId || validConversationId.trim() === "") {
          validConversationId = `conv-${Date.now()}`;
          setConversationId(validConversationId);
        }
        if (!currentSessionId) {
          setCurrentSessionId(validConversationId);
        }
        // 持久化并刷新会话列表（确保新会话在侧边栏显示）
        // 只有在发送第一条消息时才设置 shouldRefresh 为 true，从而触发侧边栏更新
        await persistSessionSnapshot(validConversationId, nextMessages, true);
      }

      isFinalizedRef.current = false;
      pendingFinalizeAfterTypewriterRef.current = false;
      const nextRunId = startNewRun();
      setActiveRunId(nextRunId);
      lastDoneRunRef.current = -1;
      currentProcessNodesRef.current = [];
      // Pre-generate a message ID for this run so resume patches can reference it
      currentAssistantMessageIdRef.current = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      setSearchResults((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setLoadedResumes((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setResumeEditDiffs((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );
      setStructuredEvents((prev) =>
        prev.filter((item) => item.messageId !== "current"),
      );

      const effectiveResumeData =
        resumeDataOverride !== undefined
          ? resumeDataOverride
          : resumeDataRef.current;
      await sendMessage(userMessage, effectiveResumeData);
    },
    [
      isProcessing,
      messages,
      conversationId,
      currentSessionId,
      persistSessionSnapshot,
      sendMessage,
      loadedResumes,
      importPastedResumeInChat,
      isPasteImporting,
    ],
  );

  // Asking 模式提交：把用户逐项选择的结果拼成结构化文本，作为下一轮 prompt 发出去。
  // agent 在新一轮里读到答案 + ResumeDataStore 里 progress 仍保留该模块 pending，
  // 用答案改写模块或判定 skip，整份优化接着推进。必须放在 sendUserTextMessage
  // 定义之后（依赖它），和上面 heroInput 首条消息同一处理由。
  const handleAskQuestionSubmit = useCallback(
    (answers: AskQuestionAnswer[]) => {
      if (askQuestionSubmitted) return;
      setAskQuestionSubmitted(true);
      // 点击即对话 P2：气泡文案说人话（第一人称短句），LLM 同样读得懂；
      // 原 `[选择框确认的信息]` 技术标记经核无任何前后端依赖，安全移除。
      const lines = answers.map((a) => {
        if (a.choice === "skip") return `${a.header} 跳过`;
        return `${a.header} ${a.value || "(空)"}`;
      });
      const message = `我确认这些信息：${lines.join("；")}`;
      // bypassProcessingGuard=true：选择框提交是"回复 agent 的提问"，此时
      // isProcessing 可能还是 true（后端 FINISHED 但前端 SSE 收尾状态更新有
      // 延迟），走正常 guard 会被挡住静默 return——用户实测"提交无反应"。
      void sendUserTextMessage(message, undefined, undefined, true);
    },
    [askQuestionSubmitted, sendUserTextMessage],
  );

  // 选择简历对话化（2026-07-15 设计）：点选简历是用户的一次输出，以用户
  // 气泡进入对话并触发 Agent 真实回应一轮，而非一条居中 assistant 回执。
  // 必须定义在 sendUserTextMessage 之后（依赖它，提前引用会 TDZ）。
  const handleResumeSelect = useCallback(
    async (selectedResume: SavedResume) => {
      // 注意不要在这里掐断进行中的流(此前 isProcessing 时调 finalizeStream,
      // 会把尚未 finalize 的 AI 引导文案直接清空,历史上表现为"选完简历上一轮
      // 消息消失")。暂存输入的重发由 replay effect 负责,其自带等流结束的守卫。
      await applyResumeToChat(selectedResume);
      const selectionText = `我选择了「${selectedResume.name || "这份简历"}」这份简历`;
      if (pendingResumeInput.trim()) {
        // 用户带着意图来（如先说"帮我优化简历"再选）：replay effect 会静默
        // 重发原意图，已构成本次选择后的真实一轮——这里只补用户气泡记录
        // 选择动作，不再另发一轮，避免双轮。
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-resume-selected`,
            role: "user",
            content: selectionText,
            timestamp: new Date().toISOString(),
          },
        ]);
        return;
      }
      // 直接点选（无暂存意图）：选择本身走完整一轮（用户气泡 + Agent 确认
      // 与下一步引导）。简历数据已由 applyResumeToChat 同步写入
      // resumeDataRef，随请求自动带上。bypassProcessingGuard 理由同上方
      // AskQuestion 提交：面板动作可能撞上上一轮 SSE 收尾的尾态。
      void sendUserTextMessage(selectionText, undefined, undefined, true);
    },
    [applyResumeToChat, pendingResumeInput, sendUserTextMessage],
  );

  // 首页 hero 输入框带来的第一条消息：会话就绪后自动发出一次。
  // 复用 sendUserTextMessage（其内部会自动识别粘贴的简历文本并走解析），不新建平行链路。
  // 必须放在 sendUserTextMessage 定义之后，否则依赖数组会在 TDZ 中访问它而报错。
  // 优化对比卡收尾：本批全部处理完（无 pending）且至少应用了一处 → 插入收尾卡（下载 PDF / 去编辑器）
  const prevPendingCountRef = useRef(0);
  // 已经记录进气泡的 patch_id：用来算「本批新处理」的 patch，避免气泡数字
  // 用全会话累计（原来第二批点 1 处会显示「4 处」）+ 让气泡只描述本批改动。
  const recordedPatchIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const pendingCount = pendingPatches.filter((p) => p.status === "pending").length;
    const newlyApplied = pendingPatches.filter(
      (p) => p.status === "applied" && !recordedPatchIdsRef.current.has(p.patch_id),
    );
    const newlyRejected = pendingPatches.filter(
      (p) => p.status === "rejected" && !recordedPatchIdsRef.current.has(p.patch_id),
    );
    // 点击即对话（specs/2026-07-15-点击即对话-统一交互原则 P1）：全部拒绝
    // 也是用户完成的一个决定，留一条气泡记录（不发轮、不出收尾卡）。
    if (
      prevPendingCountRef.current > 0 &&
      pendingCount === 0 &&
      newlyApplied.length === 0 &&
      newlyRejected.length > 0
    ) {
      const rejectedCount = newlyRejected.length;
      newlyRejected.forEach((p) => recordedPatchIdsRef.current.add(p.patch_id));
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-patches-rejected`,
          role: "user",
          content: buildRejectDecisionCopy(rejectedCount),
          timestamp: new Date().toISOString(),
        },
      ]);
    }
    if (prevPendingCountRef.current > 0 && pendingCount === 0 && newlyApplied.length > 0) {
      const appliedCount = newlyApplied.length;
      const rejectedCount = newlyRejected.length;
      const appliedSummaries = newlyApplied.map((p) => p.summary);
      [...newlyApplied, ...newlyRejected].forEach((p) =>
        recordedPatchIdsRef.current.add(p.patch_id),
      );
      // 点击即对话 P1：应用（含「全部应用」）是用户的决定，先落一条用户
      // 气泡（复用 summary 说清具体改了什么），下面的收尾卡与 LLM 静默收尾
      // 轮自然成为对它的回应。
      const decisionMsg: Message = {
        id: `${Date.now()}-patches-applied`,
        role: "user",
        content: buildApplyDecisionCopy(appliedSummaries, rejectedCount),
        timestamp: new Date().toISOString(),
      };
      // 瘦身版收尾卡:只留功能入口(下载/再优化/精修),"说什么"交给下面的 LLM 收尾轮
      const doneMsg: Message = {
        id: `${Date.now()}-apply-done`,
        role: "assistant",
        content: `已应用 ${appliedCount} 处优化，右侧预览已更新。`,
        timestamp: new Date().toISOString(),
        meta: { applyDone: { count: appliedCount } },
      };
      setMessages((prev) => {
        const updated = [...prev, decisionMsg, doneMsg];
        const sid = conversationId?.trim() || currentSessionId;
        if (sid) void persistSessionSnapshot(sid, updated, false);
        return updated;
      });
      // 静默触发一条 Agent 轮(不渲染用户气泡):让 Coco 基于本轮真实 diff
      // 说收尾话 + 给贴合改动的动态建议,替代原先写死的三个打磨 chip
      if (!isProcessing) {
        // 静默轮同样必须走完整的新轮初始化:此前裸调 sendMessage 导致
        // streamRunRef 不推进,finalizeMessage 的同 run 判重把收尾轮的
        // finalize 直接吞掉,总结正文永远落不进时间线(2026-07-10 实测)。
        isFinalizedRef.current = false;
        pendingFinalizeAfterTypewriterRef.current = false;
        const nextRunId = startNewRun();
        setActiveRunId(nextRunId);
        lastDoneRunRef.current = -1;
        currentProcessNodesRef.current = [];
        currentRunUserInputRef.current = "";
        hasPatchInCurrentStreamRef.current = false;
        currentAssistantMessageIdRef.current = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        setSearchResults((prev) => prev.filter((item) => item.messageId !== "current"));
        setLoadedResumes((prev) => prev.filter((item) => item.messageId !== "current"));
        setResumeEditDiffs((prev) => prev.filter((item) => item.messageId !== "current"));
        setDiagnosisToolEvents((prev) => prev.filter((item) => item.messageId !== "current"));
        setStructuredEvents((prev) => prev.filter((item) => item.messageId !== "current"));
        void sendMessage(
          `[系统内部提示,不要向用户复述本条] 用户刚刚应用了 ${appliedCount} 处简历修改：${appliedSummaries.join("；")}。` +
            "你的回复必须以「Response: 」开头,包含两部分,顺序固定:" +
            "第一部分(必须有,禁止为空,禁止只输出建议标记):用 1-2 句自然的话告诉用户这次实际改好了什么" +
            "(基于会话里真实发生的修改点名具体段落,例如「美团那段的量化数据补上了,项目描述也更突出成果了」,不要泛泛而谈);" +
            '第二部分:另起一行,基于刚才改动给 1-3 条贴合的下一步建议按钮,格式:%%SUGGESTIONS%%[{"text":"按钮文字","msg":"点击后发送的话"}]%%END%%。' +
            "不要调用任何工具。",
          resumeDataRef.current,
        );
      }
    }
    prevPendingCountRef.current = pendingCount;
    // startNewRun/setter 均只操作 ref 或为稳定引用,不列入 deps 避免每渲染重跑
  }, [pendingPatches, conversationId, currentSessionId, persistSessionSnapshot, isProcessing, sendMessage]);

  // 整份优化任务续跑：上一轮真正 finalize 完（!isProcessing 且最后一条落进
  // messages 的是 assistant 消息）之后，如果攒了 auto_continue 待续跑输入，
  // 静默发起下一轮——不渲染用户气泡，用户感知不到这是"又发了一条消息"，
  // 跟手动回复"继续优化"效果一样，只是自动做的。见设计方案七点五
  // （前端消费 AutoContinueEvent，此前是已知缺口）。
  //
  // 注意：finalizeMessage 有几条"内容为空/重复签名/陈旧diff"分支会在不
  // append messages 的情况下直接 finalizeStream()（isProcessing→false）；
  // 命中这些分支时 last 仍是上一条 assistant 消息，下面的判断依然会放行
  // 触发续跑——这是有意为之（真实发生过 auto_continue 的场景理应继续），
  // 不是判断漏了这些分支。
  useEffect(() => {
    if (!pendingAutoContinueRef.current) return;
    if (isProcessing) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;

    // 独立review发现的竞态：同一次 commit 里，如果 pendingPatches 静默轮
    // effect 也判定该发（它先于本 effect 定义，会先跑），两边都读到
    // isProcessing===false，都会调 sendMessage，后发的这个会把先发的流
    // disconnect 掉。延后一个宏任务，让对方 sendMessage 里同步调用的
    // setIsProcessing(true) 先落地，再用实时 ref 复核一次。
    const timer = window.setTimeout(() => {
      if (isProcessingRef.current) return; // 另一个静默轮已经在跑，这次让它，ref 留着下次重试
      // 上一轮还有未落地的正文(打字机/finalize 定时器进行中):现在发新轮会
      // resetStreamBuffers 把它截断——2026-07-13 实测丢字"…推进到下一个模"。
      // pending 留着,finalize append 消息后本 effect 会因 messages 变化重跑。
      // (内容为空时不拦:agent_error/空回答的续跑维持原"有意放行"语义)
      if (
        pendingFinalizeAfterTypewriterRef.current &&
        (readLiveAnswer().trim() || readLiveThought().trim())
      ) {
        return;
      }
      if (autoContinueFiredCountRef.current >= AUTO_CONTINUE_FRONTEND_CAP) {
        console.warn(
          "[AgentChat] auto_continue 前端防御性上限触发，停止自动续跑",
          { fired: autoContinueFiredCountRef.current },
        );
        pendingAutoContinueRef.current = null;
        return;
      }
      const nextInput = pendingAutoContinueRef.current;
      if (!nextInput) return;
      pendingAutoContinueRef.current = null;
      autoContinueFiredCountRef.current += 1;

      // 静默轮同样必须走完整的新轮初始化（同上方 pendingPatches 静默轮的
      // 教训：裸调 sendMessage 会导致 streamRunRef 不推进，finalize 被同
      // run 判重吞掉）。
      isFinalizedRef.current = false;
      pendingFinalizeAfterTypewriterRef.current = false;
      const nextRunId = startNewRun();
      setActiveRunId(nextRunId);
      lastDoneRunRef.current = -1;
      currentProcessNodesRef.current = [];
      currentRunUserInputRef.current = "";
      hasPatchInCurrentStreamRef.current = false;
      currentAssistantMessageIdRef.current = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      setSearchResults((prev) => prev.filter((item) => item.messageId !== "current"));
      setLoadedResumes((prev) => prev.filter((item) => item.messageId !== "current"));
      setResumeEditDiffs((prev) => prev.filter((item) => item.messageId !== "current"));
      setDiagnosisToolEvents((prev) => prev.filter((item) => item.messageId !== "current"));
      setStructuredEvents((prev) => prev.filter((item) => item.messageId !== "current"));
      // next_user_input 已带 AUTO_CONTINUE_PREFIX，原样传给后端，不能再包装。
      void sendMessage(nextInput, resumeDataRef.current);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [messages, isProcessing, sendMessage]);

  const heroInitialConsumedRef = useRef(false);
  useEffect(() => {
    if (heroInitialConsumedRef.current || !initialSessionResolved) return;
    const fromHome = (location.state as { fromHome?: number } | null)?.fromHome;
    if (!fromHome) return;
    const openJd = sessionStorage.getItem("agent_open_jd_card") === "1";
    const pending = sessionStorage.getItem("agent_initial_text") || "";
    const hasImages = hasHeroHandoffImages();
    if (!openJd && !pending && !hasImages) return;
    if (
      isProcessing ||
      isPasteImporting ||
      isCreatingNewSessionRef.current ||
      messages.length > 0
    )
      return;
    heroInitialConsumedRef.current = true;
    sessionStorage.removeItem("agent_initial_text");
    if (openJd) {
      // 首页「按 JD 改简历」chip：先落成一轮对话（用户消息 + AI 引导回复），
      // 再在下方弹出 JD 优化交互卡——避免停在空态首页、卡片突兀浮底。
      sessionStorage.removeItem("agent_open_jd_card");
      const ts = Date.now();
      const jdMessages: Message[] = [
        {
          id: `${ts}-jd-q`,
          role: "user",
          content: "按目标岗位 JD 帮我改简历",
          timestamp: new Date().toISOString(),
        },
        {
          id: `${ts}-jd-a`,
          role: "assistant",
          content:
            "好的！请把你的简历和目标岗位的 JD（职位描述）发我，我来帮你逐条对齐、重写亮点、补齐匹配关键词 👇",
          timestamp: new Date().toISOString(),
        },
      ];
      setMessages(jdMessages);
      const jdConvId =
        conversationId?.trim() || currentSessionId || `conv-${ts}`;
      if (!conversationId) setConversationId(jdConvId);
      if (!currentSessionId) setCurrentSessionId(jdConvId);
      void persistSessionSnapshot(jdConvId, jdMessages, true);
      setShowJdCard(true);
      return;
    }
    if (hasImages) {
      // 首页粘贴的简历截图：复用图片解析链路（进对话 + 解析动画 + 渲染，不发 Agent、不诊断）
      void importResumeImagesInChat(pending || "解析这份简历", takeHeroHandoffImages());
    } else {
      void sendUserTextMessage(pending);
    }
  }, [
    initialSessionResolved,
    location.state,
    isProcessing,
    isPasteImporting,
    messages.length,
    sendUserTextMessage,
    importResumeImagesInChat,
  ]);

  const submitMessageWithAttachments = useCallback(
    async (userMessage: string, attachmentsToProcess: File[]) => {
      setResumeError(null);
      setIsUploadingFile(true);

      // 先立即进对话视图：上用户气泡（带文件卡）+ 解析占位，再做慢解析。
      // 原实现把 PDF 解析（glm-ocr + 结构化，实测 15-40s）同步 await 在
      // sendUserTextMessage 之前，期间既不进对话也不上气泡，用户停在落地页
      // 干等、看着像卡死。复用 importResumeFileInChat 的「先进对话再解析」范式。
      const userBubbleId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const attachmentMeta = attachmentsToProcess.map((file) => ({
        name: file.name,
        type: file.type,
        size: file.size,
      }));
      const userBubble: Message = {
        id: userBubbleId,
        role: "user",
        content: userMessage || "解析这份简历",
        timestamp: new Date().toISOString(),
        attachments: attachmentMeta,
      };
      const nextMessages = [...messages, userBubble];
      const isFirstMessage = messages.length === 0;
      setMessages(nextMessages);

      let validConversationId = conversationId;
      if (!validConversationId || validConversationId.trim() === "") {
        validConversationId = `conv-${Date.now()}`;
        setConversationId(validConversationId);
      }
      if (!currentSessionId) setCurrentSessionId(validConversationId);

      const parsingMsgId = `${userBubbleId}-parsing`;
      const parseStartedAt = Date.now();
      const parsingMsg: Message = {
        id: parsingMsgId,
        role: "assistant",
        content: "正在解析简历文件、请稍候…",
        timestamp: new Date().toISOString(),
        meta: { pasteImportParsing: true, parseStartedAt },
      };
      const withParsing = [...nextMessages, parsingMsg];
      setMessages(withParsing);
      await persistSessionSnapshot(validConversationId, withParsing, isFirstMessage);

      try {
        const attachmentBlocks: string[] = [];
        let latestResumeDataForRequest: ResumeData | null = null;

        for (const file of attachmentsToProcess) {
          const isPdf =
            file.type === "application/pdf" ||
            file.name.toLowerCase().endsWith(".pdf");
          if (isPdf) {
            const resumeEntryId = `uploaded-pdf-${file.lastModified}-${file.size}`;
            const resumeDisplayName =
              file.name.replace(/\.pdf$/i, "") || "上传简历";
            const uploadMessageId = `upload-pdf-${file.lastModified}-${file.size}`;

            setLoadedResumes((prev) => {
              const nextEntry = {
                id: resumeEntryId,
                name: resumeDisplayName,
                messageId: uploadMessageId,
              };
              const existingIndex = prev.findIndex(
                (item) => item.id === resumeEntryId,
              );
              if (existingIndex >= 0) {
                const updated = [...prev];
                updated[existingIndex] = {
                  ...updated[existingIndex],
                  ...nextEntry,
                };
                return updated;
              }
              return [...prev, nextEntry];
            });
            updateResumePdfState(resumeEntryId, {
              blob: file,
              loading: true,
              progress: "已加载原始 PDF，正在解析简历内容...",
              error: null,
            });
            setAllowPdfAutoRender(true);
            setSelectedResumeId(resumeEntryId);

            const formData = new FormData();
            formData.append("file", file);

            const response = await fetch(`${apiBaseUrl}/api/resume/upload-pdf`, {
              method: "POST",
              body: formData,
            });
            if (!response.ok) {
              throw new Error(`PDF 解析失败: ${response.status}`);
            }

            const data = await response.json();
            const parsedResume = data?.resume;
            if (parsedResume && typeof parsedResume === "object") {
              const resolvedUserId = user?.id ?? null;
              const canonical = normalizeImportedResumeToCanonical(
                parsedResume as Record<string, any>,
                {
                  resumeId: resumeEntryId,
                  title: resumeDisplayName,
                },
              );
              const resumeDataWithMeta = {
                ...canonical,
                user_id: resolvedUserId,
                resume_id: resumeEntryId,
                _meta: {
                  ...(canonical as any)._meta,
                  user_id: resolvedUserId,
                  resume_id: resumeEntryId,
                },
              } as ResumeData;
              latestResumeDataForRequest = resumeDataWithMeta;
              setResumeData(resumeDataWithMeta);
              try {
                await saveResume(resumeDataWithMeta, resumeEntryId);
              } catch (saveError) {
                console.warn("[AgentChat] 上传简历保存失败:", saveError);
              }
              setLoadedResumes((prev) => {
                const nextEntry = {
                  id: resumeEntryId,
                  name: resumeDisplayName,
                  messageId: uploadMessageId,
                  resumeData: resumeDataWithMeta,
                };
                const existingIndex = prev.findIndex(
                  (item) => item.id === resumeEntryId,
                );
                if (existingIndex >= 0) {
                  const updated = [...prev];
                  updated[existingIndex] = nextEntry;
                  return updated;
                }
                return [...prev, nextEntry];
              });
              updateResumePdfState(resumeEntryId, {
                loading: false,
                progress: "",
                error: null,
              });
              attachmentBlocks.push(
                `已上传并解析 PDF 文件《${file.name}》。请基于这份简历内容进行分析并给出优化建议。`,
              );
            } else {
              updateResumePdfState(resumeEntryId, {
                loading: false,
                progress: "",
                error: "未解析出结构化简历内容，当前展示原始 PDF。",
              });
              attachmentBlocks.push(
                `已上传 PDF 文件《${file.name}》，但未解析出结构化简历内容。`,
              );
            }
            continue;
          }

          const isTextLike =
            file.type.startsWith("text/") ||
            /\.(txt|md|json|csv)$/i.test(file.name);
          if (!isTextLike) {
            throw new Error("仅支持 pdf/txt/md/json/csv 文件");
          }

          const rawText = await file.text();
          const maxLen = 12000;
          const clipped = rawText.slice(0, maxLen);
          const truncatedNote =
            rawText.length > maxLen
              ? "\n[文件内容过长，已截断为前 12000 字符]"
              : "";
          attachmentBlocks.push(
            `文件《${file.name}》内容：\n${clipped}${truncatedNote}`,
          );
        }

        const baseMessage =
          userMessage || "我上传了附件，请先提炼关键信息并给出下一步建议。";
        const finalMessage = attachmentBlocks.length
          ? `${baseMessage}\n\n${attachmentBlocks.join("\n\n")}`
          : baseMessage;
        // 解析完成：移除解析占位，触发 Agent 真实一轮。用户气泡已在上方展示，
        // silentUserBubble=true 让 sendUserTextMessage 不再重复上气泡。
        setMessages((prev) => prev.filter((m) => m.id !== parsingMsgId));
        await sendUserTextMessage(
          finalMessage,
          attachmentsToProcess,
          latestResumeDataForRequest,
          false,
          true,
        );
      } catch (error) {
        console.error("[AgentChat] Failed to send message:", error);
        const errText =
          error instanceof Error ? error.message : "文件上传失败，请稍后重试";
        setResumeError(errText);
        // 解析占位转失败态 + 存重试闭包（与图片/文件导入同款，失败不静默、一键可重试）
        importRetryMapRef.current.set(parsingMsgId, () => {
          void submitMessageWithAttachments(userMessage, attachmentsToProcess);
        });
        setMessages((prev) =>
          prev.map((m) =>
            m.id === parsingMsgId
              ? {
                  ...m,
                  content: `简历解析失败：${errText}`,
                  timestamp: new Date().toISOString(),
                  meta: {
                    pasteImportParsing: false,
                    parseStartedAt,
                    parseElapsedMs: Date.now() - parseStartedAt,
                    importRetry: true,
                  },
                }
              : m,
          ),
        );
      } finally {
        setIsUploadingFile(false);
      }
    },
    [
      apiBaseUrl,
      user?.id,
      messages,
      conversationId,
      currentSessionId,
      persistSessionSnapshot,
      sendUserTextMessage,
      updateResumePdfState,
      setResumeData,
      setLoadedResumes,
      setAllowPdfAutoRender,
      setSelectedResumeId,
    ],
  );

  const handleFillCreateResumePrompt = useCallback(() => {
    handleCreateResume();
  }, [handleCreateResume]);

  const addAttachmentFiles = useCallback((files: File[]) => {
    if (files.length === 0) return;
    setPendingAttachments((prev) => {
      const existingKeys = new Set(
        prev.map((file) => `${file.name}-${file.size}-${file.lastModified}`),
      );
      const unique = files.filter(
        (file) =>
          !existingKeys.has(
            `${file.name}-${file.size}-${file.lastModified}`,
          ),
      );
      return [...prev, ...unique];
    });
  }, []);

  const handleUploadFile = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      if (selectedFiles.length === 0) return;
      if (isProcessing) {
        toast.error("当前正在处理消息，请稍后再上传。");
        event.target.value = "";
        return;
      }
      addAttachmentFiles(selectedFiles);
      event.target.value = "";
    },
    [isProcessing, addAttachmentFiles],
  );

  // 截图 / 剪贴板图片粘贴进输入框：作为简历图片附件收下，发送时统一走图片识别链路
  const handlePasteFiles = useCallback(
    (files: File[]) => {
      if (isProcessing) return;
      addAttachmentFiles(files);
    },
    [isProcessing, addAttachmentFiles],
  );

  const handleRemoveAttachment = useCallback((target: File) => {
    const targetKey = `${target.name}-${target.size}-${target.lastModified}`;
    setPendingAttachments((prev) =>
      prev.filter(
        (file) =>
          `${file.name}-${file.size}-${file.lastModified}` !== targetKey,
      ),
    );
  }, []);

  const handleClickUpload = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  useEffect(() => {
    if (!pendingResumeInput.trim()) return;
    if (!resumeData) return;
    if (showResumeSelector || isProcessing) return;
    // 同步 ref 守卫:setPendingResumeInput("") 是异步 state 更新,在嵌套
    // commit / StrictMode 双跑等场景下,本 effect 可能带着旧的 pendingResumeInput
    // 快照连续重入——2026-07-13 实测一次点击引发 48 连发 sendMessage、后端被
    // 273 轮"我要优化简历"打爆(Maximum update depth @ useCLTP finally)。
    // ref 同步生效,同一发弹药只允许发射一次。
    if (replayFiredForInputRef.current === pendingResumeInput) return;
    replayFiredForInputRef.current = pendingResumeInput;
    const replay = pendingResumeInput;
    setPendingResumeInput("");
    // silentUserBubble:重发的是用户已说过的原话,不渲染重复气泡
    void sendUserTextMessage(replay, undefined, resumeData, false, true);
  }, [
    pendingResumeInput,
    resumeData,
    showResumeSelector,
    isProcessing,
    sendUserTextMessage,
  ]);

  useEffect(() => {
    if (answerCompleteCount === 0) return;
    if (answerCompleteCount <= lastHandledAnswerCompleteRef.current) {
      return;
    }
    isFinalizedRef.current = false;
    lastHandledAnswerCompleteRef.current = answerCompleteCount;
    if (lastFinalizedRunRef.current === streamRunRef.current) {
      pendingFinalizeAfterTypewriterRef.current = false;
      return;
    }
    // 打字机播完 → 标记待 finalize。完成态内容由 currentRunState 保留至
    // finalizeStream，不再抓页面级完成快照（captureCompletionSnapshot 已随
    // 镜像 ref 一并移除）。
    pendingFinalizeAfterTypewriterRef.current = true;
  }, [answerCompleteCount]);

  /**
   * Send message to backend via SSE
   */
  // ——「按 JD 优化简历」交互卡回调 ——
  // 卡内上传简历文件：只解析入库、加载到会话，全程不发 Agent（点「开始优化」才优化）
  const handleJdCardUploadResume = useCallback(
    (file: File) => {
      if (isProcessing || isPasteImporting || isUploadingFile) return;
      void importResumeFileInChat(file);
    },
    [isProcessing, isPasteImporting, isUploadingFile, importResumeFileInChat],
  );

  // 卡内粘贴简历文本：sendUserTextMessage 内部会自动识别为粘贴简历并走 /api/resume/parse 解析导入
  const handleJdCardPasteResume = useCallback(
    (text: string) => {
      if (!text.trim() || isProcessing || isPasteImporting) return;
      void sendUserTextMessage(text);
    },
    [isProcessing, isPasteImporting, sendUserTextMessage],
  );

  // 简历已在 context + JD 已给：让 Agent 按 JD 逐条优化（走已补的「按 JD 改简历（已有简历）」prompt 脚本）
  const handleJdCardStartOptimize = useCallback(
    (jdText: string) => {
      if (!jdText.trim()) return;
      setShowJdCard(false);
      void sendUserTextMessage(
        `我的目标岗位 JD 如下，请对照它逐条优化我的整份简历：重写各段经历、突出与 JD 匹配的技能与成果、补齐缺失的关键词。\n\n【目标岗位 JD】\n${jdText.trim()}`,
      );
    },
    [sendUserTextMessage],
  );

  // 收尾卡：下载当前右侧预览的 PDF；预览还没生成时给提示
  const handleDownloadPdf = useCallback(() => {
    const preview = selectedResumeId ? resumePdfPreview[selectedResumeId] : null;
    const blob = preview?.blob;
    if (!blob) {
      toast("右侧 PDF 预览生成后即可下载，稍等片刻再点");
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${resumeData?.basic?.name || "简历"}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  }, [selectedResumeId, resumePdfPreview, resumeData]);

  // 收尾卡：去编辑器精修。
  // 修复：原来跳无 ID 的新建路由，会被编辑器当「新建默认模板」加载成默认简历（丢当前优化后的简历）。
  // 改为先把优化后的数据回存到该简历记录，再带 ID 跳 /workspace/{id}，编辑器按 ID 加载正确简历。
  const handleGoEditor = useCallback(async () => {
    const target =
      loadedResumes.find((r) => r.id === selectedResumeId) || loadedResumes[0];
    if (target?.id && target.resumeData) {
      try {
        await saveResume(target.resumeData as any, target.id);
      } catch (e) {
        console.error("[AgentChat] 去编辑器前保存优化后简历失败:", e);
      }
      setCurrentResumeId(target.id);
      navigate(`/workspace/${target.id}`);
      return;
    }
    navigate("/workspace/new");
  }, [loadedResumes, selectedResumeId, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedInput = input.trim();
    const hasAttachments = pendingAttachments.length > 0;
    if ((!trimmedInput && !hasAttachments) || isProcessing || isUploadingFile || isPasteImporting)
      return;

    // 每轮新消息开始前清理可能残留的状态

    // 清除之前的错误
    setResumeError(null);

    const userMessage = formatChatInput(trimmedInput);
    const attachmentsToProcess = pendingAttachments;
    setInput("");
    setPendingAttachments([]);
    try {
      if (!hasAttachments) {
        await sendUserTextMessage(userMessage);
        return;
      }

      // 图片附件走「解析导入」链路（进对话 + 解析动画 + 展示，不发 Agent）；
      // 其余（PDF / 文本）仍交给 Agent 处理。
      const imageAttachments = attachmentsToProcess.filter((file) =>
        file.type.startsWith("image/"),
      );
      if (imageAttachments.length > 0) {
        await importResumeImagesInChat(userMessage, imageAttachments);
        return;
      }

      await submitMessageWithAttachments(userMessage, attachmentsToProcess);
    } catch (error) {
      console.error("[AgentChat] Failed to send message:", error);
      setPendingAttachments(attachmentsToProcess);
    }
  };

  const handleComposerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Enter" || event.shiftKey) {
        return;
      }
      // 输入法 composing 期间（如中文选词按 Enter 确认）不提交
      if (event.nativeEvent.isComposing) {
        return;
      }
      event.preventDefault();
      if (!input.trim() || isProcessing || isPasteImporting) {
        return;
      }
      event.currentTarget.form?.requestSubmit();
    },
    [input, isProcessing],
  );

  /**
   * Clear conversation
   */
  const handleClearConversation = () => {
    setMessages([]);
    setDiagnosisToolEvents([]);
    setStructuredEvents([]);
    finalizeStream();
  };

  const activeSessionId = currentSessionId || conversationId;

  // 空态（无消息、非处理中、非简历选择器）：参考 Manus 把输入框居中展示，
  // 输入框移进 ChatEmptyState；有消息时回到底部输入区。
  const isEmptyState =
    messages.length === 0 && !isProcessing && !showResumeSelector;

  const composerNode = (
    <Composer
      input={input}
      isProcessing={isProcessing || isPasteImporting}
      isUploadingFile={isUploadingFile}
      isResumePreviewActive={isResumePreviewActive}
      pendingAttachments={pendingAttachments}
      fileInputRef={fileInputRef}
      onSubmit={handleSubmit}
      onInputChange={setInput}
      onKeyDown={handleComposerKeyDown}
      onFileChange={handleUploadFile}
      onPasteFiles={handlePasteFiles}
      onRemoveAttachment={handleRemoveAttachment}
      onClickUpload={handleClickUpload}
      onShowResumeSelector={() => {
        // 当前会话已有简历：直接展示它（渲染右侧预览），不弹"开始处理简历"选择面板
        const current =
          selectedLoadedResume ||
          loadedResumes[loadedResumes.length - 1] ||
          null;
        if (current) {
          setSelectedResumeId(current.id);
          setAllowPdfAutoRender(true);
          void renderResumePdfPreview(current, true);
          return;
        }
        // 一份简历都没有时，才打开选择器让用户创建 / 导入 / 选择
        setResumeSelectorInitialStep("entry");
        setShowResumeSelector(true);
      }}
      onStop={handleStopGeneration}
      previewConcealed={Boolean(selectedResumeId) && previewConcealed}
      onRevealPreview={() => setPreviewConcealed(false)}
    />
  );

  const showByokErrorAction = Boolean(
    resumeError &&
      (/AI_RATE_LIMITED|AI_QUOTA_EXHAUSTED|上限|额度|余额不足|配额/.test(resumeError) ||
        (resumeError === lastError &&
          (lastErrorCode === "AI_RATE_LIMITED" ||
            lastErrorCode === "AI_QUOTA_EXHAUSTED"))),
  );

  return (
    <WorkspaceLayout
      agentSession={{
        currentSessionId: activeSessionId,
        sessionsRefreshKey,
        onSelectSession: handleSelectSession,
        onCreateSession: handleCreateSession,
        onDeleteSession: deleteSession,
        onRenameSession: renameSession,
      }}
    >
      <div className="h-full bg-chat-canvas dark:bg-slate-950 flex flex-col overflow-hidden font-chat">
        <div className="flex-1 flex overflow-hidden relative">
          {/* Left: Chat */}
          <section className="flex-1 min-w-0 flex flex-col h-full">
            <div className="shrink-0 border-b-2 border-black bg-chat-canvas/80 px-4 py-2 dark:border-slate-800 dark:bg-slate-950/80 fresh:border-slate-200">
              <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-none border px-2.5 py-1 text-xs font-medium fresh:rounded-full ${
                      byokActive
                        ? "border-[#3367D6] bg-blue-50 text-[#1a73e8] dark:border-blue-500/60 dark:bg-blue-950/50 dark:text-blue-300"
                        : "border-black/20 bg-white/80 text-slate-700 fresh:border-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                    }`}
                  >
                    {byokActive
                      ? `自带 Key · ${byokConfig.provider}/${byokConfig.model || "自定义"}`
                      : "免费体验"}
                  </span>
                  {!byokActive && (
                    <ModelSelector value={selectedModel} onChange={handleModelChange} />
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setByokModalOpen(true)}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-none border border-black bg-white px-2.5 py-1 text-xs font-medium text-slate-800 shadow-[2px_2px_0px_0px_#000000] transition-all hover:bg-slate-50 fresh:rounded-lg fresh:border-slate-200 fresh:shadow-sm dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
                >
                  <KeyRound className="h-3.5 w-3.5 text-[#3367D6] dark:text-blue-400" />
                  <span>自带 API Key</span>
                </button>
              </div>
            </div>
            <CustomScrollbar as="main" className="flex-1 px-4 py-8 flex flex-col">
              <div className="max-w-3xl mx-auto w-full flex-1 flex flex-col">
                {loadingResume && (
                  <div className="text-sm text-gray-400 dark:text-slate-500 mb-4">
                    正在加载简历...
                  </div>
                )}
                {resumeError && (
                  <div className="flex items-start gap-3 p-3 bg-red-50 dark:bg-red-950/30 border-2 fresh:border border-black fresh:border-slate-200 fresh:border-slate-200 dark:border-red-900/50 rounded-none fresh:rounded-lg mb-4">
                    <span className="text-sm text-red-600 dark:text-red-400 flex-1">{resumeError}</span>
                    {showByokErrorAction && (
                      <button
                        type="button"
                        onClick={() => setByokModalOpen(true)}
                        className="text-xs font-semibold text-[#1a73e8] dark:text-blue-300 bg-white dark:bg-slate-900 border border-[#3367D6] dark:border-blue-500 rounded-none fresh:rounded-lg px-2.5 py-1 hover:bg-blue-50 dark:hover:bg-blue-950/40 shrink-0"
                      >
                        配置自带 API Key
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setResumeError(null);
                        const lastUser = [...messages].reverse().find((m) => m.role === "user");
                        if (lastUser) void sendUserTextMessage(lastUser.content);
                      }}
                      className="text-xs font-medium text-red-600 dark:text-red-300 border border-black fresh:border-slate-200 dark:border-red-800 rounded-none fresh:rounded-lg px-2 py-1 hover:bg-red-100 dark:hover:bg-red-900/40 shrink-0"
                    >
                      重新发送
                    </button>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(resumeError);
                        toast.success("已复制错误信息");
                      }}
                      className="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 underline shrink-0"
                    >
                      复制
                    </button>
                  </div>
                )}
                {isLoadingSession && (
                  <div className="text-xs text-gray-400 dark:text-slate-500 mb-4">
                    正在加载会话...
                  </div>
                )}

                {isEmptyState &&
                  (carryResumePrompt ? (
                    <div className="w-full max-w-lg mx-auto px-4 flex-1 flex flex-col justify-center">
                      <div className="rounded-none fresh:rounded-lg border-2 fresh:border border-black fresh:border-slate-200 fresh:border-slate-200 bg-chat-surface p-6 text-center shadow-[3px_3px_0px_0px_#000000] fresh:shadow-sm dark:border-white dark:bg-slate-800/60 dark:shadow-[3px_3px_0px_0px_#ffffff]">
                        <div className="mb-1 text-sm text-chat-ink-muted dark:text-slate-400">
                          从编辑页带来了
                        </div>
                        <div className="mb-5 truncate text-lg font-bold text-chat-ink dark:text-slate-100">
                          「{carryResumePrompt.name || "未命名简历"}」
                        </div>
                        <div className="flex gap-3">
                          <button
                            type="button"
                            onClick={handleContinueEditCarry}
                            className="flex-1 rounded-none fresh:rounded-lg border-2 fresh:border border-black fresh:border-slate-200 fresh:border-slate-200 bg-chat-accent px-4 py-2.5 text-sm font-semibold text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm transition-all hover:shadow-none hover:translate-x-[1px] hover:translate-y-[1px] dark:border-white dark:bg-amber-500 dark:shadow-[2px_2px_0px_0px_#ffffff]"
                          >
                            继续编辑这份
                          </button>
                          <button
                            type="button"
                            onClick={handleStartNewFromCarry}
                            className="flex-1 rounded-none fresh:rounded-lg border-2 fresh:border border-black fresh:border-slate-200 fresh:border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-chat-ink-muted shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm transition-all hover:text-chat-ink hover:shadow-none hover:translate-x-[1px] hover:translate-y-[1px] dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300"
                          >
                            开启新会话
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <ChatEmptyState
                      onCreateResume={handleFillCreateResumePrompt}
                      onImportResume={handleImportResume}
                      onSelectExisting={() => {
                        setResumeSelectorInitialStep("existing");
                        setShowResumeSelector(true);
                      }}
                      composerSlot={composerNode}
                    />
                  ))}

                <MessageTimeline
                  messages={messages}
                  loadedResumes={loadedResumes}
                  searchResults={searchResults}
                  resumeEditDiffs={resumeEditDiffs}
                  diagnosisToolEvents={diagnosisToolEvents}
                  structuredEvents={structuredEvents}
                  pendingPatches={pendingPatches}
                  copiedId={copiedId}
                  stripResumeEditMarkdown={stripResumeEditMarkdown}
                  onSetCopiedId={setCopiedId}
                  onImportRetry={handleImportRetry}
                  onOpenSearchPanel={setActiveSearchPanel}
                  onOpenResume={(resumeForMessage) => {
                    setAllowPdfAutoRender(true);
                    setSelectedResumeId(resumeForMessage.id);
                    if (resumeForMessage.resumeData) {
                      setResumeData(resumeForMessage.resumeData);
                    }
                  }}
                  onOpenResumeSelector={() => {
                    setResumeSelectorInitialStep("entry");
                    setShowResumeSelector(true);
                  }}
                  onSuggestionClick={(msg) => {
                    setInput("");
                    void sendUserTextMessage(msg);
                  }}
                  onDownloadPdf={handleDownloadPdf}
                  onGoEditor={handleGoEditor}
                  askQuestionHandler={{
                    onSubmit: handleAskQuestionSubmit,
                    submitted: askQuestionSubmitted,
                  }}
                />

                <StreamingLane
                  conversationRun={currentRunState}
                  isProcessing={isProcessing}
                  onSuggestionClick={(msg) => {
                    setInput("");
                    void sendUserTextMessage(msg);
                  }}
                  stripResumeEditMarkdown={stripResumeEditMarkdown}
                  onOpenSearchPanel={setActiveSearchPanel}
                  onResponseTypewriterComplete={finalizeAfterTypewriter}
                  askQuestionHandler={{
                    onSubmit: handleAskQuestionSubmit,
                    submitted: askQuestionSubmitted,
                  }}
                />

                {/* 按 JD 优化简历交互卡（首页「按 JD 改简历」chip 进入） */}
                {showJdCard && (
                  <div className="px-4 py-2">
                    <JdOptimizeChatCard
                      resumeLoaded={Boolean(resumeData)}
                      resumeName={resumeData?.basic?.name}
                      busy={isPasteImporting || isProcessing || isUploadingFile}
                      onUploadResumeFile={handleJdCardUploadResume}
                      onPasteResumeText={handleJdCardPasteResume}
                      onStartOptimize={handleJdCardStartOptimize}
                      onDismiss={() => setShowJdCard(false)}
                    />
                  </div>
                )}

                {/* 简历选择器：放在对话流末尾，与最新消息同区域展示 */}
                {showResumeSelector && (
                  <div
                    className={
                      messages.length === 0 && !isProcessing
                        ? "flex flex-1 items-center justify-center py-8"
                        : ""
                    }
                  >
                    <div className="w-full max-w-2xl">
                      <ResumeSelector
                        initialStep={resumeSelectorInitialStep}
                        onSelect={handleResumeSelect}
                        onCreateResume={handleCreateResume}
                        onImportResume={handleImportResume}
                        onFillCreatePrompt={handleFillCreateResumePrompt}
                        onCancel={handleResumeSelectorCancel}
                      />
                    </div>
                  </div>
                )}

                {/* 对话流唯一反馈栏：绑最后一条 assistant 回复，永远位于
                    所有消息与面板之后（2026-07-15 问题 A：反馈上收）。 */}
                <ConversationFeedbackBar
                  messages={messages}
                  isProcessing={isProcessing}
                  onRegenerate={() => {
                    const userMessages = messages.filter((m) => m.role === "user");
                    const lastUserMsg = userMessages[userMessages.length - 1];
                    if (lastUserMsg) {
                      void sendUserTextMessage(lastUserMsg.content);
                    }
                  }}
                />

                {/* 处理中占位由 StreamingLane 内的星芒 ThinkingIndicator 统一负责，此处不再重复 */}

                <div ref={messagesEndRef} />
              </div>
            </CustomScrollbar>

            {/* Input Area（有消息时固定底部；空态下输入框移到中间，见 ChatEmptyState） */}
            {!isEmptyState && (
              <div className="bg-chat-canvas dark:bg-slate-950 px-4 py-4 pb-8">
                <div className="max-w-3xl mx-auto w-full">{composerNode}</div>
              </div>
            )}
          </section>

          {/* Right: Resume Preview - 只在有选中简历时显示；concealed 时
              视觉隐藏但保持挂载渲染（对话区看起来是纯聊天，展开零等待） */}
          {selectedResumeId && (
            <AgentPdfPreviewPanel
              resumeName={selectedLoadedResume?.name}
              pdfBlob={selectedResumePdfState.blob}
              loading={selectedResumePdfState.loading}
              progress={selectedResumePdfState.progress}
              error={selectedResumePdfState.error}
              justUpdated={previewJustUpdated}
              concealed={previewConcealed}
              onToggleConceal={() => setPreviewConcealed(true)}
              onRerender={() => {
                if (selectedLoadedResume) {
                  void renderResumePdfPreview(selectedLoadedResume, true);
                }
              }}
              onClose={() => {
                setAllowPdfAutoRender(false);
                setSelectedResumeId(null);
              }}
              onSave={async () => {
                if (!selectedLoadedResume) return;
                await saveResume(
                  (selectedLoadedResume as any).resumeData,
                  selectedLoadedResume.id,
                );
              }}
            />
          )}
        </div>
        <SearchResultPanel
          isOpen={!!activeSearchPanel}
          query={activeSearchPanel?.query || ""}
          totalResults={activeSearchPanel?.total_results || 0}
          results={activeSearchPanel?.results || []}
          onClose={() => setActiveSearchPanel(null)}
        />
        <AIImportModal
          isOpen={aiImportModalOpen}
          sectionType="all"
          sectionTitle="导入简历"
          onClose={() => setAiImportModalOpen(false)}
          onSave={handleAIImportSave}
        />
        <ByokConfigModal
          open={byokModalOpen}
          onClose={() => setByokModalOpen(false)}
          onConfigChange={setByokConfig}
        />
      </div>
    </WorkspaceLayout>
  );
}
