/**
 * PDF 文档加载 Hook
 * 负责加载 PDF 文档并管理其生命周期
 * 支持移动设备和网络较差环境的重试机制
 */

import { useState, useEffect, useRef } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import { initPDF } from '../pdfWorkerConfig'

// 初始化 PDF 配置
initPDF()

interface UsePDFDocumentResult {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null
  numPages: number
  loading: boolean
  error: string | null
}

const MAX_RETRIES = 3
const RETRY_DELAY = 1000 // 1 秒

export const usePDFDocument = (pdfBlob: Blob | null): UsePDFDocumentResult => {
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 追踪当前加载任务，用于取消
  const loadingTaskRef = useRef<pdfjsLib.PDFDocumentLoadingTask | null>(null)
  const retryCountRef = useRef(0)
  // 当前已渲染的文档；重渲染时保留它直到新文档就绪，避免中途置空导致预览闪烁空白
  const currentDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null)

  useEffect(() => {
    if (!pdfBlob) {
      // 无 PDF：清空并释放当前文档
      if (currentDocRef.current) {
        currentDocRef.current.destroy()
        currentDocRef.current = null
      }
      setPdfDoc(null)
      setNumPages(0)
      setError(null)
      retryCountRef.current = 0
      return
    }

    const loadPDF = async (retryCount = 0) => {
      setLoading(true)
      if (retryCount === 0) {
        setError(null)
      }

      try {
        // 取消之前的加载任务
        if (loadingTaskRef.current) {
          loadingTaskRef.current.destroy()
        }

        const arrayBuffer = await pdfBlob.arrayBuffer()

        // 检查 PDF 文件有效性
        const dataView = new Uint8Array(arrayBuffer)
        if (dataView[0] !== 0x25 || dataView[1] !== 0x50 || dataView[2] !== 0x44 || dataView[3] !== 0x46) {
          throw new Error('Invalid PDF file format')
        }

        const loadingTask = pdfjsLib.getDocument({
          data: arrayBuffer,
          cMapUrl: '/pdfjs/cmaps/',
          cMapPacked: true,
          // 移动设备优化：使用 Range 请求但要求较大的块大小
          rangeChunkSize: 65536,
          disableStream: true, // 禁用流式处理，一次性加载整个文件
          standardFontDataUrl: '/pdfjs/standard_fonts/',
        })

        loadingTaskRef.current = loadingTask

        const doc = await loadingTask.promise

        // 原子换新：先挂上新文档，再延后销毁旧文档，
        // 让旧页面继续显示到新页面渲染完成，消除重渲染时的空白闪烁
        const prevDoc = currentDocRef.current
        currentDocRef.current = doc
        setPdfDoc(doc)
        setNumPages(doc.numPages)
        setError(null)
        retryCountRef.current = 0
        if (prevDoc) {
          window.setTimeout(() => {
            try { prevDoc.destroy() } catch { /* 已销毁忽略 */ }
          }, 600)
        }
      } catch (err) {
        // 忽略取消错误
        if (err instanceof Error && err.message.includes('destroy')) {
          return
        }
        
        console.error('PDF 加载失败:', err)
        
        const errorMessage = err instanceof Error ? err.message : '加载失败'
        
        // 如果还有重试次数，自动重试
        if (retryCount < MAX_RETRIES) {
          console.info(`Retrying PDF load (attempt ${retryCount + 1}/${MAX_RETRIES})`)
          setError(`加载中... (${retryCount + 1}/${MAX_RETRIES})`)
          
          // 延迟后重试
          setTimeout(() => {
            loadPDF(retryCount + 1)
          }, RETRY_DELAY * (retryCount + 1))
        } else {
          // 重试失败，显示错误信息
          setError(`${errorMessage}。请检查网络连接或刷新页面重试。`)
          setLoading(false)
        }
      } finally {
        if (retryCount === MAX_RETRIES || !error) {
          setLoading(false)
        }
      }
    }

    loadPDF()

    return () => {
      if (loadingTaskRef.current) {
        loadingTaskRef.current.destroy()
        loadingTaskRef.current = null
      }
    }
  }, [pdfBlob])

  return { pdfDoc, numPages, loading, error }
}
