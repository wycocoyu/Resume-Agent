import axios from 'axios'
import { extractApiErrorMessage, extractAxiosErrorMessage, readFetchErrorMessage } from '@/lib/apiError'
import { getAuthHeaders } from '@/lib/authHeaders'
import { getApiBaseUrl, getDirectApiBaseUrl } from '@/lib/runtimeEnv'
import type { Resume } from '@/types/resume'
import type { ResumeData } from '@/pages/Workspace/v2/types'
import { DEFAULT_RESUME_TEMPLATE } from '@/data/defaultTemplate'
import type { PDFRenderMode } from './pdfRenderMode'
import {
  PDF_PAYLOAD_BASE64,
  PDF_PAYLOAD_ENCODING_HEADER,
  decodePdfPayload,
  isPdfPayloadEvent,
} from './pdfPayload'

/**
 * PDF 渲染端点。
 *
 * local（工作台预览/下载、Agent 会话预览、分享页、Dashboard 批量下载）走
 * **直连业务主机**而非 auth-web 代理：该端点后端是 get_current_user_optional，
 * 匿名即可渲染，不需要 BetterAuth cookie 中转；而经过代理时整份 PDF（SSE + hex）
 * 要先跨境绕到 auth-web 区域再回源，既慢又容易在流式转发中被缓冲或掐断。
 *
 * remote（仅管理员）必须保留代理：后端 /api/admin/pdf/** 用 require_admin_only，
 * 依赖代理注入的 trusted headers 传递管理员身份。
 */
function getPDFRenderEndpoint(path: '/api/pdf/render' | '/api/pdf/render/stream', mode: PDFRenderMode): string {
  if (mode === 'remote') {
    return `${getApiBaseUrl()}/api/admin/pdf${path.replace('/api/pdf', '')}`
  }
  return `${getDirectApiBaseUrl()}${path}`
}

function parseApiErrorDetail(raw: string): string {
  return extractApiErrorMessage(raw, raw)
}

export { extractApiErrorMessage }

export type UserEntitlement = {
  plan: string
  credits: number
  daily_usage_count: number
  subscription_status: string
}

export async function fetchUserEntitlement(): Promise<UserEntitlement> {
  const { data } = await axios.get(`${getApiBaseUrl()}/api/auth/better/account`, {
    headers: getAuthHeaders(),
  })
  return (data as { entitlement: UserEntitlement }).entitlement
}

export async function mockCheckout(packageName: 'starter' | 'pro'): Promise<UserEntitlement> {
  const { data } = await axios.post(
    `${getApiBaseUrl()}/api/billing/mock-checkout`,
    { package: packageName },
    { headers: getAuthHeaders() },
  )
  return data as UserEntitlement
}

export type PdfDownloadQuota = {
  limit: number | null
  used: number
  remaining: number | null
  unlimited: boolean
}

export async function fetchPdfDownloadQuota(): Promise<PdfDownloadQuota> {
  const { data } = await axios.get(`${getApiBaseUrl()}/api/pdf/quota`, {
    headers: getAuthHeaders(),
  })
  return data as PdfDownloadQuota
}

export async function recordPdfDownload(): Promise<PdfDownloadQuota> {
  try {
    const { data } = await axios.post(
      `${getApiBaseUrl()}/api/pdf/downloads/record`,
      {},
      { headers: getAuthHeaders() },
    )
    return data as PdfDownloadQuota
  } catch (error: any) {
    if (error?.response?.status === 401) {
      throw new Error('请先登录后再下载 PDF')
    }
    if (error?.response?.status === 403) {
      throw new Error(
        extractApiErrorMessage(error?.response?.data, '') || 'PDF 下载次数已达上限（10 次）',
      )
    }
    throw new Error(extractAxiosErrorMessage(error, 'PDF 下载失败'))
  }
}

export async function logPDFRenderModeChange(fromMode: PDFRenderMode, toMode: PDFRenderMode): Promise<void> {
  const url = `${getApiBaseUrl()}/api/admin/pdf/render-mode/log`
  try {
    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        from_mode: fromMode,
        to_mode: toMode,
      }),
    })
  } catch (error) {
    console.warn('[PDF TRACE][render-mode:backend-log-failed]', {
      fromMode,
      toMode,
      error,
    })
  }
}


