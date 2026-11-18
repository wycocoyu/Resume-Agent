import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Download, Copy, Check, ZoomIn, ZoomOut, Maximize2, FileText, Eye, Calendar, RefreshCw, Edit3 } from 'lucide-react'
import { cn } from '../lib/utils'
import { PDFViewerSelector } from '../components/PDFEditor'
import { recordPdfDownload, renderPDFStream } from '../services/api'
import { convertToBackendFormat } from './Workspace/v2/utils/convertToBackend'
import { saveAs } from 'file-saver'
import type { ResumeData } from './Workspace/v2/types'
import { getApiBaseUrl, useRuntimeFeatures } from '@/lib/runtimeEnv'
import { useAuth } from '@/contexts/AuthContext'
import { saveResume, setCurrentResumeId } from '@/services/resumeStorage'
import { toast } from '@/lib/toast'

interface SharedResume {
  success: boolean
  data: ResumeData
  name: string
  expires_at: string
  views: number
}

export default function SharePage() {
  const { shareId } = useParams<{ shareId: string }>()
  const navigate = useNavigate()
  const { isAuthenticated, loading: authLoading, openModal } = useAuth()
  const { authEnabled } = useRuntimeFeatures()
  const [resume, setResume] = useState<SharedResume | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [importing, setImporting] = useState(false)
  const [pdfBlob, setPdfBlob] = useState<Blob | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfProgress, setPdfProgress] = useState('')
  const [zoom, setZoom] = useState(100)

  useEffect(() => {
    const fetchSharedResume = async () => {
      try {
        const response = await fetch(`${getApiBaseUrl()}/api/resume/share/${shareId}`)
        
        if (!response.ok) {
          if (response.status === 404) {
            setError('分享链接不存在或已过期')
          } else {
            setError('获取简历失败')
          }
          return
        }

        const data = await response.json()
        setResume(data)
      } catch (err) {
        console.error('获取分享简历失败:', err)
        setError('获取简历失败，请稍后重试')
      } finally {
        setLoading(false)
      }
    }

    if (shareId) {
      fetchSharedResume()
    }
  }, [shareId])

  // 使用正确的 API 渲染 PDF
  const handleRenderPDF = useCallback(async () => {
    if (!resume?.data) return
    if (authEnabled && !isAuthenticated) {
      setPdfProgress('登录后可预览和下载 PDF')
      openModal('login')
      return
    }
    
    setPdfLoading(true)
    setPdfProgress('正在准备数据...')
    
    try {
      // 使用 convertToBackendFormat 转换数据格式
      const backendData = convertToBackendFormat(resume.data)
      setPdfProgress('正在渲染 PDF...')
      
      // 使用 renderPDFStream 渲染 PDF
      const blob = await renderPDFStream(
        backendData as any,
        backendData.sectionOrder,
        (p) => setPdfProgress(p),
        () => setPdfProgress('渲染完成！'),
        (err) => setPdfProgress(`错误: ${err}`)
      )
      
      setPdfBlob(blob)
      setPdfProgress('')
    } catch (error) {
      console.error('渲染 PDF 失败:', error)
      setPdfProgress(`渲染失败: ${(error as Error).message}`)
    } finally {
      setPdfLoading(false)
    }
  }, [authEnabled, isAuthenticated, openModal, resume?.data])

  // 页面加载时自动渲染 PDF（关闭登录限制时直接匿名预览）
  useEffect(() => {
    if (authLoading) return
    if (authEnabled && !isAuthenticated) {
      setPdfProgress('登录后可预览和下载 PDF')
      return
    }
    if (resume?.data && !pdfBlob && !pdfLoading) {
      const timer = setTimeout(() => {
        handleRenderPDF()
      }, 300)
      return () => clearTimeout(timer)
    }
  }, [authEnabled, authLoading, handleRenderPDF, isAuthenticated, pdfBlob, pdfLoading, resume?.data])

  // 清理文件名：去除首尾空格，将多个连续空格替换为单个空格
  const cleanFileName = (name: string | undefined): string => {
    if (!name) return '简历'
    return name.trim().replace(/\s+/g, ' ')
  }

  const handleDownloadPDF = useCallback(async () => {
    if (!pdfBlob || !resume) return
    
    const name = cleanFileName(resume.name)
    const date = new Date().toISOString().split('T')[0]
    const filename = `${name}_简历_${date}.pdf`
    
    try {
      if (isAuthenticated) {
        await recordPdfDownload()
      }
      const file = new File([pdfBlob], filename, { type: 'application/pdf' })
      saveAs(file, filename)
    } catch (error) {
      setPdfProgress(`下载失败: ${(error as Error).message}`)
    }
  }, [isAuthenticated, pdfBlob, resume])

  const handleImportToWorkspace = useCallback(async () => {
    if (!resume?.data || importing) return
    setImporting(true)
    try {
      const saved = await saveResume(resume.data)
      setCurrentResumeId(saved.id)
      toast.success(
        isAuthenticated ? '已导入工作台并保存到云端' : '已保存到本机浏览器，正在打开工作台'
      )
      navigate(`/workspace/${saved.id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导入工作台失败，请重试')
    } finally {
      setImporting(false)
    }
  }, [importing, isAuthenticated, navigate, resume?.data])

  const handleCopyLink = async () => {
    const currentUrl = window.location.href
    try {
      // 优先使用 Clipboard API
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(currentUrl)
      } else {
        // 备用方案：使用临时文本框
        const textArea = document.createElement('textarea')
        textArea.value = currentUrl
        textArea.style.position = 'fixed'
        textArea.style.left = '-9999px'
        textArea.style.top = '-9999px'
        document.body.appendChild(textArea)
        textArea.focus()
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      console.error('复制失败:', error)
      prompt('请手动复制链接:', currentUrl)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50/50 to-indigo-100 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">正在加载简历...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50/50 to-indigo-100 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950">
        <div className="text-center p-8 bg-white dark:bg-slate-800 rounded-xl shadow-lg border border-slate-200 dark:border-slate-700">
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">出错了</h2>
          <p className="text-slate-600 dark:text-slate-300">{error}</p>
        </div>
      </div>
    )
  }

  if (!resume) {
    return null
  }

  return (
    <div className={cn(
      'w-full h-screen flex flex-col',
      'bg-gradient-to-br from-slate-50 via-blue-50/50 to-indigo-100 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950'
    )}>
      {/* 顶部工具栏 - 居中布局 */}
      <div
        className={cn(
          'flex flex-col items-center justify-center px-6 py-4',
          'bg-white/70 dark:bg-slate-800/70',
          'backdrop-blur-md',
          'border-b border-slate-200/50 dark:border-slate-700/50',
          'shadow-sm'
        )}
      >
        {/* 标题 */}
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">{resume.name}</h1>
        
        {/* 信息和按钮 */}
        <div className="flex items-center gap-4 mt-2">
          <span className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Eye className="w-3.5 h-3.5" />
            {resume.views} 次查看
          </span>
          <span className="text-slate-300 dark:text-slate-600">•</span>
          <span className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Calendar className="w-3.5 h-3.5" />
            到期: {new Date(resume.expires_at).toLocaleDateString()}
          </span>
          <span className="text-slate-300 dark:text-slate-600">•</span>
          
          {/* 复制链接按钮 */}
          <button
            onClick={handleCopyLink}
            className={cn(
              'px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium',
              'transition-all duration-200',
              copied
                ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
            )}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5" />
                已复制
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                复制链接
              </>
            )}
          </button>

          <button
            onClick={handleImportToWorkspace}
            disabled={importing}
            className={cn(
              'px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium',
              'bg-emerald-600 text-white hover:bg-emerald-700',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'transition-all duration-200'
            )}
          >
            <Edit3 className="w-3.5 h-3.5" />
            {importing ? '导入中...' : isAuthenticated ? '导入工作台编辑' : '免登录存本机编辑'}
          </button>

          {authEnabled && !isAuthenticated ? (
            <button
              onClick={() => openModal('login')}
              className={cn(
                'px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium',
                'bg-blue-600 text-white hover:bg-blue-700',
                'transition-all duration-200'
              )}
            >
              登录后下载
            </button>
          ) : !pdfBlob && !pdfLoading ? (
            <button
              onClick={handleRenderPDF}
              className={cn(
                'px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium',
                'bg-blue-600 text-white hover:bg-blue-700',
                'transition-all duration-200'
              )}
            >
              <RefreshCw className="w-3.5 h-3.5" />
              生成 PDF
            </button>
          ) : null}

          {/* 下载 PDF 按钮 */}
          <button
            onClick={handleDownloadPDF}
            disabled={!pdfBlob || pdfLoading}
            className={cn(
              'px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs font-medium',
              'bg-blue-600 text-white',
              'hover:bg-blue-700',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'transition-all duration-200'
            )}
          >
            <Download className="w-3.5 h-3.5" />
            下载 PDF
          </button>
        </div>
      </div>

      {/* PDF 预览区域 - 直接复制 PreviewPanel 的样式 */}
      <div className="flex-1 overflow-auto p-4 bg-slate-100 dark:bg-slate-900/50 flex flex-col">
        {/* 缩放控制 */}
        <div className="flex justify-center mb-4">
          <div className="flex items-center gap-1 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm rounded-xl px-2 py-1 border border-slate-200/50 dark:border-slate-600/50">
            <button
              onClick={() => setZoom(Math.max(50, zoom - 10))}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 transition-colors text-slate-600 dark:text-slate-300"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <span className="text-sm font-medium text-slate-600 dark:text-slate-300 min-w-[4ch] text-center tabular-nums">
              {zoom}%
            </span>
            <button
              onClick={() => setZoom(Math.min(200, zoom + 10))}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 transition-colors text-slate-600 dark:text-slate-300"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <div className="w-px h-5 bg-slate-200 dark:bg-slate-600 mx-1" />
            <button
              onClick={() => setZoom(100)}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 transition-colors text-slate-600 dark:text-slate-300"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* PDF 内容 */}
        <div className="flex-1 overflow-auto flex justify-center">
          {pdfBlob ? (
            <div
              style={{
                width: 'fit-content',
                maxWidth: '100%',
                transform: `scale(${zoom / 100})`,
                transformOrigin: 'top center',
              }}
            >
              <PDFViewerSelector pdfBlob={pdfBlob} scale={1.0} />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                {pdfLoading ? (
                  <>
                    <RefreshCw className="w-12 h-12 mx-auto mb-4 text-blue-500 animate-spin" />
                    <p className="text-lg font-medium text-slate-500 dark:text-slate-400 mb-2">
                      {pdfProgress || '正在生成 PDF 预览...'}
                    </p>
                  </>
                ) : (
                  <>
                    <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-700 dark:to-slate-800 flex items-center justify-center">
                      <FileText className="w-10 h-10 text-slate-400 dark:text-slate-500" />
                    </div>
                    <p className="text-lg font-medium text-slate-500 dark:text-slate-400 mb-2">
                      {pdfProgress || '正在准备 PDF 预览'}
                    </p>
                    <p className="text-sm text-slate-400 dark:text-slate-500">
                      请稍候...
                    </p>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
