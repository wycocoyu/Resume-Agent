/**
 * Clean Resume Template —— 移植自 Resume-Matcher components/resume/resume-clean.tsx。
 *
 * Minimal modern sans layout: centered light-weight name, a single pipe-separated
 * contact line, large understated gray UPPERCASE section headers with a thin rule,
 * and single-line entries (COMPANY | Role on the left, Location | Dates on the right).
 * Single-typeface design driven by --header-font / --body-font.
 *
 * 与 RM 源的差异(数据模型适配,视觉不变):
 * - 新增 openSource section(复用 projects 渲染,repo → GitHub pill)
 * - skills / awards 渲染为 bullets(替代 RM 的 additional 行内分类;additional/AdditionalSection 为死代码,不移植)
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
import styles from './styles/clean.module.css'

interface ResumeCleanProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeClean: React.FC<ResumeCleanProps> = ({ data, showContactIcons = false }) => {
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

  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={12} />,
    Phone: <Phone size={12} />,
    Location: <MapPin size={12} />,
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

  const contactItems = [
    renderContactDetail('Location', personalInfo?.location),
    renderContactDetail('Phone', personalInfo?.phone, 'tel:'),
    renderContactDetail('Email', personalInfo?.email, 'mailto:'),
    renderContactDetail('LinkedIn', personalInfo?.linkedin),
    renderContactDetail('GitHub', personalInfo?.github),
    renderContactDetail('Website', personalInfo?.website),
  ].filter(Boolean)

  // Single-line entry header: COMPANY | Role (left), Location | Dates (right).
  const renderEntryHeader = (
    primary?: string,
    role?: string,
    location?: string,
    dates?: string,
    primaryWeightControlled?: boolean,
    logoUrl?: string,
    logoSize?: number
  ) => {
    const meta = [location, dates ? formatDateRange(dates) : undefined].filter(Boolean).join(' | ')
    return (
      <div
        className={`flex justify-between items-baseline gap-3 ${baseStyles['resume-row-tight']}`}
      >
        <span className="min-w-0">
          <TemplateLogo url={logoUrl} size={logoSize} alt={primary} />
          <InlineBold as="span" className={styles.entryCompany} text={primary} weightControlled={primaryWeightControlled} />
          {role && (
            <>
              <span className={styles.sep}>|</span>
              <InlineBold as="span" className={styles.entryRole} text={role} />
            </>
          )}
        </span>
        {meta && <span className={styles.entryMeta}>{meta}</span>}
      </div>
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

  // 项目类条目(personalProjects / openSource 共用):名称加粗 + 小型大写 role + 链接 pill + 日期右对齐
  const renderProjectItems = (projects?: Project[]) => {
    if (!projects || projects.length === 0) return null
    return (
      <div className={baseStyles['resume-items']}>
        {projects.map((project) => (
          <div key={project.id} className={baseStyles['resume-item']}>
            <div
              className={`flex justify-between items-baseline gap-3 ${baseStyles['resume-row-tight']}`}
            >
              <span className="flex items-baseline gap-2 min-w-0">
                <span className={styles.entryCompany}>{project.name}</span>
                {project.role && (
                  <>
                    <span className={styles.sep}>|</span>
                    <span className={styles.entryRole}>{project.role}</span>
                  </>
                )}
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
              </span>
              {project.years && (
                <span className={styles.entryMeta}>{formatDateRange(project.years)}</span>
              )}
            </div>
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
              {renderEntryHeader(exp.company, exp.title, exp.location, exp.years, true, exp.companyLogoUrl, exp.companyLogoSize)}
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
                  {renderEntryHeader(edu.institution, edu.degree, undefined, edu.years, undefined, edu.schoolLogoUrl, edu.schoolLogoSize)}
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
            <DynamicResumeSectionClean
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderBullets={renderBullets}
              renderEntryHeader={renderEntryHeader}
            />
          )
        }
        return null
    }
  }

  return (
    <div className={styles.container}>
      {personalInfo && (
        <header className={`text-center ${baseStyles['resume-header']}`}>
          {personalInfo.name && <h1 className={`${styles.name} mb-1`}>{personalInfo.name}</h1>}
          {personalInfo.title && (
            <div className={`${styles.tagline} mb-1`}>{personalInfo.title}</div>
          )}
          {contactItems.length > 0 && (
            <div
              className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 ${styles.contactRow}`}
            >
              {contactItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && <span className={styles.sep}>|</span>}
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
 * Dynamic (custom) section wrapper for the Clean template.
 */
const DynamicResumeSectionClean: React.FC<{
  sectionMeta: SectionMeta
  resumeData: BuilderResumeData
  renderBullets: (items?: string[]) => React.ReactNode
  renderEntryHeader: (
    primary?: string,
    role?: string,
    location?: string,
    dates?: string,
    primaryWeightControlled?: boolean,
    logoUrl?: string,
    logoSize?: number
  ) => React.ReactNode
}> = ({ sectionMeta, resumeData, renderBullets, renderEntryHeader }) => {
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
              {renderEntryHeader(item.title, item.subtitle, item.location, item.years)}
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

export default ResumeClean