export async function renderPDF(
  resume: Resume,
  _useDemo: boolean = false,
  sectionOrder?: string[],
  signal?: AbortSignal,
  renderMode: PDFRenderMode = 'local',
): Promise<Blob> {
  const traceId = `pdf-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const mappedOrder = sectionOrder?.map(s => s === 'experience' ? 'internships' : s)
  console.log('[PDF TRACE][renderPDF:start]', {
    traceId,
    renderMode,
    sectionOrder: mappedOrder,
    resumeKeys: Object.keys((resume || {}) as any).slice(0, 20),
  })

  // 使用非流式端点进行简单的PDF渲染
  const url = getPDFRenderEndpoint('/api/pdf/render', renderMode)
  try {
    const { data } = await axios.post(
      url,
      { resume, section_order: mappedOrder },
      {
        responseType: 'blob',
        signal,
        headers: {
          'X-PDF-Trace-Id': traceId,
          'X-PDF-Trace-Source': 'api.renderPDF',
          ...getAuthHeaders(),
        },
      }
    )
    console.log('[PDF TRACE][renderPDF:done]', { traceId, size: (data as Blob).size })
    return data as Blob
  } catch (error: any) {
    let detail = ''
    try {
      const blob = error?.response?.data
      if (blob instanceof Blob) {
        const text = await blob.text()
        detail = parseApiErrorDetail(text)
      } else if (error?.response?.status === 401) {
        detail = '请先登录后再下载 PDF'
      } else if (error?.response?.status === 403) {
        detail = parseApiErrorDetail(JSON.stringify({ detail: error?.response?.data?.detail })) || 'PDF 下载次数已达上限（10 次）'
      } else {
        detail = error?.response?.data?.detail || error?.message || ''
        if (typeof detail !== 'string') {
          detail = parseApiErrorDetail(JSON.stringify({ detail }))
        }
      }
    } catch {
      detail = error?.message || ''
    }
    throw new Error(detail || 'PDF 渲染失败')
  }
}

/**
 * 流式渲染PDF，提供实时进度
 */
export async function renderPDFStream(
  resume: Resume,
  sectionOrder?: string[],
  onProgress?: (progress: string) => void,
  onPdf?: (pdfData: ArrayBuffer) => void,
  onError?: (error: string) => void,
  context?: {
    sessionId?: string
    resumeId?: string
    traceId?: string
    source?: string
    trigger?: string
    signal?: AbortSignal
    renderMode?: PDFRenderMode
  }
): Promise<Blob> {
  const traceId = context?.traceId || `pdfs-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const traceSource = context?.source || 'api.renderPDFStream'
  const traceTrigger = context?.trigger || 'unknown'
  const callerStack = new Error().stack?.split('\n').slice(2, 6).join(' <- ')

  console.log('[PDF TRACE][stream:start]', {
    traceId,
    traceSource,
    traceTrigger,
    renderMode: context?.renderMode || 'local',
    sessionId: context?.sessionId,
    resumeId: context?.resumeId,
    sectionOrder,
    callerStack,
  })

  onProgress?.('开始生成PDF...')

  const url = getPDFRenderEndpoint('/api/pdf/render/stream', context?.renderMode || 'local')
  // 将 experience 映射为 internships（因为数据存在 internships 字段）
  const mappedOrder = sectionOrder?.map(s => s === 'experience' ? 'internships' : s)

  console.log('[PDF TRACE][stream:request]', {
    traceId,
    traceSource,
    traceTrigger,
    url,
    renderMode: context?.renderMode || 'local',
    sessionId: context?.sessionId,
    resumeId: context?.resumeId,
    mappedOrder,
  })

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      ...(context?.sessionId ? { 'X-Agent-Session-Id': context.sessionId } : {}),
      ...(context?.resumeId ? { 'X-Agent-Resume-Id': context.resumeId } : {}),
      'X-PDF-Trace-Id': traceId,
      'X-PDF-Trace-Source': traceSource,
      'X-PDF-Trace-Trigger': traceTrigger,
      // 与后端协商载荷编码：新后端回 base64（体积 4/3），老后端忽略此头仍回 hex。
      // 两种事件前端都能解析，因此前后端任一侧未升级都不会影响出图。
      [PDF_PAYLOAD_ENCODING_HEADER]: PDF_PAYLOAD_BASE64,
      ...getAuthHeaders(),
    },
    signal: context?.signal,
    body: JSON.stringify({ resume, section_order: mappedOrder })
  })

  console.log('[PDF TRACE][stream:response]', {
    traceId,
    status: response.status,
    statusText: response.statusText,
  })

  if (!response.ok) {
    const errorText = await response.text()
    console.error('[PDF TRACE][stream:http-error]', { traceId, errorText })
    if (response.status === 401) {
      throw new Error('请先登录后再下载 PDF')
    }
    if (response.status === 403) {
      throw new Error(parseApiErrorDetail(errorText) || 'PDF 下载次数已达上限（10 次）')
    }
    throw new Error(parseApiErrorDetail(errorText) || `HTTP error! status: ${response.status}`)
  }

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()

  if (!reader) {
    throw new Error('无法获取响应流')
  }

  console.log('[PDF TRACE][stream:read-start]', { traceId })

  let buffer = ''
  let pdfData: Uint8Array | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    console.log('[PDF TRACE][stream:chunk]', { traceId, chunkBytes: chunk.length })
    buffer += chunk

    // SSE格式：事件之间用双换行符分隔（Windows 后端可能产生 \r\n，先统一）
    const events = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n\n')
    buffer = events.pop() || ''  // 保留最后一个可能不完整的事件
    console.log('[PDF TRACE][stream:buffer]', { traceId, events: events.length, bufferLen: buffer.length })

    for (const event of events) {
      // SSE 格式：先解析 event: 行，再解析 data: 行
      const lines = event.split('\n')
      let eventType: string | null = null
      let eventData: string | null = null

      // 先解析 event: 和 data: 行
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          eventData = line.slice(6).trim()
        }
      }

      // 根据事件类型处理数据
      if (eventType && eventData !== null) {
        try {
          if (eventType === 'progress') {
            // progress 事件的 data 是纯字符串
            onProgress?.(eventData)
          } else if (eventType === 'error') {
            // error 事件的 data 是纯字符串
            console.error('[PDF TRACE][stream:event-error]', { traceId, eventData })
            onError?.(eventData)
            throw new Error(eventData)
          } else if (isPdfPayloadEvent(eventType)) {
            // pdf / pdf_b64 事件的 data 是编码后的 PDF 载荷
            console.log('[PDF TRACE][stream:event-pdf]', {
              traceId,
              eventType,
              payloadLen: eventData.length,
            })

            if (!eventData || eventData.length === 0) {
              console.error('[PDF TRACE][stream:pdf-empty]', { traceId })
              throw new Error('PDF数据为空')
            }

            try {
              pdfData = decodePdfPayload(eventType, eventData)
              console.log('[PDF TRACE][stream:pdf-parsed]', {
                traceId,
                eventType,
                bytes: pdfData.length,
              })
            } catch (error) {
              console.error('[PDF TRACE][stream:pdf-parse-failed]', { traceId, eventType, error })
              throw error
            }
          }
        } catch (e) {
          // 如果是 error 事件，重新抛出以便上层处理
          if (eventType === 'error') {
            throw e
          }
          console.error('[PDF TRACE][stream:sse-parse-failed]', { traceId, error: e })
        }
      }
    }
  }

  // 处理缓冲区中剩余的数据（可能是不完整的最后一个事件）
  if (buffer && buffer.length > 0) {
    console.log('[PDF TRACE][stream:tail-buffer]', {
      traceId,
      length: buffer.length,
      preview: buffer.substring(0, 200),
    })

    // 解析剩余缓冲区中的事件（先统一换行符）
    const lines = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
    let eventType: string | null = null
    let eventData: string | null = null

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        eventData = line.slice(6).trim()
      }
    }

    if (eventType === 'error' && eventData) {
      // 处理错误事件
      console.error('[PDF TRACE][stream:tail-error]', { traceId, eventData })
      onError?.(eventData)
      throw new Error(eventData)
    } else if (isPdfPayloadEvent(eventType) && eventData) {
      // 处理PDF事件（hex 或 base64）
      console.log('[PDF TRACE][stream:tail-pdf]', {
        traceId,
        eventType,
        payloadLen: eventData.length,
      })

      try {
        pdfData = decodePdfPayload(eventType, eventData)
        console.log('[PDF TRACE][stream:tail-pdf-parsed]', {
          traceId,
          eventType,
          bytes: pdfData.length,
        })
      } catch (error) {
        console.error('[PDF TRACE][stream:tail-pdf-parse-failed]', { traceId, eventType, error })
        throw error
      }
    } else if (eventType === 'progress' && eventData) {
      // 处理进度事件
      onProgress?.(eventData)
    } else {
      console.log('[PDF TRACE][stream:tail-no-event]', { traceId })
    }
  }

  if (!pdfData) {
    throw new Error('未收到PDF数据')
  }

  console.log('[PDF TRACE][stream:pdf-ready]', { traceId })
  onPdf?.(pdfData.buffer as ArrayBuffer)

  // 创建 blob 返回
  const blob = new Blob([pdfData.buffer as ArrayBuffer], { type: 'application/pdf' })
  console.log('[PDF TRACE][stream:done]', { traceId, blobSize: blob.size })

  return blob
}


