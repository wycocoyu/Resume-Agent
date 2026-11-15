/**
 * 3-Tier 渐进式「自动一页」高度自适应算法
 * 规范实现：Issue #46
 * 
 * 压缩梯度：
 * Tier 0: 原高未超标 (无需调整)
 * Tier 1: 间距压缩 (微调 section-gap, item-gap, page-padding) - 零字号字距损失
 * Tier 2: 行高压缩 (微调 line-height 与段间距) - 保持字号完全不变
 * Tier 3: 整体缩放 (Transform Scale 兜底，带 minScale 0.82 下限) - 保底不被裁切
 */

export interface AutoFitOptions {
  targetHeight?: number // 默认 1122.5px (A4 96 DPI 标准高度: 297mm * 96 / 25.4)
  tolerance?: number // 容差高度 (默认 1.5px，适配打印与子像素舍入)
  minSpacingFactor?: number // 间距压缩下限，默认 0.45
  minLineHeight?: number // 行高压缩下限，默认 1.22
  minScale?: number // 缩放保底阈值，默认 0.82
  containerSelector?: string // 容器类选择器，默认 .html-template-container
}

export interface AutoFitResult {
  fitted: boolean
  tier: 0 | 1 | 2 | 3
  appliedValues: {
    spacingFactor: number
    lineHeight: number
    scale: number
  }
  originalHeight: number
  finalHeight: number
  overflowRatio: number
}

export const A4_TARGET_HEIGHT_PX = 1122.5

export function autoFitToOnePage(
  container?: HTMLElement | null,
  options?: AutoFitOptions | number
): AutoFitResult {
  if (!container) {
    return {
      fitted: true,
      tier: 0,
      appliedValues: { spacingFactor: 1.0, lineHeight: 1.5, scale: 1.0 },
      originalHeight: 0,
      finalHeight: 0,
      overflowRatio: 0,
    }
  }

  const opts: AutoFitOptions = typeof options === 'number'
    ? { targetHeight: options }
    : options || {}

  const targetHeight = opts.targetHeight || A4_TARGET_HEIGHT_PX
  const tolerance = opts.tolerance ?? 1.5
  const minSpacing = opts.minSpacingFactor ?? 0.45
  const minLineHeight = opts.minLineHeight ?? 1.22
  const minScale = opts.minScale ?? 0.82

  // 先重置历史自适应样式，获取真实原始高度
  resetAutoFit(container)

  const originalHeight = container.scrollHeight || container.offsetHeight || 0
  const overflowRatio = targetHeight > 0 ? originalHeight / targetHeight : 1

  // Tier 0: 未超高（含容差边界），直接返回
  if (originalHeight <= targetHeight + tolerance || originalHeight === 0) {
    return {
      fitted: true,
      tier: 0,
      appliedValues: { spacingFactor: 1.0, lineHeight: 1.5, scale: 1.0 },
      originalHeight,
      finalHeight: originalHeight,
      overflowRatio,
    }
  }

  // Tier 1: 间距微调阶梯
  const spacingSteps = [0.85, 0.70, 0.55, minSpacing]
  for (const factor of spacingSteps) {
    container.style.setProperty('--section-gap', `${Math.round(20 * factor)}px`)
    container.style.setProperty('--item-gap', `${Math.round(12 * factor)}px`)
    container.style.setProperty('--page-padding', `${Math.round(36 * factor)}px`)
    container.style.setProperty('--list-item-gap', `${Math.max(1, Math.round(4 * factor))}px`)

    const currentHeight = container.scrollHeight || container.offsetHeight
    if (currentHeight <= targetHeight + tolerance) {
      return {
        fitted: true,
        tier: 1,
        appliedValues: { spacingFactor: factor, lineHeight: 1.5, scale: 1.0 },
        originalHeight,
        finalHeight: currentHeight,
        overflowRatio,
      }
    }
  }

  // Tier 2: 行高微调阶梯 (保持 Tier 1 最小间距)
  const lineHeightSteps = [1.45, 1.38, 1.30, minLineHeight]
  for (const lh of lineHeightSteps) {
    container.style.setProperty('--line-height', `${lh}`)
    container.style.lineHeight = `${lh}`

    const currentHeight = container.scrollHeight || container.offsetHeight
    if (currentHeight <= targetHeight + tolerance) {
      return {
        fitted: true,
        tier: 2,
        appliedValues: { spacingFactor: minSpacing, lineHeight: lh, scale: 1.0 },
        originalHeight,
        finalHeight: currentHeight,
        overflowRatio,
      }
    }
  }

  // Tier 3: 缩放兜底 (Transform Scale)
  const currentHeight = container.scrollHeight || container.offsetHeight
  const rawNeededScale = targetHeight / currentHeight
  const appliedScale = Math.max(minScale, Number(rawNeededScale.toFixed(3)))

  container.style.transform = `scale(${appliedScale})`
  container.style.transformOrigin = 'top center'
  container.style.maxHeight = `${targetHeight}px`
  container.style.overflow = 'hidden'

  const finalHeight = Math.round(currentHeight * appliedScale)

  return {
    fitted: finalHeight <= targetHeight + tolerance,
    tier: 3,
    appliedValues: {
      spacingFactor: minSpacing,
      lineHeight: minLineHeight,
      scale: appliedScale,
    },
    originalHeight,
    finalHeight,
    overflowRatio,
  }
}

export function resetAutoFit(container?: HTMLElement | null): void {
  if (!container) return
  container.style.removeProperty('--section-gap')
  container.style.removeProperty('--item-gap')
  container.style.removeProperty('--page-padding')
  container.style.removeProperty('--list-item-gap')
  container.style.removeProperty('--line-height')
  container.style.lineHeight = ''
  container.style.transform = ''
  container.style.transformOrigin = ''
  container.style.maxHeight = ''
  container.style.overflow = ''
}
