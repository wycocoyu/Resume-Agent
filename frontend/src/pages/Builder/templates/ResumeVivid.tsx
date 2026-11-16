/**
 * Vivid Resume Template —— 移植自 Resume-Matcher components/resume/resume-vivid.tsx。
 *
 * Colorful two-column layout in the "Awesome-CV" lineage: a two-tone accent name,
 * a monospace title + contact row with circular icon chips, accent small-caps section
 * headers, and accent arrow (➜) bullet markers. Reads the accent-color control
 * (--resume-accent-primary,由外层注入,组件不接 accentColor prop)。
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 双栏分配:主列(63%)= 自我评价 / 实习经历 / 项目经历 / 开源经历(新增,复用 projects 渲染,github → pill);
 *   侧栏(37%)= 专业技能 / 教育经历 / 荣誉奖项 / 自定义模块 / 相关链接;列内顺序按 sectionMeta order(RM 为固定顺序)
 * - 删除 RM 的 additional 行内分类死代码(technicalSkills / languages / certificationsTraining)
 * - skills 为句子型 bullets → 侧栏箭头 bullet 列表(不用 RM 的 join(' • '),不用胶囊 pill)
 * - awards → 侧栏列表(RM 原样式),条目为行内 HTML 经 SafeHtml
 * - summary 为 bullets:单条=正文段,多条=箭头 bullet 列表
 * - education description 为 string[] → 箭头 bullets(RM 为单段 meta 文本)
 * - 自定义模块从主列移入侧栏(需求指定),标题相应改用 sectionTitleSm(RM 在主列用 sectionTitle)
 * - name 缺失不渲染姓名(去掉 'Your Name' 兜底);section 标题取 sectionMeta.displayName,链接栏缺省「相关链接」
 * - 双色调姓名中文适配:纯中文无空格名按「姓/名」切分(含常见复姓,段间不加空格);
 *   有空格仍按 RM 原版首空格切分(2026-07-07 用户拍板)
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Linkedin, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Experience, Project, SectionMeta } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import baseStyles from './styles/_base.module.css'
import styles from './styles/vivid.module.css'

interface ResumeVividProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

/** 主列固定收纳的 section;其余默认 section 与自定义模块进侧栏,列内顺序仍按 sectionMeta */
const MAIN_COLUMN_KEYS = ['summary', 'fullTimeExperience', 'workExperience', 'personalProjects', 'openSource']

// 常见复姓(用于中文姓名的姓/名两色调切分)
const COMPOUND_SURNAMES = [
  '欧阳', '司马', '上官', '诸葛', '夏侯', '皇甫', '尉迟', '长孙',
  '慕容', '令狐', '东方', '独孤', '南宫', '西门', '申屠', '公孙',
]

/**
 * 双色调姓名切分:有空格按 RM 原版取首个空格;纯 CJK 无空格名按「姓/名」切(复姓优先)。
 * nameSpaced 标记两段之间是否渲染空格(西文是,中文否)。
 */
function splitNameTwoTone(fullName: string): {
  nameFirst: string
  nameRest: string
  nameSpaced: boolean
} {
  const firstSpace = fullName.indexOf(' ')
  if (firstSpace !== -1) {
    return {
      nameFirst: fullName.slice(0, firstSpace),
      nameRest: fullName.slice(firstSpace + 1),
      nameSpaced: true,
    }
  }
  if (fullName.length >= 2 && /^[一-鿿]+$/.test(fullName)) {
    const compound = COMPOUND_SURNAMES.find(
      (surname) => fullName.startsWith(surname) && fullName.length > surname.length
    )
    const surname = compound ?? fullName.slice(0, 1)
    return { nameFirst: surname, nameRest: fullName.slice(surname.length), nameSpaced: false }
  }
  return { nameFirst: fullName, nameRest: '', nameSpaced: false }
}