/**
 * 流式 AI 改写 - 实时显示生成内容
 */
export async function rewriteResumeStream(
  provider: 'deepseek',
  resume: Resume,
  path: string,
  instruction: string,
  onChunk: (chunk: string) => void,
  onComplete?: () => void,
  onError?: (error: string) => void,
  signal?: AbortSignal,
  history?: { role: string; content: string }[]
) {
  const url = `${getApiBaseUrl()}/api/resume/rewrite/stream`

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, resume, path, instruction, history: history || [] }),
      signal
    })
    
    if (!response.ok) {
      throw new Error(await readFetchErrorMessage(response, `HTTP error! status: ${response.status}`))
    }
    
    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    
    if (!reader) {
      throw new Error('无法获取响应流')
    }
    
    let buffer = ''
    let streamCompleted = false

    // 处理 SSE 消息
    const processLine = (line: string) => {
      if (!line.startsWith('data: ')) return

      const data = line.slice(6).trim()
      if (data === '[DONE]') {
        if (!streamCompleted) {
          streamCompleted = true
          onComplete?.()
        }
        return
      }
      
      try {
        const parsed = JSON.parse(data)
        if (parsed.content) {
          // 立即调用回调，触发 UI 更新
          onChunk(parsed.content)
        }
        if (parsed.error) {
          onError?.(extractApiErrorMessage(parsed.error, 'AI 处理失败'))
          return
        }
      } catch {
        // 忽略 JSON 解析错误
      }
    }
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      
      // SSE 消息以 \n\n 分隔，处理完整的消息
      const messages = buffer.split('\n\n')
      // 最后一个可能是不完整的，保留在 buffer 中
      buffer = messages.pop() || ''
      
      // 处理每个完整的消息
      for (const message of messages) {
        const lines = message.split('\n')
        for (const line of lines) {
          processLine(line)
        }
      }
    }
    
    // 处理剩余的 buffer
    if (buffer.trim()) {
      const lines = buffer.split('\n')
      for (const line of lines) {
        processLine(line)
      }
    }
    
    if (!streamCompleted) {
      onComplete?.()
    }
  } catch (error) {
    onError?.(error instanceof Error ? error.message : '流式请求失败')
  }
}


