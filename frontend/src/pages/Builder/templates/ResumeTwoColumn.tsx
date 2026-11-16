/**
 * Swiss Two-Column Resume Template —— 移植自 Resume-Matcher components/resume/resume-two-column.tsx。
 *
 * Two-column layout with experience-focused main column (left) and
 * supporting information sidebar (right).
 *
 * Main Column (65%): Summary, Experience, Projects, Open Source, Custom Sections
 * Sidebar (35%): Education, Skills, Awards, Links
 *
 * Best for technical roles with many projects, optimized for one-page resumes.
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 新增 openSource section(主栏,复用 personalProjects 渲染,github → GitHub pill)
 * - skills / awards 渲染为侧栏 bullets(替代 RM 的 additional 行内分类;RM 源的
 *   technicalSkills pill / languages / certificationsTraining 依赖 additional 数据,
 *   我方模型无此结构,未移植)
 * - summary 为 bullets:单条=正文段,多条=列表
 * - education description 渲染为 bullets(替代 RM 的单段 <p>,保留侧栏 xs/meta 字号)
 * - i18n sectionHeadings props 去掉,fallback 硬编码(取 DEFAULT_SECTION_META 中文名;Links 保留 RM 英文)
 * - 自定义 section 内联为 DynamicResumeSectionSwissTwoColumn(视觉与 RM dynamic-resume-section 一致)
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Linkedin, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Experience, Project, SectionMeta } from '../types'
import { getSortedSections, formatDateRange, DEFAULT_SECTION_META } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import baseStyles from './styles/_base.module.css'
import styles from './styles/swiss-two-column.module.css'

interface ResumeTwoColumnProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeTwoColumn: React.FC<ResumeTwoColumnProps> = ({
  data,
  showContactIcons = false,
}) => {
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

  // Get sorted visible sections
  const sortedSections = getSortedSections(data)

  // Get all sections (including hidden) for visibility checks
  const allSections = data.sectionMeta?.length ? data.sectionMeta : DEFAULT_SECTION_META

  // Get section display name from metadata
  const getSectionDisplayName = (sectionKey: string, fallback: string): string => {
    const section = sortedSections.find((s) => s.key === sectionKey)
    return section?.displayName || fallback
  }

  // Check if a section is visible (use allSections, not sortedSections)
  const isSectionVisible = (sectionKey: string): boolean => {
    const section = allSections.find((s) => s.key === sectionKey)
    return section?.isVisible ?? true
  }

  // Get custom sections (non-default)
  const customSections = sortedSections.filter((s) => !s.isDefault)

  // Icon mapping for contact types
  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={12} />,
    Phone: <Phone size={12} />,
    Location: <MapPin size={12} />,
    Website: <Globe size={12} />,
    LinkedIn: <Linkedin size={12} />,
    GitHub: <Github size={12} />,
  }

  // Helper function to render contact details
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
      <span className="inline-flex items-center gap-1">
        {showContactIcons && contactIcons[label]}
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

  // Bullet 列表(主栏 work/projects/summary 多条共用,DOM 与 RM 源逐字一致,两栏用 xs 字号)
  const renderBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <ul className={`ml-4 ${baseStyles['resume-list']} ${baseStyles['resume-text-xs']}`}>
        {items.map((desc, index) => (
          <li key={index} className="flex">
            <span className="mr-1.5 flex-shrink-0">•&nbsp;</span>
            <span>
              <SafeHtml html={desc} />
            </span>
          </li>
        ))}
      </ul>
    )
  }

  // 项目类条目(personalProjects / openSource 共用):h4 名称 + 链接 pill + 右对齐日期
  const renderProjectItems = (projects?: Project[]) => {
    if (!projects || projects.length === 0) return null
    return (
      <div className={baseStyles['resume-items']}>
        {projects.map((project) => (
          <div key={project.id} className={baseStyles['resume-item']}>
            <div
              className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
            >
              <div className="flex items-baseline gap-1.5">
                <h4 className={baseStyles['resume-item-title-sm']}>{project.name}</h4>
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
              </div>
              {project.years && (
                <span className={`${baseStyles['resume-date']} ml-2`}>
                  {formatDateRange(project.years)}
                </span>
              )}
            </div>
            {project.role && (
              <div
                className={`${baseStyles['resume-row-tight']} ${baseStyles['resume-item-subtitle-sm']}`}
              >
                <span>{project.role}</span>
              </div>
            )}
            {renderBullets(project.description)}
          </div>
        ))}
      </div>
    )
  }

  return (
    <>
      {/* Header Section - Centered Layout */}
      {personalInfo && (
        <header
          className={`text-center ${baseStyles['resume-header']} border-b`}
          style={{ borderColor: 'var(--resume-border-primary)' }}
        >
          {/* Name - Centered */}
          {personalInfo.name && (
            <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>
              {personalInfo.name}
            </h1>
          )}

          {/* Title - Centered, below name */}
          {personalInfo.title && (
            <h2
              className={`${baseStyles['resume-title']} ${baseStyles['resume-meta']} tracking-wide uppercase mb-3`}
            >
              {personalInfo.title}
            </h2>
          )}

          {/* Contact - Own line, centered */}
          <div
            className={`flex flex-wrap justify-center gap-x-1 gap-y-1 ${baseStyles['resume-meta']}`}
          >
            {personalInfo.email && renderContactDetail('Email', personalInfo.email, 'mailto:')}
            {personalInfo.phone && (
              <>
                <span className={baseStyles['text-muted']}>,</span>
                {renderContactDetail('Phone', personalInfo.phone, 'tel:')}
              </>
            )}
            {personalInfo.location && (
              <>
                <span className={baseStyles['text-muted']}>,</span>
                {renderContactDetail('Location', personalInfo.location)}
              </>
            )}
            {personalInfo.website && (
              <>
                <span className={baseStyles['text-muted']}>,</span>
                {renderContactDetail('Website', personalInfo.website)}
              </>
            )}
            {personalInfo.linkedin && (
              <>
                <span className={baseStyles['text-muted']}>,</span>
                {renderContactDetail('LinkedIn', personalInfo.linkedin)}
              </>
            )}
            {personalInfo.github && (
              <>
                <span className={baseStyles['text-muted']}>,</span>
                {renderContactDetail('GitHub', personalInfo.github)}
              </>
            )}
          </div>
        </header>
      )}

      {/* Two Column Layout - items-start ensures content aligns top while grid maintains equal row height */}
      <div className={styles.grid}>
        {/* Main Column - Left */}
        <div className={styles.mainColumn}>
          {/* Summary Section */}
          {isSectionVisible('summary') && summary && summary.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title']}>
                {getSectionDisplayName('summary', '自我评价')}
              </h3>
              {summary.length === 1 ? (
                <p className={`text-justify ${baseStyles['resume-text-sm']}`}>
                  <SafeHtml html={summary[0]} />
                </p>
              ) : (
                renderBullets(summary)
              )}
            </div>
          )}

          {/* Full-Time & Internship Experience Sections */}
          {[
            { key: 'fullTimeExperience', fallback: '工作经历', items: fullTimeExperience },
            { key: 'workExperience', fallback: '实习经历', items: internshipItems },
          ].map(({ key, fallback, items }) =>
            isSectionVisible(key) && items && items.length > 0 ? (
              <div key={key} className={baseStyles['resume-section']}>
                <h3 className={baseStyles['resume-section-title']}>
                  {getSectionDisplayName(key, fallback)}
                </h3>
                <div className={baseStyles['resume-items']}>
                  {items.map((exp) => (
                    <div key={exp.id} className={baseStyles['resume-item']}>
                      <div
                        className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
                      >
                        <h4 className={baseStyles['resume-item-title-sm']}><InlineBold text={exp.title} /></h4>
                        {exp.years && (
                          <span className={`${baseStyles['resume-date']} ml-2`}>
                            {formatDateRange(exp.years)}
                          </span>
                        )}
                      </div>

                      <div
                        className={`flex justify-between items-center ${baseStyles['resume-row-tight']} ${baseStyles['resume-item-subtitle-sm']}`}
                      >
                        <span>
                          <TemplateLogo url={exp.companyLogoUrl} size={exp.companyLogoSize} alt={exp.company} /><InlineBold text={exp.company} weightControlled />
                          {exp.location && <> • {exp.location}</>}
                        </span>
                      </div>

                      {renderBullets(exp.description)}
                    </div>
                  ))}
                </div>
              </div>
            ) : null,
          )}

          {/* Projects Section */}
          {isSectionVisible('personalProjects') &&
            personalProjects &&
            personalProjects.length > 0 && (
              <div className={baseStyles['resume-section']}>
                <h3 className={baseStyles['resume-section-title']}>
                  {getSectionDisplayName('personalProjects', '项目经历')}
                </h3>
                {renderProjectItems(personalProjects)}
              </div>
            )}

          {/* Open Source Section */}
          {isSectionVisible('openSource') && openSource && openSource.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title']}>
                {getSectionDisplayName('openSource', '开源经历')}
              </h3>
              {renderProjectItems(openSource)}
            </div>
          )}

          {/* Custom Sections - Main column */}
          {customSections.map((section) => (
            <DynamicResumeSectionSwissTwoColumn
              key={section.id}
              sectionMeta={section}
              resumeData={data}
            />
          ))}
        </div>

        {/* Sidebar Column - Right */}
        <div className={styles.sidebarColumn}>
          {/* Education Section */}
          {isSectionVisible('education') && education && education.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title-sm']}>
                {getSectionDisplayName('education', '教育经历')}
              </h3>
              <div className={baseStyles['resume-stack']}>
                {education.map((edu) => (
                  <div key={edu.id}>
                    <h4
                      className={`${baseStyles['resume-item-title-sm']} ${baseStyles['sidebar-text-wrap']}`}
                    >
                      <TemplateLogo url={edu.schoolLogoUrl} size={edu.schoolLogoSize} alt={edu.institution} /><InlineBold text={edu.institution} />
                      {edu.years && (
                        <span
                          className={`font-normal ${baseStyles['resume-date']} ${baseStyles['text-muted']}`}
                        >
                          {' '}
                          | {formatDateRange(edu.years)}
                        </span>
                      )}
                    </h4>
                    <p className={baseStyles['resume-item-subtitle-sm']}>{edu.degree}</p>
                    {edu.description && edu.description.length > 0 && (
                      <ul className={baseStyles['resume-list']}>
                        {edu.description.map((desc, index) => (
                          <li
                            key={index}
                            className={`${baseStyles['resume-text-xs']} ${baseStyles['resume-meta']}`}
                          >
                            <SafeHtml html={desc} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Skills Section */}
          {isSectionVisible('skills') && data.skills && data.skills.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title-sm']}>
                {getSectionDisplayName('skills', '专业技能')}
              </h3>
              <ul className={baseStyles['resume-list']}>
                {data.skills.map((skill, index) => (
                  <li key={index} className={baseStyles['resume-text-xs']}>
                    <SafeHtml html={skill} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Awards Section */}
          {isSectionVisible('awards') && data.awards && data.awards.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={baseStyles['resume-section-title-sm']}>
                {getSectionDisplayName('awards', '荣誉奖项')}
              </h3>
              <ul className={baseStyles['resume-list']}>
                {data.awards.map((award, index) => (
                  <li key={index} className={baseStyles['resume-text-xs']}>
                    <SafeHtml html={award} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Links Section */}
          {personalInfo &&
            (personalInfo.website || personalInfo.linkedin || personalInfo.github) && (
              <div className={baseStyles['resume-section']}>
                <h3 className={baseStyles['resume-section-title-sm']}>Links</h3>
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
 * Dynamic (custom) section wrapper for the Swiss two-column template.
 * 视觉语言与 RM dynamic-resume-section.tsx 一致(base 类:h4 标题 + meta-sm 日期,sm 字号 bullets)。
 */
const DynamicResumeSectionSwissTwoColumn: React.FC<{
  sectionMeta: SectionMeta
  resumeData: BuilderResumeData
}> = ({ sectionMeta, resumeData }) => {
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
      <h3 className={baseStyles['resume-section-title']}>{sectionMeta.displayName}</h3>
      {sectionMeta.sectionType === 'text' && customSection.text?.trim() && (
        <p className={`text-justify ${baseStyles['resume-text']}`}>{customSection.text}</p>
      )}
      {sectionMeta.sectionType === 'itemList' && customSection.items?.length ? (
        <div className={baseStyles['resume-items']}>
          {customSection.items.map((item) => (
            <div key={item.id} className={baseStyles['resume-item']}>
              {/* Title and Years Row */}
              <div
                className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
              >
                <h4 className={baseStyles['resume-item-title']}>{item.title}</h4>
                {item.years && (
                  <span className={`${baseStyles['resume-meta-sm']} shrink-0 ml-4`}>
                    {formatDateRange(item.years)}
                  </span>
                )}
              </div>

              {/* Subtitle and Location Row */}
              {(item.subtitle || item.location) && (
                <div
                  className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
                >
                  {item.subtitle && <span>{item.subtitle}</span>}
                  {item.location && <span>{item.location}</span>}
                </div>
              )}

              {/* Description Points */}
              {item.description && item.description.length > 0 && (
                <ul className={`ml-4 ${baseStyles['resume-list']} ${baseStyles['resume-text-sm']}`}>
                  {item.description.map((desc, index) => (
                    <li key={index} className="flex">
                      <span className="mr-1.5 flex-shrink-0">•&nbsp;</span>
                      <span>
                        <SafeHtml html={desc} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : null}
      {sectionMeta.sectionType === 'stringList' && customSection.strings?.length ? (
        <div className={baseStyles['resume-text-sm']}>{customSection.strings.join(', ')}</div>
      ) : null}
    </div>
  )
}

export default ResumeTwoColumn
