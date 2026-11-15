/**
 * 简历模板数据管理
 * 
 * 定义所有可用的简历模板及其元数据
 */
import type { ResumeData } from '../pages/Workspace/v2/types'
import { DEFAULT_RESUME_TEMPLATE } from './defaultTemplate'

export type TemplateType = 'latex' | 'html'

export interface TemplateMetadata {
  id: string
  name: string
  description: string
  type: TemplateType // 模板类型：latex 或 html
  thumbnail?: string // 预览图 URL（未来可扩展）
  category?: string // 分类（未来可扩展）
  tags?: string[] // 标签（未来可扩展）
}

/**
 * 模板元数据列表
 * 包含 LaTeX 和 HTML 模板
 */
// COS 图片 URL
const COS_BASE_URL = 'https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com'

export const TEMPLATE_METADATA: TemplateMetadata[] = [
  {
    id: 'default',
    name: '经典模板（LaTeX）',
    description: 'LATEX简历模板：适用于程序员大多数求职场景',
    type: 'latex',
    category: '通用',
    tags: ['标准', '通用', '经典', '高质量'],
    thumbnail: `${COS_BASE_URL}/classic.png`
  },
  {
    id: 'html-classic',
    name: '经典模板（HTML）',
    description: 'HTML实时编辑模板：支持实时预览',
    type: 'html',
    category: '通用',
    tags: ['实时预览', '快速编辑', '经典'],
    thumbnail: `${COS_BASE_URL}/html.png`
  },
  {
    id: 'asu-tech',
    name: 'ASu 极客单栏',
    description: '高密度技术单栏简历，精配公司条目灰色气泡与多层级项目列表',
    type: 'html',
    category: '技术',
    tags: ['ASu', '高密度', '单栏', '大厂标准'],
    thumbnail: `${COS_BASE_URL}/asu-tech.png`
  },
  {
    id: 'asu-01',
    name: '经典蓝线 (01)',
    description: '深蓝横线标题，单栏紧凑排版',
    type: 'html',
    category: '单栏',
    tags: ['经典', '蓝线', '紧凑'],
  },
  {
    id: 'asu-02',
    name: '蓝底色块条 (02)',
    description: '蓝底反白标题色块，单栏明朗结构',
    type: 'html',
    category: '单栏',
    tags: ['色块', '蓝底', '醒目'],
  },
  {
    id: 'asu-03',
    name: '时间轴 (03)',
    description: '左侧经历时间轴连接线，科技感脉络',
    type: 'html',
    category: '单栏',
    tags: ['时间轴', '科技感'],
  },
  {
    id: 'asu-04',
    name: '深蓝顶幅 (04)',
    description: '深蓝通栏顶幅背景，视觉冲击力强',
    type: 'html',
    category: '单栏',
    tags: ['通栏', '深蓝顶幅'],
  },
  {
    id: 'asu-05',
    name: '灰调侧栏 (05)',
    description: '左侧浅灰背景功能侧栏，右侧主经历',
    type: 'html',
    category: '侧栏',
    tags: ['侧栏', '双列', '灰调'],
  },
  {
    id: 'asu-06',
    name: '纯黑时间轴双页 (06)',
    description: '沉稳黑灰时间轴双页设计，适合资深技术',
    type: 'html',
    category: '双页',
    tags: ['双页', '纯黑', '时间轴'],
  },
  {
    id: 'asu-07',
    name: '右侧蓝轨 (07)',
    description: '右侧纵向蓝轨边线，版式独特鲜明',
    type: 'html',
    category: '单栏',
    tags: ['右轨', '蓝线'],
  },
  {
    id: 'asu-08',
    name: '色块双栏双页 (08)',
    description: '双栏结构双页排版，信息密度充实',
    type: 'html',
    category: '双栏',
    tags: ['双栏', '双页', '色块'],
  },
  {
    id: 'asu-09',
    name: '卡片分区双页 (09)',
    description: '模块轻微卡片边框包围，层级井然',
    type: 'html',
    category: '双页',
    tags: ['卡片', '双页', '黑灰'],
  },
  {
    id: 'asu-10',
    name: '丝带标签 (10)',
    description: '丝带切角标题标签，活泼有致',
    type: 'html',
    category: '单栏',
    tags: ['丝带', '标签', '活力'],
  },
  {
    id: 'asu-11',
    name: '衬线分割头 (11)',
    description: '衬线优雅字体与双线分割头',
    type: 'html',
    category: '单栏',
    tags: ['衬线', '优雅', '学术'],
  },
  {
    id: 'asu-12',
    name: '居中作品集双页 (12)',
    description: '头部居中对齐，作品项目特化双页',
    type: 'html',
    category: '双页',
    tags: ['作品集', '居中', '双页'],
  },
  {
    id: 'asu-13',
    name: '纯黑紧凑侧栏 (13)',
    description: '深黑高对比紧凑侧栏，专业硬核',
    type: 'html',
    category: '侧栏',
    tags: ['纯黑', '侧栏', '高密度'],
  },
  {
    id: 'asu-14',
    name: '蓝线紧凑双栏双页 (14)',
    description: '蓝线主题紧凑双栏双页版式',
    type: 'html',
    category: '双栏',
    tags: ['双栏', '双页', '蓝线'],
  },
  {
    id: 'asu-15',
    name: '色块现代序号 (15)',
    description: '模块标题带圆圈序号微标',
    type: 'html',
    category: '单栏',
    tags: ['序号', '现代', '色块'],
  },
  {
    id: 'asu-16',
    name: '超高密度双栏双页 (16)',
    description: '极端高密度双栏双页技术版式',
    type: 'html',
    category: '双栏',
    tags: ['超高密度', '双栏', '双页'],
  },
  {
    id: 'asu-17',
    name: '纯黑学术风双页 (17)',
    description: '纯黑严谨学术风双页排版',
    type: 'html',
    category: '双页',
    tags: ['学术', '纯黑', '双页'],
  },
  {
    id: 'asu-18',
    name: '蓝线现代紧凑双页 (18)',
    description: '现代极简蓝线双页排版',
    type: 'html',
    category: '双页',
    tags: ['现代', '蓝线', '紧凑', '双页'],
  }
]

/**
 * 根据模板 ID 获取模板数据
 */
export function getTemplateById(templateId: string): ResumeData | null {
  // 目前所有模板都使用默认模板数据
  // 未来可以根据 templateId 返回不同的模板结构
  const template = structuredClone(DEFAULT_RESUME_TEMPLATE)
  template.templateId = templateId
  return template
}

/**
 * 获取所有模板的元数据
 */
export function getAllTemplates(): TemplateMetadata[] {
  return TEMPLATE_METADATA
}

/**
 * 根据模板 ID 获取模板元数据
 */
export function getTemplateMetadata(templateId: string): TemplateMetadata | null {
  return TEMPLATE_METADATA.find(t => t.id === templateId) || null
}