/**
 * 获取默认简历模板
 *
 * 使用前端内嵌的模板，不依赖后端
 * 用户数据保存在浏览器 localStorage 中
 */
export function getDefaultTemplate(): ResumeData {
  return structuredClone(DEFAULT_RESUME_TEMPLATE)
}

/**
 * 编译 LaTeX 源代码为 PDF（流式）
 * 使用 slager 原版样式，与 slager.link 完全一致
 */
export async function compileLatexStream(
  latexContent: string,
  onProgress?: (progress: string) => void,
  onPdf?: (pdfData: ArrayBuffer) => void,
  onError?: (error: string) => void
): Promise<Blob> {
  console.log('[API] 开始编译 LaTeX，内容长度:', latexContent.length)
  
  onProgress?.('开始编译 LaTeX...')
  
  const url = `${getApiBaseUrl()}/api/pdf/compile-latex/stream`
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ latex_content: latexContent })
  })
  
  if (!response.ok) {
    const errorText = await response.text()
    if (response.status === 401) {
      throw new Error('请先登录后再下载 PDF')
    }
    if (response.status === 403) {
      throw new Error(parseApiErrorDetail(errorText) || 'PDF 下载次数已达上限（10 次）')
    }
    throw new Error(parseApiErrorDetail(errorText) || `HTTP error! status: ${response.status}`)
  }
  
  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  
  if (!reader) {
    throw new Error('无法获取响应流')
  }
  
  let buffer = ''
  let pdfData: Uint8Array | null = null
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    const chunk = decoder.decode(value, { stream: true })
    buffer += chunk
    
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    
    for (const event of events) {
      const lines = event.split('\n')
      let eventType: string | null = null
      let eventData: string | null = null

      // 先解析 event: 和 data: 行
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          eventData = line.slice(6).trim()
        }
      }

      // 根据事件类型处理数据
      if (eventType && eventData !== null) {
        try {
          if (eventType === 'progress') {
            // progress 事件的 data 是纯字符串
            onProgress?.(eventData)
          } else if (eventType === 'error') {
            // error 事件的 data 是纯字符串
            console.error('[API] 收到错误事件:', eventData)
            onError?.(eventData)
            throw new Error(eventData)
          } else if (eventType === 'pdf') {
            // pdf 事件的 data 是十六进制字符串
            const hexData = eventData
            console.log('[API] 收到 PDF 数据，长度:', hexData?.length || 0)
            
            const normalizedHex = hexData.length % 2 === 0 ? hexData : '0' + hexData
            const matches = normalizedHex.match(/.{2}/g)
            if (matches) {
              pdfData = new Uint8Array(matches.map((byte: string) => parseInt(byte, 16)))
            }
          }
        } catch (e) {
          // 如果是 error 事件，重新抛出以便上层处理
          if (eventType === 'error') {
            throw e
          }
          console.error('解析 SSE 数据失败:', e)
        }
      }
    }
  }
  
  // 处理剩余缓冲区
  if (buffer && !pdfData) {
    const lines = buffer.split('\n')
    let eventType: string | null = null
    let eventData: string | null = null

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        eventData = line.slice(6).trim()
      }
    }

    if (eventType === 'error' && eventData) {
      console.error('[API] 收到错误事件:', eventData)
      onError?.(eventData)
      throw new Error(eventData)
    } else if (eventType === 'pdf' && eventData) {
      const hexData = eventData
      const normalizedHex = hexData.length % 2 === 0 ? hexData : '0' + hexData
      const matches = normalizedHex.match(/.{2}/g)
      if (matches) {
        pdfData = new Uint8Array(matches.map((byte: string) => parseInt(byte, 16)))
      }
    } else if (eventType === 'progress' && eventData) {
      onProgress?.(eventData)
    }
  }
  
  if (!pdfData) {
    throw new Error('未收到 PDF 数据')
  }
  
  onPdf?.(pdfData.buffer as ArrayBuffer)
  
  const blob = new Blob([pdfData.buffer as ArrayBuffer], { type: 'application/pdf' })
  console.log('[API] LaTeX 编译完成，PDF 大小:', blob.size, '字节')

  return blob
}

