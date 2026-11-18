import { toast } from '@/lib/toast'
/**
 * 导出按钮 + 导出格式弹窗
 * 点「导出」弹出格式选择（PDF / JSON），选中后统一从底部「导出」执行。
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Download, FileJson, FileText, Globe, X } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import {
  fetchPdfDownloadQuota,
  recordPdfDownload,
  type PdfDownloadQuota,
} from "@/services/api";
import { generateHTML } from "../utils/generateHTML";

type ExportFormat = "pdf" | "json" | "html";

interface ExportButtonProps {
  resumeData: Record<string, any>;
  resumeName?: string;
  onExportJSON?: () => void;
  pdfBlob?: Blob | null;
  onDownloadPDF?: () => void | Promise<void>;
}

export function ExportButton({
  resumeData,
  resumeName = "我的简历",
  onExportJSON,
  pdfBlob,
  onDownloadPDF,
}: ExportButtonProps) {
  const { isAuthenticated } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [quota, setQuota] = useState<PdfDownloadQuota | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  const isHtmlTemplate = resumeData?.templateType === "html";
  const [format, setFormat] = useState<ExportFormat>("pdf");

  const getPdfFileName = () => {
    const safeName = (resumeName || "简历")
      .trim()
      .replace(/[\\/:*?"<>|]/g, "_")
      .replace(/\s+/g, " ");
    const name = safeName || "简历";
    const date = new Date().toISOString().split("T")[0];
    return `${name}_简历_${date}.pdf`;
  };

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const refreshQuota = async () => {
    if (!isAuthenticated) {
      setQuotaLoading(false);
      setQuotaError(null);
      setQuota({ unlimited: true, limit: null, used: 0, remaining: null });
      return;
    }
    setQuotaLoading(true);
    setQuotaError(null);
    try {
      setQuota(await fetchPdfDownloadQuota());
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法读取下载额度";
      setQuotaError(message);
    } finally {
      setQuotaLoading(false);
    }
  };

  const getQuotaText = () => {
    if (quotaLoading) return "正在读取下载额度";
    if (quotaError) return "下载额度读取失败";
    if (!quota) return "下载次数额度";
    if (quota.unlimited) return "下载不限次数";
    return `剩余 ${quota.remaining ?? 0}/${quota.limit ?? 10} 次下载`;
  };

  const quotaIsExhausted = Boolean(
    quota && !quota.unlimited && (quota.remaining ?? 0) <= 0,
  );

  // 导出 PDF：LaTeX 模板走后端渲染好的 pdfBlob（占下载额度）；HTML 模板走前端导出（onDownloadPDF，不占额度）
  const exportPdf = async () => {
    if (!isHtmlTemplate && !pdfBlob) {
      toast.error('请先点击"渲染 PDF"按钮生成 PDF，然后再下载');
      return;
    }
    setIsOpen(false);
    try {
      if (onDownloadPDF) {
        await onDownloadPDF();
      } else if (pdfBlob) {
        if (isAuthenticated) {
          await recordPdfDownload();
        }
        downloadBlob(pdfBlob, getPdfFileName());
      }
      if (!isHtmlTemplate && isAuthenticated) void refreshQuota();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "PDF 下载失败，请重试");
    }
  };

  // 导出 JSON（结构化简历数据，本地生成不耗下载额度）
  const exportJson = () => {
    setIsOpen(false);
    if (onExportJSON) {
      onExportJSON();
      return;
    }
    try {
      const jsonString = JSON.stringify(resumeData, null, 2);
      const blob = new Blob([jsonString], { type: "application/json" });
      downloadBlob(
        blob,
        `${resumeName}-${new Date().toISOString().split("T")[0]}.json`,
      );
    } catch (error) {
      console.error("导出 JSON 失败:", error);
      toast.error("导出失败，请重试");
    }
  };

  // 导出 HTML（自包含、零网络依赖可编辑文件，本地生成不耗下载额度）
  const exportHtml = () => {
    setIsOpen(false);
    try {
      const htmlContent = generateHTML(
        resumeData as any,
        resumeData?.templateId || "asu-tech",
        { editable: true, autoOnePage: true }
      );
      const blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
      const safeName =
        (resumeName || "简历")
          .trim()
          .replace(/[\\/:*?"<>|]/g, "_")
          .replace(/\s+/g, " ") || "简历";
      const date = new Date().toISOString().split("T")[0];
      downloadBlob(blob, `${safeName}_简历_${date}.html`);
      toast.success("已导出自包含可编辑 HTML 文件");
    } catch (error) {
      console.error("导出 HTML 失败:", error);
      toast.error("导出 HTML 失败，请重试");
    }
  };

  const handleExport = () => {
    if (format === "pdf") void exportPdf();
    else if (format === "html") exportHtml();
    else exportJson();
  };

  useEffect(() => {
    if (isOpen) {
      setFormat("pdf");
      if (!isHtmlTemplate) void refreshQuota();
    }
  }, [isOpen, isHtmlTemplate, isAuthenticated]);

  const formatCardClass = (active: boolean) =>
    cn(
      'flex flex-col items-center gap-2 p-4 text-center transition-[transform,box-shadow,background-color] duration-100',
      'border-2 fresh:border border-black fresh:border-slate-200 dark:border-white',
      active
        ? 'bg-[#D4E4FF] shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:bg-[#1a2a4a] dark:shadow-[2px_2px_0px_0px_#ffffff]'
        : 'bg-[#F0F0E8] fresh:bg-slate-50 hover:translate-y-[1px] fresh:hover:translate-y-0 hover:translate-x-[1px] fresh:hover:translate-x-0 hover:shadow-none fresh:hover:shadow-sm dark:bg-[#2A2A2A] dark:hover:bg-[#3A3A3A]',
    );

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          'inline-flex items-center justify-center gap-2',
          'whitespace-nowrap text-sm font-medium font-mono fresh:font-sans uppercase fresh:normal-case tracking-wide fresh:tracking-normal',
          'transition-[transform,box-shadow,background-color] duration-100 ease-out',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2',
          'disabled:opacity-50',
          'rounded-none fresh:rounded-md h-9 px-5',
          'border border-black fresh:border-slate-200 dark:border-white',
          'shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm dark:shadow-[2px_2px_0px_0px_#ffffff]',
          'bg-blue-700 text-white',
          'hover:bg-blue-800 hover:translate-y-[1px] fresh:hover:translate-y-0 hover:translate-x-[1px] fresh:hover:translate-x-0 hover:shadow-none fresh:hover:shadow-sm',
        )}
      >
        <Download className="w-4 h-4" strokeWidth={3} />
        <span>导出</span>
      </button>

      {isOpen && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
          onClick={(e) => e.target === e.currentTarget && setIsOpen(false)}
        >
          <div className="w-full max-w-md border-2 fresh:border border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50 p-5 shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md dark:border-white dark:bg-[#2A2A2A] dark:shadow-[4px_4px_0px_0px_#ffffff]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-mono fresh:font-sans text-sm font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black dark:text-white">
                  导出简历
                </h3>
                <p className="mt-0.5 font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
                  选择导出格式下载简历
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50 p-1.5 text-black shadow-[1px_1px_0px_0px_#000000] transition-colors hover:bg-[#E5E5E0] hover:translate-y-[1px] fresh:hover:translate-y-0 hover:translate-x-[1px] fresh:hover:translate-x-0 hover:shadow-none fresh:hover:shadow-sm dark:border-white dark:bg-[#2A2A2A] dark:text-white dark:shadow-[1px_1px_0px_0px_#ffffff] dark:hover:bg-[#3A3A3A]"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 grid gap-3 grid-cols-3">
              <button
                type="button"
                onClick={() => setFormat("pdf")}
                className={formatCardClass(format === "pdf")}
              >
                <span
                  className={cn(
                    "flex h-11 w-11 items-center justify-center",
                    format === "pdf"
                      ? "bg-blue-700 text-white border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                      : "bg-[#F0F0E8] fresh:bg-slate-50 text-black border border-black fresh:border-slate-200 shadow-[1px_1px_0px_0px_#000000] dark:bg-[#2A2A2A] dark:text-white dark:border-white dark:shadow-[1px_1px_0px_0px_#ffffff]",
                  )}
                >
                  <FileText className="h-5 w-5" strokeWidth={2} />
                </span>
                <span className="font-mono fresh:font-sans text-xs font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black dark:text-white">
                  PDF
                </span>
                <span className="font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
                  可打印文档
                </span>
                <span
                  className={cn(
                    "font-mono fresh:font-sans text-[10px]",
                    !isHtmlTemplate && quotaIsExhausted
                      ? "text-red-600"
                      : "text-[#878E99] dark:text-neutral-400",
                  )}
                >
                  {isHtmlTemplate
                    ? "前端实时导出，不占下载额度"
                    : !pdfBlob
                      ? "需要先渲染 PDF"
                      : getQuotaText()}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setFormat("html")}
                className={formatCardClass(format === "html")}
              >
                <span
                  className={cn(
                    "flex h-11 w-11 items-center justify-center",
                    format === "html"
                      ? "bg-blue-700 text-white border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                      : "bg-[#F0F0E8] fresh:bg-slate-50 text-black border border-black fresh:border-slate-200 shadow-[1px_1px_0px_0px_#000000] dark:bg-[#2A2A2A] dark:text-white dark:border-white dark:shadow-[1px_1px_0px_0px_#ffffff]",
                  )}
                >
                  <Globe className="h-5 w-5" strokeWidth={2} />
                </span>
                <span className="font-mono fresh:font-sans text-xs font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black dark:text-white">
                  HTML
                </span>
                <span className="font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
                  自包含可编辑
                </span>
                <span className="font-mono fresh:font-sans text-[10px] text-emerald-600 dark:text-emerald-400">
                  零网络依赖·自带工具栏
                </span>
              </button>

              <button
                type="button"
                onClick={() => setFormat("json")}
                className={formatCardClass(format === "json")}
              >
                <span
                  className={cn(
                    "flex h-11 w-11 items-center justify-center",
                    format === "json"
                      ? "bg-blue-700 text-white border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
                      : "bg-[#F0F0E8] fresh:bg-slate-50 text-black border border-black fresh:border-slate-200 shadow-[1px_1px_0px_0px_#000000] dark:bg-[#2A2A2A] dark:text-white dark:border-white dark:shadow-[1px_1px_0px_0px_#ffffff]",
                  )}
                >
                  <FileJson className="h-5 w-5" strokeWidth={2} />
                </span>
                <span className="font-mono fresh:font-sans text-xs font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black dark:text-white">
                  JSON
                </span>
                <span className="font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
                  结构化数据
                </span>
                <span className="font-mono fresh:font-sans text-[10px] text-[#878E99] dark:text-neutral-400">
                  可再次导入编辑
                </span>
              </button>
            </div>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-[#F0F0E8] fresh:bg-slate-50 px-4 py-2 font-mono fresh:font-sans text-xs font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-black shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm transition-colors hover:bg-[#E5E5E0] hover:translate-y-[1px] fresh:hover:translate-y-0 hover:translate-x-[1px] fresh:hover:translate-x-0 hover:shadow-none fresh:hover:shadow-sm dark:border-white dark:bg-[#2A2A2A] dark:text-white dark:shadow-[2px_2px_0px_0px_#ffffff] dark:hover:bg-[#3A3A3A]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleExport}
                className="rounded-none fresh:rounded-md border border-black fresh:border-slate-200 bg-blue-700 px-5 py-2 font-mono fresh:font-sans text-xs font-bold uppercase fresh:normal-case tracking-wide fresh:tracking-normal text-white shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm transition-colors hover:bg-blue-800 hover:translate-y-[1px] fresh:hover:translate-y-0 hover:translate-x-[1px] fresh:hover:translate-x-0 hover:shadow-none fresh:hover:shadow-sm dark:border-white dark:shadow-[2px_2px_0px_0px_#ffffff]"
              >
                导出
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
