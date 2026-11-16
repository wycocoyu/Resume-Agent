/**
 * Modern Resume Template —— 移植自 Resume-Matcher components/resume/resume-modern.tsx。
 *
 * Single-column layout with user-selectable accent colors.
 * Features colored section headers with underline and decorative name underline.
 * ATS-compatible: all visual elements are real DOM text nodes.
 * 强调色由外层 cssVars 注入(--resume-accent-primary / --resume-accent-light)。
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 新增 openSource section(复用 personalProjects 渲染,github → GitHub pill)
 * - skills / awards 渲染为 bullets(替代 RM 的 additional 行内分类;RM 源的
 *   additional case 与 AdditionalSection 组件为死代码,未移植)
 * - summary 为 bullets:单条=正文段,多条=列表
 * - education description 渲染为 bullets
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Linkedin, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Experience, Project, SectionMeta } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import baseStyles from './styles/_base.module.css'
import styles from './styles/modern.module.css'

interface ResumeModernProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeModern: React.FC<ResumeModernProps> = ({ data, showContactIcons = false }) => {
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

  const renderBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <ul className={`ml-4 ${baseStyles['resume-list']} ${baseStyles['resume-text-sm']}`}>
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

  // 项目类条目(personalProjects / openSource 共用):名称加粗 + 链接 pill + 日期右对齐
  const renderProjectItems = (projects?: Project[]) => {
    if (!projects || projects.length === 0) return null
    return (
      <div className={baseStyles['resume-items']}>
        {projects.map((project) => (
          <div key={project.id} className={baseStyles['resume-item']}>
            <div
              className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
            >
              <div className="flex items-baseline gap-2">
                <h4 className={baseStyles['resume-item-title']}>{project.name}</h4>
                {(project.github || project.website) && (
                  <span className="flex gap-1.5">
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
                        <Github size={10} />
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
                        <ExternalLink size={10} />
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
                <span className={`${baseStyles['resume-date']} ml-4`}>
                  {formatDateRange(project.years)}
                </span>
              )}
            </div>
            {project.role && (
              <div className={`${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}>
                <span>{project.role}</span>
              </div>
            )}
            {renderBullets(project.description)}
          </div>
        ))}
      </div>
    )
  }

  const renderExperienceSection = (keyId: string, title: string, items?: Experience[]) => {
    if (!items || items.length === 0) return null
    return (
      <div key={keyId} className={baseStyles['resume-section']}>
        <h3 className={styles['section-title-accent']}>{title}</h3>
        <div className={baseStyles['resume-items']}>
          {items.map((exp) => (
            <div key={exp.id} className={baseStyles['resume-item']}>
              <div
                className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
              >
                <h4 className={baseStyles['resume-item-title']}><InlineBold text={exp.title} /></h4>
                <span className={`${baseStyles['resume-date']} ml-4`}>
                  {formatDateRange(exp.years)}
                </span>
              </div>
              <div
                className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
              >
                <span className="inline-flex items-center">
                  <TemplateLogo url={exp.companyLogoUrl} size={exp.companyLogoSize} alt={exp.company} />
                  <InlineBold as="span" text={exp.company} weightControlled />
                </span>
                {exp.location && <span>{exp.location}</span>}
              </div>
              {renderBullets(exp.description)}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Render a section based on its key
  const renderSection = (section: SectionMeta) => {
    switch (section.key) {
      case 'personalInfo':
        // Personal info is the header - handled separately
        return null

      case 'summary':
        if (!summary || summary.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            {summary.length === 1 ? (
              <p className={`text-justify ${baseStyles['resume-text']}`}>
                <SafeHtml html={summary[0]} />
              </p>
            ) : (
              renderBullets(summary)
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
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            {renderProjectItems(personalProjects)}
          </div>
        )

      case 'openSource':
        if (!openSource || openSource.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            {renderProjectItems(openSource)}
          </div>
        )

      case 'education':
        if (!education || education.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {education.map((edu) => (
                <div key={edu.id} className={baseStyles['resume-item']}>
                  <div
                    className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
                  >
                    <h4 className={baseStyles['resume-item-title']}><TemplateLogo url={edu.schoolLogoUrl} size={edu.schoolLogoSize} alt={edu.institution} /><InlineBold text={edu.institution} /></h4>
                    <span className={`${baseStyles['resume-date']} ml-4`}>
                      {formatDateRange(edu.years)}
                    </span>
                  </div>
                  <div
                    className={`flex justify-between ${baseStyles['resume-item-subtitle']} ${baseStyles['resume-row-tight']}`}
                  >
                    <span>{edu.degree}</span>
                  </div>
                  {renderBullets(edu.description)}
                </div>
              ))}
            </div>
          </div>
        )

      case 'skills':
        if (!data.skills || data.skills.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            {renderBullets(data.skills)}
          </div>
        )

      case 'awards':
        if (!data.awards || data.awards.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            {renderBullets(data.awards)}
          </div>
        )

      default:
        // Custom section - render using DynamicResumeSectionModern
        if (!section.isDefault) {
          return (
            <DynamicResumeSectionModern
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderBullets={renderBullets}
            />
          )
        }
        return null
    }
  }

  return (
    <div className={styles.container}>
      {/* Header Section - Centered Layout (always first) */}
      {personalInfo && (
        <header className={`text-center ${baseStyles['resume-header']}`}>
          {/* Name - Centered */}
          {personalInfo.name && (
            <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>
              {personalInfo.name}
            </h1>
          )}

          {/* Decorative accent underline under name */}
          <div className={styles['name-underline']} aria-hidden="true" />

          {/* Title - Centered, below name */}
          {personalInfo.title && (
            <h2
              className={`${baseStyles['resume-title']} ${baseStyles['resume-meta']} tracking-wide uppercase mt-3 mb-3`}
            >
              {personalInfo.title}
            </h2>
          )}

          {/* Contact - Own line, centered */}
          <div
            className={`flex flex-wrap justify-center gap-x-1 gap-y-1 ${baseStyles['resume-meta']}`}
          >
            {renderContactDetail('Email', personalInfo.email, 'mailto:')}
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

      {/* Render sections in order based on sectionMeta */}
      {sortedSections
        .filter((section) => section.key !== 'personalInfo')
        .map((section) => renderSection(section))}
    </div>
  )
}

/**
 * Dynamic (custom) section wrapper for the Modern template.
 * Uses accent-colored section titles.
 */
const DynamicResumeSectionModern: React.FC<{
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
      <h3 className={styles['section-title-accent']}>{sectionMeta.displayName}</h3>
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
                  className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-meta']}`}
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

export default ResumeModern
