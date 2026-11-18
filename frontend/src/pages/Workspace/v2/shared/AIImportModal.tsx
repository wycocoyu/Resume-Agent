import { toast } from '@/lib/toast'

/**
 * AI 导入弹窗组件（从 v1 移植）
 * 支持全局导入和分模块导入
 */
import {
  ChevronDown,
  Copy,
  RotateCcw,
  Save,
  Wand2,
  X,
  Upload,
  FileText,
  File,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "../../../../lib/utils";
import FileUploadZone from "./FileUploadZone";
import { getApiBaseUrl } from "@/lib/runtimeEnv";
import { extractApiErrorMessage } from "@/lib/apiError";
import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetchWithTimeout";
import { uploadResumeImageStream } from "@/lib/uploadResumeImageStream";

// 简历解析走大模型，耗时较长，给一个宽松上限避免后端挂死时前端一直卡在"解析中"
const PARSE_TIMEOUT_MS = 150_000;

// DeepSeek 官方 logo（Wikimedia Commons，MIT/Expat）
const DEEPSEEK_LOGO_URL =
  "https://upload.wikimedia.org/wikipedia/commons/e/ec/DeepSeek_logo.svg";

// 可用的 AI 模型列表
// 2026-09-16：阿里云百炼欠费，全线切到 DeepSeek 官方。
// 官方在售只有 deepseek-flash / deepseek-v4-pro；原「Claude Sonnet 4.6（仅 PDF）」
// 所依赖的中转站已下架该模型，一并移除。
const AI_MODELS = [
  {
    id: "deepseek-flash",
    name: "DeepSeek Flash",
    description: "智能解析简历内容（快速）",
    logoUrl: DEEPSEEK_LOGO_URL,
  },
];

// 视觉模型（图片识别），上传图片时由用户选择
const VISION_MODELS = [
  {
    id: "glm-ocr",
    name: "智谱 GLM-OCR",
    description: "文档 OCR",
  },
];

export type SectionType =
  | "contact"
  | "education"
  | "experience"
  | "projects"
  | "skills"
  | "selfEvaluation"
  | "awards"
  | "summary"
  | "opensource"
  | "all"; // 全局导入

export interface AIImportModalProps {
  isOpen: boolean;
  sectionType: SectionType | string;
  sectionTitle: string;
  onClose: () => void;
  onSave: (data: any, meta?: { awardsListType?: 'unordered' | 'ordered' }) => void;
}

// AI 导入提示词占位符
const aiImportPlaceholders: Record<string, string> = {
  contact:
    "张三\n电话: 13800138000\n邮箱: zhangsan@example.com\n地区: 北京\n求职意向: 后端开发工程师",
  education:
    "华南理工大学\n本科 · 计算机科学与技术\n2020.09 - 2024.06\nGPA: 3.8/4.0",
  experience:
    "字节跳动 · 后端开发实习生\n2023.06 - 2023.09\n- 负责推荐系统后端开发\n- 优化接口性能，QPS 提升 50%",
  projects:
    "智能简历系统\n技术负责人 · 2023.01 - 2023.06\n- 使用 React + FastAPI 开发\n- 集成 AI 自动生成功能\nGitHub: https://github.com/xxx/resume",
  skills:
    "编程语言: Java, Python, Go\n数据库: MySQL, Redis, MongoDB\n框架: Spring Boot, FastAPI",
  selfEvaluation:
    "具备扎实的后端开发基础，熟悉 Java/Go、MySQL、Redis 与微服务架构，关注系统性能优化、稳定性建设和工程化落地。",
  awards: "国家奖学金 · 2023\nACM 省级一等奖 · 2022\n优秀毕业生 · 2024",
  summary:
    "3年后端开发经验，熟悉 Java/Go 技术栈，擅长高并发系统设计与优化，有丰富的微服务架构经验。",
  opensource:
    "Kubernetes\n核心贡献者 · 2023.03 - 2024.06\n- 提交性能优化 PR #12345，优化 Pod 调度算法，被成功合并\n- 修复关键 Bug #12346，解决内存泄漏问题\n- 参与社区讨论，协助新贡献者\n仓库: https://github.com/kubernetes/kubernetes\n\nVue.js\n贡献者 · 2022.08 - 2023.12\n- 实现新特性：响应式系统性能优化\n- 修复 SSR 渲染问题，提升首屏加载速度 30%\n- 编写单元测试，提升代码覆盖率\n仓库: https://github.com/vuejs/vue\n\nReact\n社区维护者 · 2021.05 - 2022.10\n- 维护 React 官方文档中文翻译\n- 提交多个 Bug 修复和性能优化 PR\n- 组织线上技术分享活动\n仓库: https://github.com/facebook/react",
  all: "张三\n电话: 13800138000\n邮箱: zhangsan@example.com\n求职意向: 后端开发工程师\n\n教育经历:\n北京大学\n计算机科学与技术\n2022.09 - 2026.06\n学校: 清华大学\n学历: 本科\n专业: 电子信息\n\n实习经历:\n实习经历一\n算法实习生\n2025.06 - 2025.10\n\n实习经历二\n后端开发实习生\n2025.02 - 2025.06\n\n实习经历三\n前端开发实习生\n2024.12 - 2025.01\n\n项目经历:\n项目一\n- 子项目甲\n  * 描述该子项目的主要目标和解决的问题\n  * 概述采用的核心技术手段或架构思路\n  * 说明实现过程中的关键策略或容灾措施\n- 子项目乙\n  * 介绍从 0 到 1 搭建某模块的背景与价值\n  * 说明缓存或性能优化的思路与结果\n  * 描述数据一致性或稳定性保障方案\n- 子项目丙\n  * 总结优化高风险操作的范围与收益\n  * 概括查询调优、索引策略等具体动作\n  * 解释资源隔离或负载转移方式\n\n项目二\n- 项目描述：\n  概述一个具备多模态检索、长文阅读与结构化输出能力的智能系统，强调其解决的痛点与特性。\n- 核心职责与产出：\n  描述在需求拆解、链路打通以及配套平台建设中的角色与贡献。\n  * 模块一：说明如何利用大模型进行推理规划与查询扩展，提升召回能力\n  * 模块二：概括多源融合检索架构，指出使用的检索方式与调度策略\n  * 模块三：描述 RAG 或抗幻觉生成的实现思路、Prompt 策略与输出形式\n  * 模块四：介绍广告或数据闭环链路的建设，涵盖埋点、分析与反馈机制\n\n开源经历:\n社区贡献一（某分布式项目）\n* 仓库：[https://example.com/repo1](https://example.com/repo1)\n* 简述提交的核心 PR 或 Issue 处理经验\n* 说明在社区内承担的协作职责\n\n社区贡献二\n* 组件一：列举涉及的技术栈与能力范围\n* 仓库：[https://example.com/repo2（可演示）](https://example.com/repo2（可演示）)\n* 能力二：描述检索、知识构建或多 Agent 流程的实现\n* 成果：简述分享传播与社区反馈\n\n专业技能:\n后端: 熟悉若干编程语言或服务框架\n数据库: 了解常见数据库及调优思路\n缓存: 掌握缓存策略与典型问题处理\n网络: 熟悉常见网络协议与连接管理\n操作系统: 理解进程线程与资源管理机制\nAI: 了解 Agent、RAG、Function Call 与 Prompt 工程\n\n荣誉奖项:\n例如学科竞赛、省级奖项等",
};

export function AIImportModal({
  isOpen,
  sectionType,
  sectionTitle,
  onClose,
  onSave,
}: AIImportModalProps) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [streamChars, setStreamChars] = useState(0);
  const [parsedData, setParsedData] = useState<any>(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [finalTime, setFinalTime] = useState<number | null>(null);
  const [selectedModel, setSelectedModel] = useState("deepseek-flash");
  const [selectedVisionModel, setSelectedVisionModel] = useState("glm-ocr");
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedImage2, setSelectedImage2] = useState<File | null>(null);
  const [copied, setCopied] = useState(false);
  const [importMode, setImportMode] = useState<"pdf" | "image" | "text">("pdf");
  const [currentStep, setCurrentStep] = useState<"input" | "results">("input");
  const [awardsListType, setAwardsListType] = useState<'unordered' | 'ordered'>('unordered');
  const [showTipQr, setShowTipQr] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉框
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setShowModelDropdown(false);
      }
    };
    if (showModelDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showModelDropdown]);

  // 计时器逻辑
  useEffect(() => {
    if (parsing) {
      setElapsedTime(0);
      setFinalTime(null);
      startTimeRef.current = Date.now();
      timerRef.current = setInterval(() => {
        setElapsedTime(Date.now() - startTimeRef.current);
      }, 100);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
      if (startTimeRef.current > 0) {
        setFinalTime(Date.now() - startTimeRef.current);
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [parsing]);

  // 重置状态
  useEffect(() => {
    if (!isOpen) {
      setText("");
      setParsedData(null);
      setFinalTime(null);
      setSelectedFile(null);
      setSelectedImage2(null);
      setImportMode("pdf");
      setCurrentStep("input");
      setAwardsListType('unordered');
    }
  }, [isOpen]);

  // AI 解析
  const handleParse = async () => {
    if (!text.trim()) return;
    setParsing(true);
    setParsedData(null);
    setStreamChars(0);

    const apiBase = getApiBaseUrl();
    // 处理命名不一致：openSource -> opensource
    const normalizedType =
      sectionType === "openSource"
        ? "opensource"
        : sectionType === "selfEvaluation"
          ? "summary"
          : sectionType;

    try {
      if (sectionType === "all") {
        // 全局解析走流式接口，实时显示生成进度
        const resp = await fetch(`${apiBase}/api/resume/parse/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text.trim(), model: selectedModel }),
        });
        if (!resp.ok || !resp.body) {
          let errMsg = `HTTP ${resp.status}`;
          try {
            const err = await resp.json();
            errMsg = extractApiErrorMessage(err, errMsg) || errMsg;
          } catch {
            // 非 JSON 错误体保持 HTTP 状态码
          }
          throw new Error(errMsg);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let resume: any = null;
        let streamErr = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const line = part.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            const payload = line.slice(6).trim();
            if (payload === "[DONE]") continue;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === "progress") setStreamChars(evt.chars || 0);
              else if (evt.type === "json") resume = evt.content;
              else if (evt.type === "error") streamErr = evt.content || "解析失败";
            } catch {
              /* 忽略不完整帧 */
            }
          }
        }

        if (streamErr) throw new Error(streamErr);
        if (!resume) throw new Error("解析结果为空，请重试");
        applyParsedData(resume.resume || resume);
      } else {
        // 分模块解析（非流式）
        const response = await fetch(`${apiBase}/api/resume/parse-section`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text.trim(), section_type: normalizedType, model: selectedModel }),
        });
        if (!response.ok) {
          let errMsg = "解析失败";
          try {
            const err = await response.json();
            errMsg = extractApiErrorMessage(err, errMsg) || errMsg;
          } catch {
            errMsg = `HTTP ${response.status}`;
          }
          throw new Error(errMsg);
        }
        const result = await response.json();
        applyParsedData(result.data || result);
      }
    } catch (err: any) {
      console.error("AI 解析失败:", err);
      toast.error("解析失败: " + err.message);
    } finally {
      setParsing(false);
    }
  };

  const handlePdfUpload = async () => {
    if (!selectedFile) return;
    setParsing(true);
    setParsedData(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("model", selectedModel);

      const response = await fetchWithTimeout(
        `${getApiBaseUrl()}/api/resume/upload-pdf`,
        { method: "POST", body: formData },
        PARSE_TIMEOUT_MS,
      );

      if (!response.ok) {
        let errMsg = "解析失败";
        try {
          const err = await response.json();
          errMsg = extractApiErrorMessage(err, errMsg) || errMsg;
        } catch {
          errMsg = `HTTP ${response.status}`;
        }
        throw new Error(errMsg);
      }

      const result = await response.json();
      applyParsedData(result.resume || result.data || result);
    } catch (err: any) {
      console.error("PDF 解析失败:", err);
      if (err instanceof FetchTimeoutError) {
        toast.error("解析超时，请检查网络后重试，或换一份更小的 PDF");
      } else {
        toast.error("解析失败: " + err.message);
      }
    } finally {
      setParsing(false);
    }
  };

  // 图片上传解析（SSE 流式心跳保活，防止长耗时被网关切断）
  const handleImageUpload = async () => {
    if (!selectedFile) return;
    setParsing(true);
    setParsedData(null);

    try {
      const formData = new FormData();
      formData.append("files", selectedFile);
      if (selectedImage2) formData.append("files", selectedImage2);
      formData.append("model", selectedVisionModel);

      const parsed = await uploadResumeImageStream({
        apiBaseUrl: getApiBaseUrl(),
        formData,
        idleTimeoutMs: PARSE_TIMEOUT_MS,
        maxTotalMs: 300_000,
      });
      applyParsedData(parsed);
    } catch (err: any) {
      console.error("图片解析失败:", err);
      if (err instanceof FetchTimeoutError) {
        toast.error("解析超时，请检查网络后重试，或换一张更清晰的图片");
      } else {
        toast.error("解析失败: " + err.message);
      }
    } finally {
      setParsing(false);
    }
  };

  // 解析完成后的统一处理：全局导入直接填充并关闭，分模块进 results 预览
  const applyParsedData = (data: any) => {
    setParsedData(data);
    if (sectionType === 'all') {
      onSave(data);
      onClose();
    } else {
      setCurrentStep("results");
    }
  };

  // 保存数据
  const handleSave = () => {
    if (parsedData) {
      if (sectionType === 'awards') {
        onSave(parsedData, { awardsListType });
      } else {
        onSave(parsedData);
      }
      onClose();
    }
  };

  const handleCopyJson = async () => {
    if (!parsedData) return;
    const jsonText = JSON.stringify(parsedData, null, 2);
    try {
      await navigator.clipboard.writeText(jsonText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = jsonText;
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      } finally {
        document.body.removeChild(textarea);
      }
    }
  };

  const formatTime = (ms: number) => `${(ms / 1000).toFixed(1)}s`;
  const getTimeColor = (ms: number) => {
    if (ms < 2000) return "text-green-400";
    if (ms < 5000) return "text-yellow-400";
    return "text-red-400";
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "relative w-full transition-all duration-300",
          currentStep === "results" ? "max-w-4xl" : "max-w-2xl",
          "max-h-[90vh] flex flex-col",
          "bg-[#F0F0E8] fresh:bg-white",
          "rounded-none fresh:rounded-xl shadow-[8px_8px_0px_0px_#000000] fresh:shadow-2xl",
          "border-2 border-black fresh:border-slate-200",
          "overflow-hidden",
          "animate-in fade-in-0 zoom-in-95 duration-200",
        )}
      >
        {/* 头部(照搬 Resume-Matcher upload-dialog:纯文字大写标题,无图标方块,关闭按钮极简) */}
        <div className="flex items-center justify-between p-6 border-b-2 border-black fresh:border-slate-200 bg-white dark:bg-[#1C1C1C]">
          <div>
            <h3 className="text-2xl font-serif fresh:font-sans font-bold uppercase fresh:normal-case tracking-tight text-black dark:text-white">
              {parsing
                ? "正在解析内容"
                : currentStep === "results"
                  ? "解析结果预览"
                  : sectionType === "all"
                    ? "导入简历"
                    : `AI 导入 - ${sectionTitle}`}
            </h3>
            <p className="text-sm font-mono fresh:font-sans text-[#878E99] dark:text-neutral-400 mt-0.5">
              {parsing
                ? "AI 正在处理您的请求，请稍候..."
                : currentStep === "results"
                  ? "请检查解析出的数据是否准确，点击下方按钮填充到表单"
                  : sectionType === "all"
                    ? "上传或粘贴简历内容、系统将自动解析并导入"
                    : "粘贴或输入该模块的文本内容：AI 将自动解析并填充"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-black dark:text-white opacity-70 hover:opacity-100 transition-opacity"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-hidden p-6 flex flex-col min-h-[450px]">
          {/* 第一步：输入视图 */}
          {currentStep === "input" && !parsing && (
            <div className="space-y-4 animate-in fade-in duration-300 flex-1 flex flex-col overflow-y-auto custom-scrollbar pr-2">
              {/* 如果已经有解析结果，显示一个提示条 */}
              {parsedData && (
                <div className="mb-4 p-3 rounded-none fresh:rounded-lg bg-white border-2 border-black fresh:border-slate-200 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm flex items-center justify-between animate-in slide-in-from-top-2">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-blue-700 animate-pulse" />
                    <span className="text-sm text-black font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold">
                      已有解析好的数据
                    </span>
                  </div>
                  <button
                    onClick={() => setCurrentStep("results")}
                    className="text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-blue-700 hover:underline flex items-center gap-1"
                  >
                    查看结果
                    <ChevronDown className="w-3 h-3 -rotate-90" />
                  </button>
                </div>
              )}

              {/* 模型选择器 */}
              <div className="relative" ref={dropdownRef}>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <label className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black">
                    选择 AI 模型
                  </label>
                </div>
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowModelDropdown(!showModelDropdown)}
                    className={cn(
                      "w-full px-4 py-3 rounded-none fresh:rounded-lg",
                      "bg-white",
                      "border-2 border-black fresh:border-slate-200 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm",
                      "text-black",
                      "text-left",
                      "focus:outline-none",
                      "transition-all",
                      "flex items-center justify-between",
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-20 h-20 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50 flex items-center justify-center overflow-hidden p-2">
                        {AI_MODELS.find((m) => m.id === selectedModel)?.logoUrl ? (
                          <img
                            src={AI_MODELS.find((m) => m.id === selectedModel)!.logoUrl}
                            alt="DeepSeek"
                            className="w-full h-full object-contain"
                          />
                        ) : (
                          <Wand2 className="w-4 h-4 text-black" />
                        )}
                      </div>
                      <div>
                        <div className="font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal">
                          {AI_MODELS.find((m) => m.id === selectedModel)?.name}
                        </div>
                        <div className="text-xs font-mono fresh:font-sans text-[#878E99]">
                          {
                            AI_MODELS.find((m) => m.id === selectedModel)
                              ?.description
                          }
                        </div>
                      </div>
                    </div>
                    <ChevronDown
                      className={cn(
                        "w-5 h-5 text-black transition-transform",
                        showModelDropdown && "rotate-180",
                      )}
                    />
                  </button>

                  {/* 下拉菜单 */}
                  {showModelDropdown && (
                    <div className="absolute z-10 w-full mt-2 rounded-none fresh:rounded-lg bg-white border-2 border-black fresh:border-slate-200 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-lg overflow-hidden">
                      {AI_MODELS.map((model) => (
                        <button
                          key={model.id}
                          type="button"
                          onClick={() => {
                            setSelectedModel(model.id);
                            setShowModelDropdown(false);
                          }}
                          className={cn(
                            "w-full px-4 py-3 text-left transition-colors",
                            "hover:bg-[#E5E5E0]",
                            selectedModel === model.id &&
                              "bg-[#E5E5E0]",
                          )}
                        >
                          <div className="flex items-center gap-3">
                          <div
                            className={cn(
                              "w-20 h-20 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 flex items-center justify-center overflow-hidden p-2",
                              selectedModel === model.id
                                ? "bg-[#F0F0E8] fresh:bg-slate-50 ring-2 ring-black"
                                : "bg-[#F0F0E8] fresh:bg-slate-50",
                            )}
                          >
                            {"logoUrl" in model && model.logoUrl ? (
                              <img
                                src={model.logoUrl}
                                alt={model.name}
                                className="w-full h-full object-contain"
                              />
                            ) : (
                              <Wand2
                                className={cn(
                                  "w-4 h-4",
                                  selectedModel === model.id
                                    ? "text-blue-700"
                                    : "text-black",
                                )}
                              />
                            )}
                          </div>
                          <div>
                            <div
                            className={cn(
                              "font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal",
                                selectedModel === model.id
                                  ? "text-blue-700"
                                  : "text-black",
                              )}
                            >
                              {model.name}
                            </div>
                              <div className="text-xs font-mono fresh:font-sans text-[#878E99]">
                                {model.description}
                              </div>
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {sectionType === "all" ? (
                <div className="space-y-4 flex-1 flex flex-col">
                  {/* Tab 切换：PDF 上传放第一，图片上传第二，文本粘贴第三 */}
                  <div className="flex gap-2 p-1 flex-shrink-0">
                    <button
                      onClick={() => setImportMode("pdf")}
                      className={cn(
                        "relative flex-1 flex items-center justify-center gap-2 py-2 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold rounded-none fresh:rounded-md border border-black fresh:border-slate-200 transition-all",
                        importMode === "pdf"
                          ? "bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                          : "bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100",
                      )}
                    >
                      <File className="w-4 h-4" />
                      PDF 上传
                      <span className="absolute -top-2 -right-1 px-1.5 py-0.5 text-[9px] font-bold rounded-none fresh:rounded-sm bg-amber-500 text-white border border-black fresh:border-amber-600 leading-none">
                        速度慢
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setImportMode("image");
                      }}
                      className={cn(
                        "relative flex-1 flex items-center justify-center gap-2 py-2 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold rounded-none fresh:rounded-md border border-black fresh:border-slate-200 transition-all",
                        importMode === "image"
                          ? "bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                          : "bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100",
                      )}
                    >
                      <Upload className="w-4 h-4" />
                      图片上传
                      <span className="absolute -top-2 -right-1 px-1.5 py-0.5 text-[9px] font-bold rounded-none fresh:rounded-sm bg-emerald-500 text-white border border-black fresh:border-emerald-600 leading-none">
                        推荐（速度快）
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setImportMode("text");
                      }}
                      className={cn(
                        "flex-1 flex items-center justify-center gap-2 py-2 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold rounded-none fresh:rounded-md border border-black fresh:border-slate-200 transition-all",
                        importMode === "text"
                          ? "bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                          : "bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100",
                      )}
                    >
                      <FileText className="w-4 h-4" />
                      文本粘贴
                    </button>
                  </div>

                  {/* 内容区域 */}
                  <div className="flex-1 flex flex-col min-h-[350px]">
                    {importMode === "pdf" && (
                      <div className="flex-1 flex flex-col space-y-3 rounded-none fresh:rounded-lg border-2 border-black fresh:border-slate-200 bg-white p-4 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black flex-shrink-0">
                          PDF 文件上传
                        </div>
                        <div className="flex-1 min-h-0 overflow-hidden">
                          <FileUploadZone
                            file={selectedFile}
                            onFileSelect={setSelectedFile}
                            acceptTypes={["application/pdf"]}
                            acceptAttr=".pdf"
                            hintLabel="仅支持 PDF"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={handlePdfUpload}
                          disabled={!selectedFile || parsing}
                          className={cn(
                            "w-full rounded-none fresh:rounded-lg px-4 py-2.5 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold flex-shrink-0",
                            "bg-blue-700 text-white border border-black fresh:border-blue-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                            "hover:bg-blue-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                            "active:translate-y-[2px] active:translate-x-[2px]",
                            "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
                            "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                          )}
                        >
                          {parsing ? "解析中..." : "上传解析 PDF"}
                        </button>
                        <p className="text-xs text-[#878E99] text-center flex-shrink-0">
                          由于用的是我自己的 key、速度慢请见谅
                        </p>
                      </div>
                    )}

                    {importMode === "image" && (
                      <div className="flex-1 flex flex-col space-y-3 rounded-none fresh:rounded-lg border-2 border-black fresh:border-slate-200 bg-white p-4 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black flex-shrink-0">
                          图片上传
                        </div>
                        <div className="flex-1 min-h-0 overflow-hidden">
                          <FileUploadZone
                            file={selectedFile}
                            onFileSelect={setSelectedFile}
                            acceptTypes={["image/jpeg", "image/png"]}
                            acceptAttr=".jpg,.jpeg,.png"
                            hintLabel="JPG / PNG"
                          />
                        </div>
                        {selectedFile && (
                          <div className="flex-shrink-0 space-y-1">
                            <div className="text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black">
                              第二张图片（可选，最多 2 张）
                            </div>
                            <FileUploadZone
                              file={selectedImage2}
                              onFileSelect={setSelectedImage2}
                              acceptTypes={["image/jpeg", "image/png"]}
                              acceptAttr=".jpg,.jpeg,.png"
                              hintLabel="JPG / PNG"
                            />
                          </div>
                        )}
                        {VISION_MODELS.length > 1 && (
                        <div className="flex-shrink-0 space-y-2">
                          <div className="text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black">
                          选择识别模型
                          </div>
                          <div className="flex gap-2">
                            {VISION_MODELS.map((m) => (
                              <button
                                key={m.id}
                                type="button"
                                onClick={() => setSelectedVisionModel(m.id)}
                                className={cn(
                                  "flex-1 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 px-3 py-2 text-left text-xs transition-all",
                                  selectedVisionModel === m.id
                                    ? "bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                                    : "bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100",
                                )}
                              >
                                <div className="font-mono fresh:font-sans font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal">
                                  {m.name}
                                </div>
                                <div className="mt-0.5 font-mono fresh:font-sans opacity-80">
                                    {m.description}
                                  </div>
                              </button>
                            ))}
                          </div>
                        </div>
                        )}
                        <button
                          type="button"
                          onClick={handleImageUpload}
                          disabled={!selectedFile || parsing}
                          className={cn(
                            "w-full rounded-none fresh:rounded-lg px-4 py-2.5 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold flex-shrink-0",
                            "bg-blue-700 text-white border border-black fresh:border-blue-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                            "hover:bg-blue-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                            "active:translate-y-[2px] active:translate-x-[2px]",
                            "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
                            "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                          )}
                        >
                          {parsing ? "解析中..." : "识别图片并解析"}
                        </button>
                      </div>
                    )}

                    {importMode === "text" && (
                      <div className="flex-1 flex flex-col space-y-3 rounded-none fresh:rounded-lg border-2 border-black fresh:border-slate-200 bg-white p-4 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black flex-shrink-0">
                          文本粘贴
                        </div>
                        <div className="flex-1 min-h-0 flex flex-col space-y-2 overflow-hidden">
                          <label className="text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-[#878E99] flex-shrink-0">
                            粘贴简历内容（按 Tab 键快速填充示例内容）
                          </label>
                          <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Tab") {
                                const placeholder =
                                  aiImportPlaceholders["all"] || "";
                                if (
                                  placeholder &&
                                  (!text || placeholder.startsWith(text))
                                ) {
                                  e.preventDefault();
                                  setText(placeholder);
                                }
                              }
                            }}
                            placeholder={aiImportPlaceholders["all"] || "请输入文本内容..."}
                            className={cn(
                      "w-full flex-1 p-4 rounded-none fresh:rounded-lg resize-none",
                      "bg-[#F0F0E8] fresh:bg-white",
                      "border-2 border-black fresh:border-slate-200",
                      "text-black text-sm",
                      "placeholder:text-[#878E99]",
                            "outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-0",
                            "transition-all",
                            "font-mono fresh:font-sans",
                          )}
                        />
                          {text && (
                            <div className="text-xs font-mono fresh:font-sans text-[#878E99] flex-shrink-0">
                              字符数: {text.length}
                            </div>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={handleParse}
                          disabled={!text.trim() || parsing}
                          className={cn(
                            "w-full rounded-none fresh:rounded-lg px-4 py-2.5 text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold flex-shrink-0",
                            "bg-blue-700 text-white border border-black fresh:border-blue-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                            "hover:bg-blue-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                            "active:translate-y-[2px] active:translate-x-[2px]",
                            "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
                            "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                          )}
                        >
                          {parsing ? "解析中..." : "AI 解析文本"}
                        </button>
                      </div>
                    )}

                    {/* 赞赏码 */}
                    <div className="flex-shrink-0 flex items-center gap-3 rounded-none fresh:rounded-lg border-2 border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50 p-3 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm">
                      <div className="flex-1 text-xs text-[#878E99] leading-relaxed">
                        <span className="font-bold text-black">支持作者</span>
                        <br />
                        网站用的 AI 都是我自费的 Token、如果觉得有用、可以帮我加一点 Token 🙏
                      </div>
                      <img
                        src="https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com/tip-qr.jpg"
                        alt="赞赏码"
                        onClick={() => setShowTipQr(true)}
                        className="w-20 h-20 object-contain border border-black fresh:border-slate-200 flex-shrink-0 cursor-pointer hover:opacity-80 transition-opacity"
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 flex-1 flex flex-col">
                  {sectionType === 'awards' && (
                    <div className="flex items-center justify-between gap-3 p-3 rounded-none fresh:rounded-lg border-2 border-black fresh:border-slate-200 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-sm bg-white">
                      <div className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black">
                        列表样式
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setAwardsListType('unordered')}
                          className={cn(
                            'px-3 py-1.5 rounded-none fresh:rounded-md text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold border border-black fresh:border-slate-200 transition-colors',
                            awardsListType === 'unordered'
                              ? 'bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm'
                              : 'bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100',
                          )}
                        >
                          无序列表
                        </button>
                        <button
                          type="button"
                          onClick={() => setAwardsListType('ordered')}
                          className={cn(
                            'px-3 py-1.5 rounded-none fresh:rounded-md text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold border border-black fresh:border-slate-200 transition-colors',
                            awardsListType === 'ordered'
                              ? 'bg-blue-700 text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm'
                              : 'bg-[#F0F0E8] fresh:bg-slate-50 text-black hover:bg-[#E5E5E0] fresh:hover:bg-slate-100',
                          )}
                        >
                          有序列表
                        </button>
                      </div>
                    </div>
                  )}
                  <label className="text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold text-black flex-shrink-0">
                    文本内容
                    <span className="text-xs font-mono fresh:font-sans text-[#878E99] ml-2">
                      （按 Tab 键快速填充示例内容）
                    </span>
                  </label>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Tab") {
                        const normalizedType =
                          sectionType === "openSource"
                            ? "opensource"
                            : sectionType === "selfEvaluation"
                              ? "summary"
                              : sectionType;
                        const placeholder =
                          aiImportPlaceholders[normalizedType] || "";
                        if (
                          placeholder &&
                          (!text || placeholder.startsWith(text))
                        ) {
                          e.preventDefault();
                          setText(placeholder);
                        }
                      }
                    }}
                    placeholder={(() => {
                      const normalizedType =
                        sectionType === "openSource"
                          ? "opensource"
                          : sectionType === "selfEvaluation"
                            ? "summary"
                            : sectionType;
                      return (
                        aiImportPlaceholders[normalizedType] || "请输入文本内容..."
                      );
                    })()}
                    className={cn(
                      "w-full flex-1 p-4 rounded-none fresh:rounded-lg resize-none",
                      "bg-[#F0F0E8] fresh:bg-white",
                      "border-2 border-black fresh:border-slate-200",
                      "text-black text-sm",
                      "placeholder:text-[#878E99]",
                            "outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-0",
                            "transition-all",
                            "font-mono fresh:font-sans",
                          )}
                        />
                  {text && (
                    <div className="text-xs font-mono text-[#878E99] flex-shrink-0">
                      字符数: {text.length}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 解析结果预览 */}
          {currentStep === "results" && !parsing && parsedData && (
            <div
              className={cn(
                "flex-1 flex flex-col p-6 rounded-none fresh:rounded-xl overflow-hidden",
                "bg-white",
                "border-2 border-black fresh:border-slate-200 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-lg",
                "animate-in zoom-in-95 duration-300",
              )}
            >
              <div className="flex items-center justify-between gap-2 mb-4 flex-shrink-0">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-green-700 flex items-center justify-center shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm">
                    <span className="text-white text-lg font-bold">✓</span>
                  </div>
                  <div>
                    <span className="text-black text-base font-serif fresh:font-sans font-bold block">
                      解析成功！
                    </span>
                    <span className="text-[#878E99] text-xs font-mono fresh:font-sans">
                      共解析出 {Object.keys(parsedData).length} 个核心数据项
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleCopyJson}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-none fresh:rounded-md px-3 py-1.5 text-xs font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold",
                    "bg-green-700 text-white",
                    "border border-black fresh:border-green-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                    "hover:bg-green-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                    "active:translate-y-[2px] active:translate-x-[2px]",
                    "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                  )}
                >
                  <Copy className="w-3.5 h-3.5" />
                  {copied ? "已复制" : "复制结果"}
                </button>
              </div>
              
              <div className="flex-1 min-h-0 overflow-hidden rounded-none fresh:rounded-lg bg-[#F0F0E8] fresh:bg-slate-50 border-2 border-black fresh:border-slate-200">
                <div className="h-full overflow-auto p-4 custom-scrollbar">
                  <pre className="m-0 text-black text-sm whitespace-pre-wrap break-words font-mono fresh:font-sans leading-relaxed">
                    {JSON.stringify(parsedData, null, 2)}
                  </pre>
                </div>
              </div>

              <div className="mt-4 p-3 rounded-none fresh:rounded-lg bg-[#F0F0E8] fresh:bg-slate-50 border border-black fresh:border-slate-200 text-xs font-mono fresh:font-sans text-black flex items-center gap-2 flex-shrink-0">
                <FileText className="w-3.5 h-3.5" />
                提示：您可以点击右下角的“填充到表单”按钮，将这些数据自动填写到简历编辑器中。
              </div>
            </div>
          )}

          {/* 加载状态 */}
          {parsing && (
            <div className="flex-1 flex flex-col items-center justify-center py-12 px-6 animate-in fade-in duration-300">
              <div className="relative mb-8">
                <div className="w-20 h-20 border-4 border-[#E5E5E0] rounded-full" />
                <div className="absolute inset-0 w-20 h-20 border-4 border-blue-700 border-t-transparent rounded-full animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Wand2 className="w-8 h-8 text-blue-700 animate-pulse" />
                </div>
              </div>

              <div className="text-center space-y-3 max-w-xs">
                <div className="text-2xl font-serif fresh:font-sans font-bold text-black">
                  AI 正在深度解析...
                </div>
                <p className="text-sm font-mono fresh:font-sans text-[#878E99] leading-relaxed">
                  我们的 AI 正在提取关键信息并进行结构化处理 这通常需要 1-2 分钟。
                </p>
              </div>

              <div className="mt-8 w-full max-w-[240px] bg-[#F0F0E8] fresh:bg-slate-50 border border-black fresh:border-slate-200 rounded-none fresh:rounded-full h-2 overflow-hidden">
                <div className="bg-blue-700 h-full w-full animate-pulse" />
              </div>

              <div className={cn(
                "mt-6 px-4 py-1.5 rounded-none fresh:rounded-md text-sm font-mono fresh:font-sans font-bold",
                "bg-white border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                getTimeColor(elapsedTime)
              )}>
                {formatTime(elapsedTime)}
              </div>

              {streamChars > 0 && (
                <div className="mt-2 text-xs font-mono fresh:font-sans text-[#878E99] tabular-nums">
                  已生成 {streamChars} 字…
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-end gap-3 p-6 border-t-2 border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50">
          {currentStep === "input" ? (
            <>
              <button
                onClick={onClose}
                className={cn(
                  "px-4 py-2 rounded-none fresh:rounded-lg text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold",
                  "bg-[#F0F0E8] fresh:bg-white text-black border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                  "hover:bg-[#E5E5E0] fresh:hover:bg-slate-100 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                  "active:translate-y-[2px] active:translate-x-[2px]",
                  "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                )}
              >
                取消
              </button>

              {/* 解析按钮（非全局导入时显示，全局导入时按钮在内容区） */}
              {sectionType !== "all" && (
                <div className="flex items-center gap-2">
                  {parsedData && (
                    <button
                      onClick={() => setCurrentStep("results")}
                      className="px-4 py-2.5 rounded-none fresh:rounded-lg text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold bg-[#E5E5E0] fresh:bg-slate-100 text-black border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm hover:bg-[#D8D8D2] fresh:hover:bg-slate-200 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none active:translate-y-[2px] active:translate-x-[2px] transition-[transform,box-shadow,background-color] duration-100 ease-out"
                    >
                      查看已有结果
                    </button>
                  )}
                  <button
                    onClick={handleParse}
                    disabled={!text.trim() || parsing}
                    className={cn(
                      "px-6 py-2.5 rounded-none fresh:rounded-lg text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold",
                      "bg-blue-700 text-white border border-black fresh:border-blue-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                      "hover:bg-blue-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                      "active:translate-y-[2px] active:translate-x-[2px]",
                      "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
                      "flex items-center gap-2 transition-[transform,box-shadow,background-color] duration-100 ease-out",
                    )}
                  >
                    {parsing ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        解析中...
                      </>
                    ) : (
                      <>
                        <Wand2 className="w-4 h-4" />
                        {parsedData ? "重新解析" : "AI 解析"}
                      </>
                    )}
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <button
                onClick={() => {
                  setCurrentStep("input");
                }}
                className={cn(
                  "px-4 py-2.5 rounded-none fresh:rounded-lg text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold",
                  "bg-[#F0F0E8] fresh:bg-white text-black border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                  "hover:bg-[#E5E5E0] fresh:hover:bg-slate-100 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                  "active:translate-y-[2px] active:translate-x-[2px]",
                  "transition-[transform,box-shadow,background-color] duration-100 ease-out",
                  "flex items-center gap-2",
                )}
              >
                <RotateCcw className="w-4 h-4" />
                返回修改
              </button>
              <button
                onClick={handleSave}
                className={cn(
                  "px-6 py-2.5 rounded-none fresh:rounded-lg text-sm font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal font-bold",
                  "bg-green-700 text-white border border-black fresh:border-green-600 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm",
                  "hover:bg-green-800 hover:translate-y-[1px] hover:translate-x-[1px] fresh:hover:translate-y-0 fresh:hover:translate-x-0 hover:shadow-none",
                  "active:translate-y-[2px] active:translate-x-[2px]",
                  "flex items-center gap-2 transition-[transform,box-shadow,background-color] duration-100 ease-out",
                )}
              >
                <Save className="w-4 h-4" />
                确认并填充
                {finalTime !== null && (
                  <span
                    className={cn(
                      "text-xs font-medium ml-1 opacity-70",
                    )}
                  >
                    ({formatTime(finalTime)})
                  </span>
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 赞赏码放大弹窗 */}
      {showTipQr && (
        <div
          className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70"
          onClick={(e) => {
            e.stopPropagation();
            setShowTipQr(false);
          }}
        >
          <div className="relative max-w-[80vw] max-h-[80vh]">
            <img
              src="https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com/tip-qr.jpg"
              alt="赞赏码"
              className="max-w-full max-h-[80vh] object-contain border-2 border-white shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setShowTipQr(false);
              }}
              className="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-white border-2 border-black flex items-center justify-center font-bold text-black shadow-lg"
              aria-label="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default AIImportModal;
