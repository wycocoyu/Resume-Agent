// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { autoFitToOnePage, resetAutoFit, A4_TARGET_HEIGHT_PX } from './autoOnePage'

describe('autoFitToOnePage - 3-Tier progressive height fitting', () => {
  let element: HTMLElement

  beforeEach(() => {
    element = document.createElement('div')
    document.body.appendChild(element)
  })

  it('Tier 0: Content within A4 target height requires no compression', () => {
    Object.defineProperty(element, 'scrollHeight', { value: 900, configurable: true })
    const result = autoFitToOnePage(element, A4_TARGET_HEIGHT_PX)

    expect(result.tier).toBe(0)
    expect(result.fitted).toBe(true)
    expect(result.appliedValues.scale).toBe(1.0)
    expect(result.appliedValues.spacingFactor).toBe(1.0)
  })

  it('Tier 1: Slight overflow (+80px) resolved by spacing compression', () => {
    let callCount = 0
    Object.defineProperty(element, 'scrollHeight', {
      get: () => {
        callCount++
        // 初始 1200px，随着调整 spacing 后降至 1100px
        return callCount <= 1 ? 1200 : 1100
      },
      configurable: true,
    })

    const result = autoFitToOnePage(element, A4_TARGET_HEIGHT_PX)
    expect(result.tier).toBe(1)
    expect(result.fitted).toBe(true)
    expect(result.appliedValues.scale).toBe(1.0)
    expect(result.appliedValues.spacingFactor).toBeLessThan(1.0)
  })

  it('Tier 2: Moderate overflow (+250px) resolved by line-height compression', () => {
    let callCount = 0
    Object.defineProperty(element, 'scrollHeight', {
      get: () => {
        callCount++
        // 经历 4 步 spacing 仍超高，进入 line-height 阶段后降至 1110px
        return callCount <= 5 ? 1350 : 1110
      },
      configurable: true,
    })

    const result = autoFitToOnePage(element, A4_TARGET_HEIGHT_PX)
    expect(result.tier).toBe(2)
    expect(result.fitted).toBe(true)
    expect(result.appliedValues.lineHeight).toBeLessThan(1.5)
  })

  it('Tier 3: Severe overflow (+600px) activates transform scale with minScale bound', () => {
    Object.defineProperty(element, 'scrollHeight', { value: 1800, configurable: true })

    const result = autoFitToOnePage(element, { targetHeight: A4_TARGET_HEIGHT_PX, minScale: 0.82 })
    expect(result.tier).toBe(3)
    expect(result.appliedValues.scale).toBeGreaterThanOrEqual(0.82)
    expect(element.style.transform).toContain('scale(')
    expect(element.style.maxHeight).toBe(`${A4_TARGET_HEIGHT_PX}px`)
  })

  it('resetAutoFit clears all applied inline styles and variables', () => {
    element.style.setProperty('--section-gap', '10px')
    element.style.lineHeight = '1.25'
    element.style.transform = 'scale(0.85)'
    element.style.maxHeight = '1122.5px'

    resetAutoFit(element)

    expect(element.style.getPropertyValue('--section-gap')).toBe('')
    expect(element.style.lineHeight).toBe('')
    expect(element.style.transform).toBe('')
    expect(element.style.maxHeight).toBe('')
  })

  it('handles null / undefined container gracefully with default result', () => {
    const resultNull = autoFitToOnePage(null as any)
    expect(resultNull.fitted).toBe(true)
    expect(resultNull.tier).toBe(0)
    expect(resultNull.appliedValues.scale).toBe(1.0)
    expect(resultNull.originalHeight).toBe(0)

    const resultUndefined = autoFitToOnePage(undefined)
    expect(resultUndefined.fitted).toBe(true)
    expect(resultUndefined.tier).toBe(0)

    expect(() => resetAutoFit(null as any)).not.toThrow()
    expect(() => resetAutoFit(undefined)).not.toThrow()
  })

  it('respects height tolerance margin for subpixel / print boundary', () => {
    // 1123px is slightly above 1122.5px, but within 1.5px tolerance
    Object.defineProperty(element, 'scrollHeight', { value: 1123.5, configurable: true })
    const result = autoFitToOnePage(element, { targetHeight: A4_TARGET_HEIGHT_PX, tolerance: 1.5 })
    expect(result.tier).toBe(0)
    expect(result.fitted).toBe(true)
  })
})
