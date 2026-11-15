import { describe, it, expect } from 'vitest'
import { generateHTML, generateHTMLFile, sanitizeRichText, isValidHttpUrl, formatFontFamily } from './generateHTML'
import type { ResumeData } from '../types'

describe('generateHTML - Self-contained offline editable HTML export', () => {
  const mockResumeData: ResumeData = {
    basic: {
      name: '张三',
      title: '资深全栈工程师',
      email: 'zhangsan@example.com',
      phone: '13800138000',
      location: '北京',
      github: 'https://github.com/zhangsan',
      website: 'https://zhangsan.dev',
    },
    education: [
      {
        id: 'edu-1',
        school: '清华大学',
        major: '计算机科学与技术',
        degree: '硕士',
        startDate: '2018-09',
        endDate: '2021-06',
        description: 'GPA 3.8/4.0',
      },
    ],
    experience: [
      {
        id: 'exp-1',
        company: '某知名科技公司',
        position: '高级技术专家',
        department: '基础架构部',
        startDate: '2021-07',
        endDate: '至今',
        description: '负责核心分布式存储系统架构设计与落地',
      },
    ],
    projects: [
      {
        id: 'proj-1',
        name: '高性能分布式向量搜索引擎',
        role: '技术负责人',
        startDate: '2022-03',
        endDate: '2023-10',
        projectLink: 'https://github.com/zhangsan/vector-db',
        description: '自研千万级向量检索索引算法，P99 降低 45%',
      },
    ],
    openSource: [],
    skills: [],
    awards: [],
    customSections: [],
    selfEvaluation: '扎实的计算机系统基础与工程交付能力',
    skillContent: '精通 Rust、Go、TypeScript，熟悉 Kubernetes 与 Linux 内核机制',
    sectionOrder: [
      { id: 'education', title: '教育背景' },
      { id: 'experience', title: '工作经历' },
      { id: 'projects', title: '项目经历' },
      { id: 'skills', title: '专业技能' },
      { id: 'selfEvaluation', title: '自我评价' },
    ],
    globalSettings: {
      template: 'asu-tech',
      themeColor: '#2563eb',
      fontSize: 10,
      lineHeight: 1.45,
      pagePadding: 32,
    },
  }

  it('outputs complete self-contained HTML document', () => {
    const html = generateHTML(mockResumeData, 'asu-tech', { editable: true })
    expect(html).toContain('<!DOCTYPE html>')
    expect(html).toContain('<html lang="zh-CN">')
    expect(html).toContain('张三 - 简历导出')
    expect(html).toContain('</html>')
  })

  it('injects contenteditable="true" and spellcheck="false" on key resume fields', () => {
    const html = generateHTML(mockResumeData, 'asu-tech', { editable: true })
    expect(html).toContain('contenteditable="true"')
    expect(html).toContain('spellcheck="false"')
    expect(html).toContain('张三')
    expect(html).toContain('资深全栈工程师')
    expect(html).toContain('清华大学')
    expect(html).toContain('某知名科技公司')
    expect(html).toContain('高性能分布式向量搜索引擎')
  })

  it('contains embedded local toolbar and print styles without external CDN assets', () => {
    const html = generateHTML(mockResumeData, 'asu-tech', { editable: true, autoOnePage: true })
    expect(html).toContain('local-toolbar')
    expect(html).toContain('runAutoOnePage()')
    expect(html).toContain('printDocument()')
    expect(html).toContain('window.print()')
    expect(html).toContain('@page {')
    expect(html).toContain('size: A4 portrait;')

    // Zero external CDN references
    expect(html).not.toMatch(/https?:\/\/fonts\.googleapis\.com/)
    expect(html).not.toMatch(/https?:\/\/cdn\./)
    expect(html).not.toMatch(/https?:\/\/unpkg\.com/)
  })

  it('generateHTMLFile backward compatibility wrapper works', () => {
    const html = generateHTMLFile(mockResumeData)
    expect(html).toContain('<!DOCTYPE html>')
    expect(html).toContain('张三')
  })

  it('sanitizes dangerous markup and scripts in rich text fields', () => {
    // Direct unit tests on sanitizeRichText
    expect(sanitizeRichText('Hello<script>alert(1)</script>World')).toBe('HelloWorld')
    expect(sanitizeRichText('<img src=x onerror="alert(1)">')).toBe('')
    expect(sanitizeRichText('<b onclick="evil()">Safe</b>')).toBe('<b>Safe</b>')
    expect(sanitizeRichText('<ul><li>Point 1</li><li>Point 2</li></ul>')).toBe('<ul><li>Point 1</li><li>Point 2</li></ul>')
    expect(sanitizeRichText('<p>Para 1<br/>Para 2</p>')).toBe('<p>Para 1<br />Para 2</p>')

    const dangerousData: ResumeData = {
      ...mockResumeData,
      selfEvaluation: '正常评价<script>alert("xss")</script><img src=x onerror="alert(1)"><b>安全粗体</b>',
      skillContent: 'JavaScript <iframe src="evil.com"></iframe><i>斜体技能</i>',
      education: [
        {
          ...mockResumeData.education[0],
          description: '<p onmouseover="alert(1)">第一段</p><script>evil()</script><br/>',
        },
      ],
      projects: [
        {
          ...mockResumeData.projects[0],
          description: '<ul><li>项目亮点</li></ul><style>body{display:none}</style>',
        },
      ],
    }

    const html = generateHTML(dangerousData, 'asu-tech', { editable: true })
    expect(html).not.toContain('alert("xss")')
    expect(html).not.toContain('evil.com')
    expect(html).not.toContain('onerror=')
    expect(html).not.toContain('onmouseover=')
    expect(html).not.toContain('evil()')
    expect(html).not.toContain('display:none')
    expect(html).toContain('<b>安全粗体</b>')
    expect(html).toContain('<i>斜体技能</i>')
    expect(html).toContain('<li>项目亮点</li>')
  })

  it('validates project links to only allow http/https and block javascript: URIs', () => {
    expect(isValidHttpUrl('https://example.com')).toBe(true)
    expect(isValidHttpUrl('http://example.com')).toBe(true)
    expect(isValidHttpUrl('javascript:alert(1)')).toBe(false)
    expect(isValidHttpUrl('data:text/html,...')).toBe(false)
    expect(isValidHttpUrl(null)).toBe(false)

    const linkAttackData: ResumeData = {
      ...mockResumeData,
      projects: [
        {
          ...mockResumeData.projects[0],
          projectLink: 'javascript:alert(document.cookie)',
        },
      ],
    }

    const htmlWithBadLink = generateHTML(linkAttackData, 'asu-tech', { editable: true })
    expect(htmlWithBadLink).not.toContain('javascript:')
    expect(htmlWithBadLink).not.toContain('🔗 Link')

    const safeLinkData: ResumeData = {
      ...mockResumeData,
      projects: [
        {
          ...mockResumeData.projects[0],
          projectLink: 'https://github.com/safe/project',
        },
      ],
    }

    const htmlWithSafeLink = generateHTML(safeLinkData, 'asu-tech', { editable: true })
    expect(htmlWithSafeLink).toContain('href="https://github.com/safe/project"')
    expect(htmlWithSafeLink).toContain('🔗 Link')
  })

  it('ensures font family with spaces/special characters are properly quoted', () => {
    expect(formatFontFamily('PingFang SC')).toContain('"PingFang SC"')
    expect(formatFontFamily('Microsoft YaHei')).toContain('"Microsoft YaHei"')
    expect(formatFontFamily()).toContain('"PingFang SC"')
    expect(formatFontFamily()).toContain('"Microsoft YaHei"')
    expect(formatFontFamily()).toContain('"Helvetica Neue"')

    const fontData: ResumeData = {
      ...mockResumeData,
      globalSettings: {
        ...mockResumeData.globalSettings,
        fontFamily: 'PingFang SC',
      },
    }

    const html = generateHTML(fontData, 'asu-tech', { editable: true })
    expect(html).toContain('"PingFang SC"')
    expect(html).toContain('"Microsoft YaHei"')
    expect(html).toContain('"Helvetica Neue"')
  })

  it('includes openSource in default activeSections fallback array', () => {
    const dataWithoutOrder: ResumeData = {
      ...mockResumeData,
      sectionOrder: [],
      openSource: [
        {
          id: 'os-1',
          project: 'Awesome-Resume-Agent',
          role: 'Core Contributor',
          stars: 1200,
          description: '贡献了核心自适应渲染引擎',
        },
      ],
    }

    const html = generateHTML(dataWithoutOrder, 'asu-tech', { editable: true })
    expect(html).toContain('开源经历')
    expect(html).toContain('Awesome-Resume-Agent')
    expect(html).toContain('贡献了核心自适应渲染引擎')
  })

  it('does not render toolbar or edit-mode class when editable: false', () => {
    const html = generateHTML(mockResumeData, 'asu-tech', { editable: false })
    expect(html).not.toContain('<div class="local-toolbar')
    expect(html).not.toContain('id="btn-edit-toggle"')
    expect(html).not.toContain('<body class="edit-mode">')
    expect(html).toContain('<body class="">')
  })
})
