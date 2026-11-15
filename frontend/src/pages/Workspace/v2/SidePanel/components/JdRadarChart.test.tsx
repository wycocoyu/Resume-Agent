import { describe, it, expect } from 'vitest'
import {
  getVertexCoordinate,
  getRingPointsString,
  getDataPointsString,
  RADAR_CENTER_X,
  RADAR_CENTER_Y,
  RADAR_RADIUS,
} from './JdRadarChart'
import { highlightKeywordsAndMetrics } from './StarRewriteDiffCard'

describe('JdRadarChart Math & Geometry Engine', () => {
  it('calculates correct equilateral triangle vertices at radius = 95', () => {
    // Vertex 0: Top (-90 deg) -> (150, 140 - 95) = (150, 45)
    const top = getVertexCoordinate(1.0, 0)
    expect(top.x).toBeCloseTo(150, 1)
    expect(top.y).toBeCloseTo(45, 1)

    // Vertex 1: Bottom-Right (30 deg) -> (150 + 95 * cos(30), 140 + 95 * sin(30))
    // cos(30) = sqrt(3)/2 ≈ 0.866 -> 150 + 82.27 = 232.27
    // sin(30) = 0.5 -> 140 + 47.5 = 187.5
    const bottomRight = getVertexCoordinate(1.0, 1)
    expect(bottomRight.x).toBeCloseTo(232.27, 1)
    expect(bottomRight.y).toBeCloseTo(187.5, 1)

    // Vertex 2: Bottom-Left (150 deg) -> (150 - 82.27 = 67.73, 140 + 47.5 = 187.5)
    const bottomLeft = getVertexCoordinate(1.0, 2)
    expect(bottomLeft.x).toBeCloseTo(67.73, 1)
    expect(bottomLeft.y).toBeCloseTo(187.5, 1)
  })

  it('generates concentric ring points for polygon elements', () => {
    const ring1 = getRingPointsString(1.0)
    expect(ring1).toContain('150,45')
    expect(ring1).toContain('232.27,187.5')
    expect(ring1).toContain('67.73,187.5')

    const ringHalf = getRingPointsString(0.5)
    const topHalf = getVertexCoordinate(0.5, 0)
    expect(ringHalf).toContain(`${topHalf.x},${topHalf.y}`)
  })

  it('clamps scores between 10 and 100 in data points string', () => {
    const pointsHigh = getDataPointsString([
      { key: 'technical', name: '技术', score: 150 },
      { key: 'project', name: '项目', score: -20 },
      { key: 'experience', name: '资历', score: 85 },
    ])
    // 150 clamps to 100 (top vertex 150, 45)
    expect(pointsHigh).toContain('150,45')
    // -20 clamps to 10 (bottom-right near center)
    const clampedProject = getVertexCoordinate(0.1, 1)
    expect(pointsHigh).toContain(`${clampedProject.x},${clampedProject.y}`)
  })
})

describe('STAR Rewrite Highlighting Engine', () => {
  it('highlights quantifiable metrics and numbers with blue badges', () => {
    const text = '主导系统性能调优，使端到端处理耗时降低 35%，支撑峰值 QPS 达 50000+。'
    const html = highlightKeywordsAndMetrics(text, [])
    expect(html).toContain('bg-blue-100')
    expect(html).toContain('35%')
    expect(html).toContain('50000+')
  })

  it('highlights JD keywords with emerald badges', () => {
    const text = '基于 Go 和 Kubernetes 构建微服务，使用 Redis 实现多级缓存。'
    const keywords = ['Go', 'Kubernetes', 'Redis']
    const html = highlightKeywordsAndMetrics(text, keywords)
    expect(html).toContain('bg-emerald-100')
    expect(html).toContain('Go')
    expect(html).toContain('Kubernetes')
    expect(html).toContain('Redis')
  })
})
