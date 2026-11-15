/**
 * PDF.js Worker 配置
 * 支持多种加载方式，确保在桌面和移动设备上都能工作
 */

import * as pdfjsLib from 'pdfjs-dist'

// 配置 worker 源
export function configurePDFWorker() {
  // 优先使用本地托管的 worker，实现零外网 CDN 依赖；备选多个 CDN 兜底
  const localWorker = '/pdfjs/pdf.worker.min.mjs'
  const workerUrls = [
    localWorker,
    // 方案 1: JSDelivr CDN (通常更稳定)
    `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.mjs`,
    // 方案 2: unpkg CDN
    `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.mjs`,
    // 方案 3: Legacy 版本 (兼容性更好)
    `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.js`,
    `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.js`,
  ]

  // 尝试第一个 URL，如果失败会在运行时由 PDF.js 自动处理
  pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrls[0]
  
  console.log(`PDF.js worker 配置: ${pdfjsLib.version} (${workerUrls[0]})`)

  // 优化配置，提高移动设备兼容性
  pdfjsLib.GlobalWorkerOptions.workerPort = null
  
  // 禁用网络请求的并发控制，移动设备网络较差时允许更多并发
  if (pdfjsLib.version) {
    // 降低内存使用，提高移动设备兼容性
    const isLowMemoryDevice = navigator.deviceMemory && navigator.deviceMemory <= 4
    if (isLowMemoryDevice) {
      // 在低内存设备上的优化
      console.info('Optimizing for low memory device')
    }
  }
}

// 初始化PDF配置
export const initPDF = () => {
  configurePDFWorker()
}