export const ResumeVivid: React.FC<ResumeVividProps> = ({ data, showContactIcons = false }) => {
  const {
    personalInfo,
    summary,
    workExperience,
    fullTimeExperience,
    internships,
    education,
    personalProjects,
    openSource,
  } = data
  const internshipItems = internships !== undefined ? internships : workExperience

  const sortedSections = getSortedSections(data)

  // Two-tone name: bold accent first token, lighter accent for the rest(name 缺失整块不渲染).
  // RM 原版只按首个空格切分;纯中文无空格名补「姓/名」切分(含常见复姓,2026-07-07 用户拍板),
  // 让 vivid 的招牌双色姓名对中文用户同样生效。中文切分时两段之间不加空格。
  const fullName = personalInfo?.name ?? ''
  const { nameFirst, nameRest, nameSpaced } = splitNameTwoTone(fullName)

  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={11} />,
    Phone: <Phone size={11} />,
    Location: <MapPin size={11} />,
    Website: <Globe size={11} />,
    LinkedIn: <Linkedin size={11} />,
    GitHub: <Github size={11} />,
  }

  const renderContactDetail = (label: string, value?: string, hrefPrefix: string = '') => {
    if (!value) return null

    let finalHrefPrefix = hrefPrefix
    if (
      ['Website', 'LinkedIn', 'GitHub'].includes(label) &&
      !value.startsWith('http') &&
      !value.startsWith('//')
    ) {
      finalHrefPrefix = 'https://'
    }

    const href = finalHrefPrefix + value
    const isLink =
      finalHrefPrefix.startsWith('http') ||
      finalHrefPrefix.startsWith('mailto:') ||
      finalHrefPrefix.startsWith('tel:')

    let displayText = value
    if (isLink && (label === 'LinkedIn' || label === 'GitHub' || label === 'Website')) {
      displayText = value.replace(/^https?:\/\//, '').replace(/^www\./, '')
    }

    return (
      <span className={styles.contactChip}>
        {showContactIcons && <span className={styles.iconCircle}>{contactIcons[label]}</span>}
        {isLink ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={`${baseStyles['resume-link']} hover:underline`}
          >
            {displayText}
          </a>
        ) : (
          <span>{displayText}</span>
        )}
      </span>
    )
  }

  const renderArrowBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <ul className={`ml-4 ${baseStyles['resume-list']} ${baseStyles['resume-text-xs']}`}>
        {items.map((desc, index) => (
          <li key={index} className="flex">
            <span className={`mr-1.5 ${styles.arrow}`}>➜&nbsp;</span>
            <span>
              <SafeHtml html={desc} />
            </span>
          </li>
        ))}
      </ul>
    )
  }

  // 项目类条目(personalProjects / openSource 共用):名称 | 角色 + 链接 pill + 日期 meta 右对齐
  const renderProjectItems = (projects?: Project[]) => {
    if (!projects || projects.length === 0) return null
    return (
      <div className={baseStyles['resume-items']}>
        {projects.map((project) => (
          <div key={project.id} className={baseStyles['resume-item']}>
            <div
              className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
            >
              <span className="flex items-baseline gap-1.5 min-w-0">
                <span className={styles.entryCompany}>{project.name}</span>
                {project.role && (
                  <>
                    <span className={styles.entrySep}>|</span>
                    <span className={styles.entryRole}>{project.role}</span>
                  </>
                )}
                {(project.github || project.website) && (
                  <span className="flex gap-1">
                    {project.github && (
                      <a
                        href={
                          project.github.startsWith('http')
                            ? project.github
                            : `https://${project.github}`
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className={baseStyles['resume-link-pill']}
                      >
                        <Github size={9} />
                        {project.github
                          .replace(/^https?:\/\//, '')
                          .replace(/^www\./, '')
                          .replace(/\/$/, '')}
                      </a>
                    )}
                    {project.website && (
                      <a
                        href={
                          project.website.startsWith('http')
                            ? project.website
                            : `https://${project.website}`
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className={baseStyles['resume-link-pill']}
                      >
                        <ExternalLink size={9} />
                        {project.website
                          .replace(/^https?:\/\//, '')
                          .replace(/^www\./, '')
                          .replace(/\/$/, '')}
                      </a>
                    )}
                  </span>
                )}
              </span>
              {project.years && (
                <span className={`${styles.entryMeta} ml-2`}>
                  {formatDateRange(project.years)}
                </span>
              )}
            </div>
            {renderArrowBullets(project.description)}
          </div>
        ))}
      </div>
    )
  }

  const renderExperienceSection = (keyId: string, title: string, items?: Experience[]) => {
    if (!items || items.length === 0) return null
    return (
      <div key={keyId} className={baseStyles['resume-section']}>
        <h3 className={styles.sectionTitle}>{title}</h3>
        <div className={baseStyles['resume-items']}>
          {items.map((exp) => (
            <div key={exp.id} className={baseStyles['resume-item']}>
              <div
                className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
              >
                <span>
                  <TemplateLogo url={exp.companyLogoUrl} size={exp.companyLogoSize} alt={exp.company} /><InlineBold as="span" className={styles.entryCompany} text={exp.company} weightControlled />
                  {exp.title && (
                    <>
                      <span className={styles.entrySep}>|</span>
                      <InlineBold as="span" className={styles.entryRole} text={exp.title} />
                    </>
                  )}
                </span>
              </div>
              <div className={`${baseStyles['resume-row-tight']} ${styles.entryMeta}`}>
                {[formatDateRange(exp.years), exp.location].filter(Boolean).join(' | ')}
              </div>
              {renderArrowBullets(exp.description)}
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderSection = (section: SectionMeta) => {
    switch (section.key) {
      case 'personalInfo':
        return null

      case 'summary':
        if (!summary || summary.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            {summary.length === 1 ? (
              <p className={`text-justify ${baseStyles['resume-text']}`}>
                <SafeHtml html={summary[0]} />
              </p>
            ) : (
              renderArrowBullets(summary)
            )}
          </div>
        )

      case 'fullTimeExperience':
        return renderExperienceSection(section.id, section.displayName, fullTimeExperience)

      case 'workExperience':
        return renderExperienceSection(section.id, section.displayName, internshipItems)

      case 'personalProjects':
        if (!personalProjects || personalProjects.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            {renderProjectItems(personalProjects)}
          </div>
        )

      case 'openSource':
        if (!openSource || openSource.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            {renderProjectItems(openSource)}
          </div>
        )

      case 'skills':
        if (!data.skills || data.skills.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitleSm}>{section.displayName}</h3>
            {renderArrowBullets(data.skills)}
          </div>
        )

      case 'education':
        if (!education || education.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitleSm}>{section.displayName}</h3>
            <div className={baseStyles['resume-stack']}>
              {education.map((edu) => (
                <div key={edu.id}>
                  <h4
                    className={`${baseStyles['resume-item-title-sm']} ${baseStyles['sidebar-text-wrap']}`}
                  >
                    <TemplateLogo url={edu.schoolLogoUrl} size={edu.schoolLogoSize} alt={edu.institution} /><InlineBold text={edu.institution} />
                  </h4>
                  <p className={baseStyles['resume-item-subtitle-sm']}>{edu.degree}</p>
                  {edu.years && (
                    <p className={baseStyles['resume-meta-sm']}>{formatDateRange(edu.years)}</p>
                  )}
                  {renderArrowBullets(edu.description)}
                </div>
              ))}
            </div>
          </div>
        )

      case 'awards':
        if (!data.awards || data.awards.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitleSm}>{section.displayName}</h3>
            <ul className={baseStyles['resume-list']}>
              {data.awards.map((award, index) => (
                <li key={index} className={baseStyles['resume-text-xs']}>
                  <SafeHtml html={award} />
                </li>
              ))}
            </ul>
          </div>
        )

      default:
        if (!section.isDefault) {
          return (
            <DynamicResumeSectionVivid
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderArrowBullets={renderArrowBullets}
            />
          )
        }
        return null
    }
  }

  const mainSections = sortedSections.filter((s) => MAIN_COLUMN_KEYS.includes(s.key))
  const sidebarSections = sortedSections.filter(
    (s) => !MAIN_COLUMN_KEYS.includes(s.key) && s.key !== 'personalInfo'
  )
  const linksTitle = sortedSections.find((s) => s.key === 'links')?.displayName || '相关链接'

  return (
    <>
      {/* Header */}
      {personalInfo && (
        <div className={baseStyles['resume-header']}>
          {fullName && (
            <h1 className={baseStyles['resume-name']}>
              <span className={styles.nameFirst}>{nameFirst}</span>
              {nameRest && (
                <span className={styles.nameRest}>
                  {nameSpaced ? ' ' : ''}
                  {nameRest}
                </span>
              )}
            </h1>
          )}
          {personalInfo.title && <div className={styles.titleLine}>{personalInfo.title}</div>}
          <div className={`flex flex-wrap gap-x-4 gap-y-1 mt-2 ${styles.contactRow}`}>
            {renderContactDetail('Website', personalInfo.website)}
            {renderContactDetail('LinkedIn', personalInfo.linkedin)}
            {renderContactDetail('GitHub', personalInfo.github)}
            {renderContactDetail('Email', personalInfo.email, 'mailto:')}
            {renderContactDetail('Phone', personalInfo.phone, 'tel:')}
            {renderContactDetail('Location', personalInfo.location)}
          </div>
        </div>
      )}

      {/* Two-Column Grid */}
      <div className={styles.grid}>
        {/* Main Column - Left */}
        <div className={styles.mainColumn}>
          {mainSections.map((section) => renderSection(section))}
        </div>

        {/* Sidebar Column - Right */}
        <div className={styles.sidebarColumn}>
          {sidebarSections.map((section) => renderSection(section))}

          {personalInfo &&
            (personalInfo.website || personalInfo.linkedin || personalInfo.github) && (
              <div className={baseStyles['resume-section']}>
                <h3 className={styles.sectionTitleSm}>{linksTitle}</h3>
                <div
                  className={`${baseStyles['resume-stack-tight']} ${baseStyles['resume-meta-sm']}`}
                >
                  {personalInfo.linkedin && (
                    <div>{renderContactDetail('LinkedIn', personalInfo.linkedin)}</div>
                  )}
                  {personalInfo.github && (
                    <div>{renderContactDetail('GitHub', personalInfo.github)}</div>
                  )}
                  {personalInfo.website && (
                    <div>{renderContactDetail('Website', personalInfo.website)}</div>
                  )}
                </div>
              </div>
            )}
        </div>
      </div>
    </>
  )
}

/**
 * Dynamic (custom) section wrapper for the Vivid template.
 * Uses the accent small-caps section title and accent arrow bullets so custom
 * sections match the rest of the template(置于侧栏,标题用 sectionTitleSm)。
 */
const DynamicResumeSectionVivid: React.FC<{
  sectionMeta: SectionMeta
  resumeData: BuilderResumeData
  renderArrowBullets: (items?: string[]) => React.ReactNode
}> = ({ sectionMeta, resumeData, renderArrowBullets }) => {
  const customSection = resumeData.customSections?.[sectionMeta.key]
  if (!customSection) return null

  const hasContent = (() => {
    switch (sectionMeta.sectionType) {
      case 'text':
        return Boolean(customSection.text?.trim())
      case 'itemList':
        return Boolean(customSection.items?.length)
      case 'stringList':
        return Boolean(customSection.strings?.length)
      default:
        return false
    }
  })()

  if (!hasContent) return null

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={styles.sectionTitleSm}>{sectionMeta.displayName}</h3>
      {sectionMeta.sectionType === 'text' && customSection.text?.trim() && (
        <p className={`text-justify ${baseStyles['resume-text']}`}>{customSection.text}</p>
      )}
      {sectionMeta.sectionType === 'itemList' && customSection.items?.length ? (
        <div className={baseStyles['resume-items']}>
          {customSection.items.map((item) => (
            <div key={item.id} className={baseStyles['resume-item']}>
              <div
                className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
              >
                <span className="min-w-0">
                  <span className={styles.entryCompany}>{item.title}</span>
                  {item.subtitle && (
                    <>
                      <span className={styles.entrySep}>|</span>
                      <span className={styles.entryRole}>{item.subtitle}</span>
                    </>
                  )}
                </span>
                {(item.years || item.location) && (
                  <span className={`${styles.entryMeta} ml-2`}>
                    {[formatDateRange(item.years), item.location].filter(Boolean).join(' | ')}
                  </span>
                )}
              </div>
              {renderArrowBullets(item.description)}
            </div>
          ))}
        </div>
      ) : null}
      {sectionMeta.sectionType === 'stringList' && customSection.strings?.length ? (
        <p className={baseStyles['resume-text-xs']}>{customSection.strings.join(' • ')}</p>
      ) : null}
    </div>
  )
}

export default ResumeVivid