/**
 * 划词改写流式接口 — 直接对文本片段进行 AI 改写
 * 不需要完整 resume，只传选中文本 + 指令
 */
export async function rewriteTextStream(
  text: string,
  instruction: string,
  path: string,
  onChunk: (chunk: string) => void,
  onComplete?: () => void,
  onError?: (error: string) => void,
  signal?: AbortSignal,
) {
  const url = `${getApiBaseUrl()}/api/resume/rewrite-text/stream`

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'deepseek',
        text,
        instruction,
        path,
        locale: 'zh',
      }),
      signal,
    })

    if (!response.ok) {
      throw new Error(await readFetchErrorMessage(response, `HTTP error! status: ${response.status}`))
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()

    if (!reader) {
      throw new Error('无法获取响应流')
    }

    let buffer = ''

    const processLine = (line: string) => {
      if (!line.startsWith('data: ')) return

      const data = line.slice(6).trim()
      if (data === '[DONE]') {
        onComplete?.()
        return
      }

      try {
        const parsed = JSON.parse(data)
        if (parsed.error) {
          onError?.(extractApiErrorMessage(parsed.error, 'AI 处理失败'))
          return
        }
        if (parsed.content) {
          onChunk(parsed.content)
        }
      } catch {
        // ignore parse errors
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const messages = buffer.split('\n\n')
      buffer = messages.pop() || ''

      for (const message of messages) {
        const lines = message.split('\n')
        for (const line of lines) {
          processLine(line)
        }
      }
    }

    if (buffer.trim()) {
      const lines = buffer.split('\n')
      for (const line of lines) {
        processLine(line)
      }
    }

    onComplete?.()
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    onError?.(error instanceof Error ? error.message : '划词改写失败')
  }
}

