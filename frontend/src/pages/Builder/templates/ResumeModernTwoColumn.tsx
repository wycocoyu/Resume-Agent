/**
 * Modern Two-Column Resume Template —— 移植自 Resume-Matcher components/resume/resume-modern-two-column.tsx。
 *
 * Two-column layout with modern colorful accents and customizable theme colors.
 * Combines the efficiency of two-column layout with vibrant modern design.
 *
 * Main Column (65%): Summary, Experience, Projects, Open Source, Custom Sections
 * Sidebar (35%): Education, Skills, Awards, Links
 * 强调色由外层 cssVars 注入(--resume-accent-primary / --resume-accent-light)。
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 新增 openSource section(主栏,复用 personalProjects 渲染,github → GitHub pill)
 * - skills 渲染为 bullets(替代 RM 侧栏的 skill-pill 云;我方 skills 是句子型 bullets)
 * - awards 渲染沿用 RM 侧栏列表,但条目走 SafeHtml bullets(我方 awards 是行内 HTML)
 * - RM 的 languages / certificationsTraining(additional)在我方数据模型不存在,未移植
 * - summary 为 bullets:单条=正文段,多条=列表
 * - education description 渲染为 bullets(替代 RM 的单段 <p>)
 * - i18n heading/fallback props 去掉,标题走 sectionMeta.displayName,兜底硬编码中文
 * - getSectionMeta 无独立 helper,等价内联(sectionMeta ?? DEFAULT_SECTION_META)
 * - 自定义 section 内联为 DynamicResumeSectionModernTwoColumn(视觉与 RM dynamic-resume-section 一致)
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Linkedin, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Experience, Project, SectionMeta } from '../types'
import { getSortedSections, formatDateRange, DEFAULT_SECTION_META } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import baseStyles from './styles/_base.module.css'
import styles from './styles/modern-two-column.module.css'

interface ResumeModernTwoColumnProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeModernTwoColumn: React.FC<ResumeModernTwoColumnProps> = ({
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
  // (RM getSectionMeta 的等价内联)
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
          <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
        )}
      </span>
    )
  }

  // Bullet 列表(两栏版走 xs 字号,DOM 与 RM 源逐字一致)
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

  // 项目类条目(personalProjects / openSource 共用):两栏版紧凑尺寸(title-sm / pill 9px 图标)
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
      {/* Header：有照片时左文右图，无照片时保持原样 */}
      <div className={`${baseStyles['resume-header']} flex items-start justify-between gap-4`}>
        <div className="min-w-0 flex-1">
          {personalInfo?.name && (
            <h1 className={`${baseStyles['resume-name']} ${styles.nameAccent}`}>
              {personalInfo.name}
            </h1>
          )}
          {personalInfo?.title && (
            <div className={`${baseStyles['resume-title']} mt-1`}>{personalInfo.title}</div>
          )}
          {personalInfo && (
            <div className={`${baseStyles['resume-meta']} flex flex-wrap gap-x-3 gap-y-1 mt-2`}>
              {renderContactDetail('Email', personalInfo.email, 'mailto:')}
              {renderContactDetail('Phone', personalInfo.phone, 'tel:')}
              {renderContactDetail('Location', personalInfo.location)}
              {renderContactDetail('Website', personalInfo.website)}
              {renderContactDetail('LinkedIn', personalInfo.linkedin)}
              {renderContactDetail('GitHub', personalInfo.github)}
            </div>
          )}
        </div>
        {personalInfo?.photo && (
          <img
            src={personalInfo.photo}
            alt={personalInfo?.name || '照片'}
            className="shrink-0 w-[76px] h-[95px] object-cover rounded-[3px] border-2"
            style={{ borderColor: 'var(--resume-accent-primary)' }}
          />
        )}
      </div>

      {/* Two-Column Grid */}
      <div className={styles.grid}>
        {/* Main Column - Left */}
        <div className={styles.mainColumn}>
          {/* Summary Section */}
          {isSectionVisible('summary') && summary && summary.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={styles.sectionTitleAccent}>
                {getSectionDisplayName('summary', '自我评价')}
              </h3>
              {summary.length === 1 ? (
                <p className={`text-justify ${baseStyles['resume-text']}`}>
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
                <h3 className={styles.sectionTitleAccent}>
                  {getSectionDisplayName(key, fallback)}
                </h3>
                <div className={baseStyles['resume-items']}>
                  {items.map((exp) => (
                    <div key={exp.id} className={baseStyles['resume-item']}>
                      <div
                        className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
                      >
                        <h4 className={baseStyles['resume-item-title-sm']}><InlineBold text={exp.title} /></h4>
                        <span className={`${baseStyles['resume-date']} ml-4`}>
                          {formatDateRange(exp.years)}
                        </span>
                      </div>

                      <div
                        className={`flex justify-between items-center ${baseStyles['resume-row-tight']} ${baseStyles['resume-item-subtitle-sm']}`}
                      >
                        <span>
                          <TemplateLogo url={exp.companyLogoUrl} size={exp.companyLogoSize} alt={exp.company} />
                          <InlineBold text={exp.company} weightControlled />
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
                <h3 className={styles.sectionTitleAccent}>
                  {getSectionDisplayName('personalProjects', '项目经历')}
                </h3>
                {renderProjectItems(personalProjects)}
              </div>
            )}

          {/* Open Source Section - Main column */}
          {isSectionVisible('openSource') && openSource && openSource.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3 className={styles.sectionTitleAccent}>
                {getSectionDisplayName('openSource', '开源经历')}
              </h3>
              {renderProjectItems(openSource)}
            </div>
          )}

          {/* Custom Sections - Main column */}
          {customSections.map((section) => (
            <DynamicResumeSectionModernTwoColumn
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderBullets={renderBullets}
            />
          ))}
        </div>

        {/* Sidebar Column - Right */}
        <div className={styles.sidebarColumn}>
          {/* Education Section */}
          {isSectionVisible('education') && education && education.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3
                className={`${baseStyles['resume-section-title-sm']} text-[var(--resume-accent-primary)]`}
              >
                {getSectionDisplayName('education', '教育经历')}
              </h3>
              <div className={baseStyles['resume-stack']}>
                {education.map((edu) => (
                  <div key={edu.id}>
                    <h4
                      className={`${baseStyles['resume-item-title-sm']} ${baseStyles['sidebar-text-wrap']}`}
                    >
                      <TemplateLogo url={edu.schoolLogoUrl} size={edu.schoolLogoSize} alt={edu.institution} />
                      <InlineBold text={edu.institution} />
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
                    {renderBullets(edu.description)}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Skills Section */}
          {isSectionVisible('skills') && data.skills && data.skills.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3
                className={`${baseStyles['resume-section-title-sm']} text-[var(--resume-accent-primary)]`}
              >
                {getSectionDisplayName('skills', '专业技能')}
              </h3>
              {renderBullets(data.skills)}
            </div>
          )}

          {/* Awards Section */}
          {isSectionVisible('awards') && data.awards && data.awards.length > 0 && (
            <div className={baseStyles['resume-section']}>
              <h3
                className={`${baseStyles['resume-section-title-sm']} text-[var(--resume-accent-primary)]`}
              >
                {getSectionDisplayName('awards', '荣誉奖项')}
              </h3>
              {renderBullets(data.awards)}
            </div>
          )}

          {/* Links Section */}
          {personalInfo &&
            (personalInfo.website || personalInfo.linkedin || personalInfo.github) && (
              <div className={baseStyles['resume-section']}>
                <h3
                  className={`${baseStyles['resume-section-title-sm']} text-[var(--resume-accent-primary)]`}
                >
                  相关链接
                </h3>
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
 * Dynamic (custom) section wrapper for the Modern two-column template.
 * 视觉语言与 RM dynamic-resume-section.tsx 一致(base 类:h4 标题 + meta-sm 日期);
 * bullets 走两栏版 xs 字号。
 */
const DynamicResumeSectionModernTwoColumn: React.FC<{
  sectionMeta: SectionMeta
  resumeData: BuilderResumeData
  renderBullets: (items?: string[]) => React.ReactNode
}> = ({ sectionMeta, resumeData, renderBullets }) => {
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
              {(item.subtitle || item.location) && (
                <div
                  className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
                >
                  {item.subtitle && <span>{item.subtitle}</span>}
                  {item.location && <span>{item.location}</span>}
                </div>
              )}
              {renderBullets(item.description)}
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

export default ResumeModernTwoColumn
