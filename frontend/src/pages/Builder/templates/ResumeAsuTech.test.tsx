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
})
