/**
 * LaTeX Resume Template —— 移植自 Resume-Matcher components/resume/resume-latex.tsx。
 *
 * Classic serif academic layout: centered small-caps name, Title-Case section headers
 * with a full-width rule, company-first two-line entries (company + dates, then italic
 * role + location). Single-typeface design driven by --header-font / --body-font.
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 新增 openSource section(复用 projects 渲染,repo → GitHub pill)
 * - skills / awards 渲染为 bullets(替代 RM 的 additional 行内分类)
 * - summary 为 bullets:单条=正文段,多条=列表
 * - education description 渲染为 bullets
 */
import React from 'react'
import { Mail, Phone, Globe, Linkedin, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Experience, Project, SectionMeta } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import baseStyles from './styles/_base.module.css'
import styles from './styles/latex.module.css'

interface ResumeLatexProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeLatex: React.FC<ResumeLatexProps> = ({ data, showContactIcons = false }) => {
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

  // LaTeX renders location as its own centered line, so it is not a contact-row item.
  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={12} />,
    Phone: <Phone size={12} />,
    Website: <Globe size={12} />,
    LinkedIn: <Linkedin size={12} />,
    GitHub: <Github size={12} />,
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

  // Build the contact row (phone, email, linkedin, github, website) joined by middots.
  const contactItems = [
    renderContactDetail('Phone', personalInfo?.phone, 'tel:'),
    renderContactDetail('Email', personalInfo?.email, 'mailto:'),
    renderContactDetail('LinkedIn', personalInfo?.linkedin),
    renderContactDetail('GitHub', personalInfo?.github),
    renderContactDetail('Website', personalInfo?.website),
  ].filter(Boolean)

  // Company-first entry header: bold company / bold dates, then italic role / italic location.
  const renderEntryHeader = (
    primary?: string,
    dates?: string,
    secondary?: string,
    location?: string,
    primaryWeightControlled?: boolean,
    logoUrl?: string,
    logoSize?: number
  ) => (
    <>
      <div className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}>
        <span className="inline-flex items-center min-w-0">
          <TemplateLogo url={logoUrl} size={logoSize} alt={primary} />
          <InlineBold as="span" className={styles.entryPrimary} text={primary} weightControlled={primaryWeightControlled} />
        </span>
        {dates && <span className={`${styles.entryDates} ml-4`}>{formatDateRange(dates)}</span>}
      </div>
      {(secondary || location) && (
        <div className={`flex justify-between items-baseline ${baseStyles['resume-row']}`}>
          {secondary && <InlineBold as="span" className={styles.entrySecondary} text={secondary} />}
          {location && <span className={`${styles.entrySecondary} ml-4`}>{location}</span>}
        </div>
      )}
    </>
  )

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

  // 项目类条目(personalProjects / openSource 共用):名称加粗 + 链接 pill + 日期加粗右对齐
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
                <span className={styles.entryPrimary}>{project.name}</span>
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
                <span className={`${styles.entryDates} ml-4`}>
                  {formatDateRange(project.years)}
                </span>
              )}
            </div>
            {project.role && (
              <div className={baseStyles['resume-row']}>
                <span className={styles.entrySecondary}>{project.role}</span>
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
        <h3 className={styles.sectionTitle}>{title}</h3>
        <div className={baseStyles['resume-items']}>
          {items.map((exp) => (
            <div key={exp.id} className={baseStyles['resume-item']}>
              {renderEntryHeader(exp.company, exp.years, exp.title, exp.location, true, exp.companyLogoUrl, exp.companyLogoSize)}
              {renderBullets(exp.description)}
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

      case 'education':
        if (!education || education.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {education.map((edu) => (
                <div key={edu.id} className={baseStyles['resume-item']}>
                  {renderEntryHeader(edu.institution, edu.years, edu.degree, undefined, undefined, edu.schoolLogoUrl, edu.schoolLogoSize)}
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
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            {renderBullets(data.skills)}
          </div>
        )

      case 'awards':
        if (!data.awards || data.awards.length === 0) return null
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            {renderBullets(data.awards)}
          </div>
        )

      default:
        if (!section.isDefault) {
          return (
            <DynamicResumeSectionLatex
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
      {personalInfo && (
        <header className={`relative text-center ${baseStyles['resume-header']}`}>
          {/* 照片右上角叠加，不改变居中版式（与 Classic LaTeX 渲染一致的位置语义） */}
          {personalInfo.photo && (
            <img
              src={personalInfo.photo}
              alt={personalInfo.name || '照片'}
              className="absolute right-0 top-0 w-[72px] h-[90px] object-cover border border-neutral-400"
            />
          )}
          {personalInfo.name && <h1 className={`${styles.name} mb-1`}>{personalInfo.name}</h1>}
          {personalInfo.title && (
            <div className={`${styles.tagline} mb-1`}>{personalInfo.title}</div>
          )}
          {personalInfo.location && (
            <div className={`${styles.locationLine} mb-1`}>{personalInfo.location}</div>
          )}
          {contactItems.length > 0 && (
            <div
              className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 ${styles.contactRow}`}
            >
              {contactItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && <span className={styles.contactSep}>·</span>}
                  {item}
                </React.Fragment>
              ))}
            </div>
          )}
        </header>
      )}

      {sortedSections
        .filter((section) => section.key !== 'personalInfo')
        .map((section) => renderSection(section))}
    </div>
  )
}

/**
 * Dynamic (custom) section wrapper for the LaTeX template.
 */
const DynamicResumeSectionLatex: React.FC<{
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
      <h3 className={styles.sectionTitle}>{sectionMeta.displayName}</h3>
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
                <span className={styles.entryPrimary}>{item.title}</span>
                {item.years && (
                  <span className={`${styles.entryDates} ml-4`}>{formatDateRange(item.years)}</span>
                )}
              </div>
              {(item.subtitle || item.location) && (
                <div className={`flex justify-between items-baseline ${baseStyles['resume-row']}`}>
                  {item.subtitle && <span className={styles.entrySecondary}>{item.subtitle}</span>}
                  {item.location && (
                    <span className={`${styles.entrySecondary} ml-4`}>{item.location}</span>
                  )}
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

export default ResumeLatex
