// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ResumeAsuTech } from './ResumeAsuTech'
import { ResumeAsuVariant } from './ResumeAsuVariant'
import type { BuilderResumeData } from '../types'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true

describe('ResumeAsuTech & ResumeAsuVariant hardening', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
  })

  const baseData: BuilderResumeData = {
    personalInfo: {
      name: '李四',
      title: '前端架构师',
      email: 'lisi@example.com',
      phone: '13900000000',
    },
    workExperience: [
      {
        id: 'exp-1',
        company: '某互联网大厂',
        title: '资深专家',
        years: '2020-01 - 至今',
        description: [
          '主导前端微前端架构演进',
          null as any, // 恶意或脏数据
          undefined as any,
          123 as any,
          '  二级嵌套条目内容',
        ],
      },
    ],
    education: [
      {
        id: 'edu-1',
        institution: '浙江大学',
        degree: '学士',
        years: '2016-09 - 2020-06',
        description: [
          'GPA 3.9',
          null as any,
        ],
      },
    ],
    personalProjects: [
      {
        id: 'proj-1',
        name: '低代码简历系统',
        years: '2023-01 - 2023-12',
        description: [
          null as any,
          '自研 AST 模板解析引擎',
        ],
      },
    ],
    skills: ['React', null as any, 'TypeScript'],
    awards: ['优秀员工', undefined as any],
    summary: ['深耕前端领域 8 年', null as any],
  }

  it('ResumeAsuTech handles null and non-string bullets gracefully without crashing', () => {
    act(() => {
      root.render(<ResumeAsuTech data={baseData} />)
    })
    expect(container.textContent).toContain('李四')
    expect(container.textContent).toContain('主导前端微前端架构演进')
    expect(container.textContent).toContain('自研 AST 模板解析引擎')
    expect(container.textContent).toContain('GPA 3.9')
    expect(container.textContent).toContain('React')
  })

  it('ResumeAsuTech adds photoSlotNoPhoto class when photo is not provided', () => {
    act(() => {
      root.render(<ResumeAsuTech data={baseData} />)
    })
    const photoSlot = container.querySelector('[class*="photoSlot"]')
    expect(photoSlot).not.toBeNull()
    expect(photoSlot?.className).toMatch(/photoSlotNoPhoto/)
  })

  it('ResumeAsuTech does NOT add photoSlotNoPhoto when photo is provided', () => {
    const dataWithPhoto: BuilderResumeData = {
      ...baseData,
      personalInfo: {
        ...baseData.personalInfo,
        photo: 'https://example.com/avatar.jpg',
      },
    }
    act(() => {
      root.render(<ResumeAsuTech data={dataWithPhoto} />)
    })
    const photoSlot = container.querySelector('[class*="photoSlot"]')
    expect(photoSlot).not.toBeNull()
    expect(photoSlot?.className).not.toMatch(/photoSlotNoPhoto/)
    const img = container.querySelector('img[alt="Profile"]')
    expect(img).not.toBeNull()
  })

  it('ResumeAsuVariant handles null and non-string bullets gracefully without crashing', () => {
    act(() => {
      root.render(<ResumeAsuVariant data={baseData} variantId="asu-01" />)
    })
    expect(container.textContent).toContain('主导前端微前端架构演进')
    expect(container.textContent).toContain('GPA 3.9')
  })

  it('aligns ResumeAsuTech headings, 3-row header, inline code, and long openSource role placement with ASu-skills spec', () => {
    const longRole =
      '开源核心作者，基于多代理编排与流式生成流水线构建交互式技术文档助手。支持实时结构化预览、模板渲染工具链调用与多格式导出扩展。'
    const specData = {
      ...baseData,
      personalInfo: {
        ...baseData.personalInfo,
        title: '全栈开发工程师',
        location: '深圳',
        github: 'github.com/example-demo',
      },
      openSource: [
        {
          id: 'os-long-role',
          name: 'OpenAgent 示例框架',
          role: longRole,
          github: 'https://github.com/example/openagent-demo',
          years: '2025.11 - 至今',
          description: ['设计插件化渲染管线与流式状态机'],
        },
      ],
      skills: ['后端：熟悉 <code>Python</code> 与 <code>Go</code> 服务开发'],
    }

    act(() => {
      root.render(<ResumeAsuTech data={specData} />)
    })

    const headingTexts = Array.from(container.querySelectorAll('h2')).map((el) => el.textContent?.trim() || '')
    expect(headingTexts.length).toBeGreaterThan(0)
    expect(headingTexts).toContain('教育经历')
    expect(headingTexts).toContain('开源经历')
    expect(headingTexts.every((t) => !/\s\/\s[A-Za-z]/.test(t))).toBe(true)

    expect(container.textContent).toContain('深圳 · 全栈开发工程师')
    expect(container.textContent).toContain('github.com/example-demo')

    const codeNodes = Array.from(container.querySelectorAll('code')).map((el) => el.textContent)
    expect(codeNodes).toContain('Python')
    expect(codeNodes).toContain('Go')

    const companyBarTexts = Array.from(container.querySelectorAll('[class*="companyBar"]')).map(
      (el) => el.textContent || ''
    )
    const projectLeadTexts = Array.from(container.querySelectorAll('[class*="projectLead"]')).map(
      (el) => el.textContent || ''
    )
    expect(companyBarTexts.some((t) => t.includes(longRole))).toBe(false)
    expect(projectLeadTexts.some((t) => t.includes(longRole))).toBe(true)
  })

  it('applies asu-tech preset with contact icons and tight margins, and renders all 18 ASu variants without crashing', async () => {
    const { applyTemplatePreset, DEFAULT_TEMPLATE_SETTINGS } = await import('../settings')
    const { ASU_VARIANTS_CONFIG } = await import('./ResumeAsuVariant')

    const asuTechPreset = applyTemplatePreset(DEFAULT_TEMPLATE_SETTINGS, 'asu-tech')
    expect(asuTechPreset.showContactIcons).toBe(true)
    expect(asuTechPreset.margins).toEqual({ top: 7, bottom: 8, left: 10, right: 10 })

    const variantIds = Object.keys(ASU_VARIANTS_CONFIG) as Array<keyof typeof ASU_VARIANTS_CONFIG>
    expect(variantIds).toHaveLength(18)

    for (const variantId of variantIds) {
      act(() => {
        root.render(<ResumeAsuVariant data={baseData} variantId={variantId} />)
      })
      expect(container.textContent).toContain('主导前端微前端架构演进')
    }
  })
})