export interface ChatStreamMessage {
  role: 'user' | 'assistant'
  content: string
}

/** 轻量简历问答（流式）—— 供右下角悬浮 AI 助手对话窗口使用 */
export async function chatStream(
  messages: ChatStreamMessage[],
  resumeContext: string,
  onChunk: (chunk: string) => void,
  onComplete?: () => void,
  onError?: (error: string) => void,
  signal?: AbortSignal,
) {
  const url = `${getApiBaseUrl()}/api/resume/chat/stream`

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'deepseek',
        messages,
        resume_context: resumeContext,
        locale: 'zh',
      }),
      signal,
    })

    if (!response.ok) {
      throw new Error(await readFetchErrorMessage(response, `HTTP error! status: ${response.status}`))
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()

    if (!reader) {
      throw new Error('无法获取响应流')
    }

    let buffer = ''
    let completed = false
    const finish = () => {
      if (completed) return
      completed = true
      onComplete?.()
    }

    const processLine = (line: string) => {
      if (!line.startsWith('data: ')) return
      const data = line.slice(6).trim()
      if (data === '[DONE]') {
        finish()
        return
      }
      try {
        const parsed = JSON.parse(data)
        if (parsed.error) {
          onError?.(extractApiErrorMessage(parsed.error, 'AI 处理失败'))
          return
        }
        if (parsed.content) {
          onChunk(parsed.content)
        }
      } catch {
        // ignore parse errors
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const events = buffer.split('\n\n')
      buffer = events.pop() || ''

      for (const event of events) {
        for (const line of event.split('\n')) {
          processLine(line)
        }
      }
    }

    if (buffer.trim()) {
      for (const line of buffer.split('\n')) {
        processLine(line)
      }
    }

    finish()
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    onError?.(error instanceof Error ? error.message : '对话失败')
  }
}

async function postAiJson<T>(
  url: string,
  payload: unknown,
  fallbackError: string,
  headers?: Record<string, string>,
): Promise<T> {
  try {
    const { data } = await axios.post(url, payload, headers ? { headers } : undefined)
    return data as T
  } catch (error) {
    throw new Error(extractAxiosErrorMessage(error, fallbackError))
  }
}

export type RewriteTextIntent = 'full_bold' | 'selective_bold' | 'remove_bold' | 'list_transform' | 'rewrite'

export async function detectRewriteTextIntent(
  text: string,
  instruction: string,
  path: string,
): Promise<{ intent: RewriteTextIntent; intents?: RewriteTextIntent[]; confidence: number; source?: string }> {
  const url = `${getApiBaseUrl()}/api/resume/rewrite-text/intent`
  return postAiJson(
    url,
    {
      provider: 'deepseek',
      text,
      instruction,
      path,
      locale: 'zh',
    },
    '改写意图识别失败，请稍后重试',
  )
}

export type GrammarIssueType = 'grammar' | 'wording' | 'vague' | 'quantify'

export interface GrammarIssue {
  original: string
  suggestion: string
  type: GrammarIssueType
  severity: 'high' | 'medium' | 'low'
}

export interface GrammarCheckResult {
  issues: GrammarIssue[]
  summary: string
  score: number | null
}

/** 单字段语法/表达体检：返回结构化 issues + 评分（非流式） */
export async function grammarCheckField(text: string, path: string): Promise<GrammarCheckResult> {
  const url = `${getApiBaseUrl()}/api/resume/grammar-check`
  return postAiJson<GrammarCheckResult>(
    url,
    {
      provider: 'deepseek',
      text,
      path,
      locale: 'zh',
    },
    '语法体检失败，请稍后重试',
  )
}

export interface JdOptimizeField {
  key: string
  label: string
  content: string
}

export interface JdSuggestion {
  key: string
  original: string
  suggested: string
  reason: string
}

export interface JdAtsCheckItem {
  item: string
  /** pass=达标 fail=不达标需改 template=由 LaTeX 模板天然保证 */
  status: 'pass' | 'fail' | 'template'
  note: string
}

export interface JdOptimizeResult {
  matchScore: number | null
  atsScore: number | null
  keywordMatches: string[]
  missingKeywords: string[]
  atsChecklist?: JdAtsCheckItem[]
  suggestions: JdSuggestion[]
}

/** 针对 JD 的多字段优化建议（非流式，结构化） */
export async function jdOptimize(fields: JdOptimizeField[], jdText: string): Promise<JdOptimizeResult> {
  const url = `${getApiBaseUrl()}/api/resume/jd-optimize`
  return postAiJson<JdOptimizeResult>(
    url,
    {
      provider: 'deepseek',
      jd_text: jdText,
      fields,
      locale: 'zh',
    },
    'JD 优化分析失败，请稍后重试',
  )
}

export type JdKeywordIntegrateResult =
  | { integrated: false; keyword: string }
  | { integrated: true; keyword: string; key: string; original: string; suggested: string; reason: string }

/** 把某个 JD 缺失关键词自然融入最相关的字段，返回可确定性替换的 original/suggested */
export async function jdIntegrateKeyword(
  keyword: string,
  fields: JdOptimizeField[],
  jdText: string,
): Promise<JdKeywordIntegrateResult> {
  const url = `${getApiBaseUrl()}/api/resume/jd-keyword-integrate`
  return postAiJson<JdKeywordIntegrateResult>(
    url,
    {
      provider: 'deepseek',
      keyword,
      jd_text: jdText,
      fields,
      locale: 'zh',
    },
    '关键词融入失败，请稍后重试',
  )
}

export interface TranslationItem {
  key: string
  original: string
  translated: string
}

export interface TranslateResult {
  translations: TranslationItem[]
}

/** 简历多字段翻译：逐字段返回 original/translated（非流式，结构化） */
export async function translateResume(fields: JdOptimizeField[], targetLang: string): Promise<TranslateResult> {
  const url = `${getApiBaseUrl()}/api/resume/translate`
  return postAiJson<TranslateResult>(
    url,
    {
      provider: 'deepseek',
      target_lang: targetLang,
      fields,
      locale: 'zh',
    },
    '简历翻译失败，请稍后重试',
  )
}

export interface HealthDimension {
  dimension: string
  score: number | null
  comment: string
}

export interface HealthCheckResult {
  overallScore: number | null
  dimensions: HealthDimension[]
  suggestions: JdSuggestion[]
  summary: string
}

/** 通用简历体检（无需 JD）：维度评分 + 逐条可应用建议（非流式，结构化） */
export async function healthCheck(fields: JdOptimizeField[]): Promise<HealthCheckResult> {
  const url = `${getApiBaseUrl()}/api/resume/health-check`
  return postAiJson<HealthCheckResult>(
    url,
    {
      provider: 'deepseek',
      fields,
      locale: 'zh',
    },
    '简历体检失败，请稍后重试',
  )
}

export const scoreResume = async (
  resumeId: string | null,
  jdText: string,
  resumeData?: unknown,
): Promise<any> => {
  return postAiJson(
    `${getApiBaseUrl()}/api/resume/score`,
    {
      ...(resumeId ? { resume_id: resumeId } : {}),
      jd_text: jdText,
      ...(resumeData !== undefined ? { resume_data: resumeData } : {}),
    },
    '简历评分失败，请稍后重试',
    {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
  )
}
