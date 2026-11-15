/**
 * ASu 18 套变体原子模板实现
 * 规范实现：Issue #45
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Project, Experience, Education } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import type { AsuVariantId } from '../settings'
import styles from './styles/asuVariants.module.css'

interface VariantConfig {
  layout: 'single-column' | 'sidebar' | 'two-column'
  classNames: string[]
  hasTimeline?: boolean
  hasTopBanner?: boolean
  isTwoPage?: boolean
}

export const ASU_VARIANTS_CONFIG: Record<AsuVariantId, VariantConfig> = {
  'asu-01': { layout: 'single-column', classNames: [styles.variantBlueLine] },
  'asu-02': { layout: 'single-column', classNames: [styles.variantBand] },
  'asu-03': { layout: 'single-column', classNames: [styles.variantTimeline], hasTimeline: true },
  'asu-04': { layout: 'single-column', classNames: [styles.variantTopBanner], hasTopBanner: true },
  'asu-05': { layout: 'sidebar', classNames: [styles.variantSidebar] },
  'asu-06': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantTimeline, styles.variantTwoPage], hasTimeline: true, isTwoPage: true },
  'asu-07': { layout: 'single-column', classNames: [styles.variantRightRail] },
  'asu-08': { layout: 'two-column', classNames: [styles.variantBand, styles.variantTwoPage], isTwoPage: true },
  'asu-09': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantCards, styles.variantTwoPage], isTwoPage: true },
  'asu-10': { layout: 'single-column', classNames: [styles.variantRibbon] },
  'asu-11': { layout: 'single-column', classNames: [styles.variantSerif] },
  'asu-12': { layout: 'single-column', classNames: [styles.variantCentered, styles.variantTwoPage], isTwoPage: true },
  'asu-13': { layout: 'sidebar', classNames: [styles.variantBlack, styles.variantSidebar] },
  'asu-14': { layout: 'two-column', classNames: [styles.variantBlueLine, styles.variantTwoPage], isTwoPage: true },
  'asu-15': { layout: 'single-column', classNames: [styles.variantBand, styles.variantModern] },
  'asu-16': { layout: 'two-column', classNames: [styles.variantDense, styles.variantTwoPage], isTwoPage: true },
  'asu-17': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantSerif, styles.variantTwoPage], isTwoPage: true },
  'asu-18': { layout: 'single-column', classNames: [styles.variantBlueLine, styles.variantModern, styles.variantTwoPage], isTwoPage: true },
}

interface ResumeAsuVariantProps {
  data: BuilderResumeData
  variantId: AsuVariantId
  showContactIcons?: boolean
}

export const ResumeAsuVariant: React.FC<ResumeAsuVariantProps> = ({
  data,
  variantId,
  showContactIcons = true,
}) => {
  const { personalInfo, summary, workExperience, education, personalProjects, openSource, skills, awards } = data
  const config = ASU_VARIANTS_CONFIG[variantId] || ASU_VARIANTS_CONFIG['asu-01']
  const sortedSections = getSortedSections(data)

  const renderBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <ul className={styles.bulletList}>
        {items.map((bullet, idx) => {
          if (!bullet || typeof bullet !== 'string') return null
          return (
            <li key={idx} className={styles.bulletItem}>
              <SafeHtml html={bullet.trim()} />
            </li>
          )
        })}
      </ul>
    )
  }

  const renderWorkExperience = (items?: Experience[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>工作与实习经历 / Experience</div>
        <div className={config.hasTimeline ? styles.timelineContainer : undefined}>
          {items.map((exp) => (
            <div key={exp.id} className={config.hasTimeline ? styles.timelineNode : undefined}>
              <div className={styles.itemBar}>
                <div className={styles.itemMain}>
                  {exp.companyLogoUrl && (
                    <TemplateLogo
                      src={exp.companyLogoUrl}
                      alt={exp.company || 'Company'}
                      size={20}
                    />
                  )}
                  <InlineBold text={exp.company || ''} />
                  {exp.title && <span className={styles.itemSub}>({exp.title})</span>}
                </div>
                <div className={styles.itemDate}>{formatDateRange(exp.years)}</div>
              </div>
              {renderBullets(exp.description)}
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderEducation = (items?: Education[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>教育背景 / Education</div>
        {items.map((edu) => (
          <div key={edu.id}>
            <div className={styles.itemBar}>
              <div className={styles.itemMain}>
                {edu.schoolLogoUrl && (
                  <TemplateLogo
                    src={edu.schoolLogoUrl}
                    alt={edu.institution || 'School'}
                    size={20}
                  />
                )}
                <InlineBold text={edu.institution || ''} />
                {edu.degree && <span className={styles.itemSub}>({edu.degree})</span>}
              </div>
              <div className={styles.itemDate}>{formatDateRange(edu.years)}</div>
            </div>
            {renderBullets(edu.description)}
          </div>
        ))}
      </div>
    )
  }

  const renderProjects = (items?: Project[], title: string = '项目经历 / Projects') => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>{title}</div>
        <div className={config.hasTimeline ? styles.timelineContainer : undefined}>
          {items.map((proj) => (
            <div key={proj.id} className={config.hasTimeline ? styles.timelineNode : undefined}>
              <div className={styles.itemBar}>
                <div className={styles.itemMain}>
                  <span>{proj.name}</span>
                  {proj.role && <span className={styles.itemSub}>({proj.role})</span>}
                </div>
                <div className={styles.itemDate}>{formatDateRange(proj.years)}</div>
              </div>
              {renderBullets(proj.description)}
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderSkills = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>专业技能 / Skills</div>
        {renderBullets(items)}
      </div>
    )
  }

  const renderAwards = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>荣誉奖项 / Awards</div>
        {renderBullets(items)}
      </div>
    )
  }

  const renderSummary = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>自我评价 / Summary</div>
        {renderBullets(items)}
      </div>
    )
  }

  const headerElement = (
    <div className={`${styles.headerBlock} ${config.hasTopBanner ? styles.topBanner : ''}`}>
      <h1 className={styles.candidateName}>{personalInfo?.name || 'Your Name'}</h1>
      {personalInfo?.title && <div className={styles.candidateTitle}>{personalInfo.title}</div>}
      <div className={styles.metaRow}>
        {personalInfo?.phone && (
          <span className={styles.metaItem}>
            {showContactIcons && <Phone size={10} />}
            <span>{personalInfo.phone}</span>
          </span>
        )}
        {personalInfo?.email && (
          <span className={styles.metaItem}>
            {showContactIcons && <Mail size={10} />}
            <span>{personalInfo.email}</span>
          </span>
        )}
        {personalInfo?.location && (
          <span className={styles.metaItem}>
            {showContactIcons && <MapPin size={10} />}
            <span>{personalInfo.location}</span>
          </span>
        )}
        {personalInfo?.github && (
          <span className={styles.metaItem}>
            {showContactIcons && <Github size={10} />}
            <span>{personalInfo.github.replace(/^https?:\/\//, '')}</span>
          </span>
        )}
      </div>
    </div>
  )

  const containerClasses = [
    styles.container,
    ...(config.classNames || []),
  ].join(' ')

  if (config.layout === 'sidebar') {
    return (
      <div className={containerClasses}>
        <div className={styles.layoutSidebar}>
          <div className={styles.sidebar}>
            {headerElement}
            {renderEducation(education)}
            {renderSkills(skills)}
            {renderAwards(awards)}
          </div>
          <div className={styles.sidebarContent}>
            {renderWorkExperience(workExperience)}
            {renderProjects(personalProjects, '项目经历 / Projects')}
            {renderProjects(openSource, '开源经历 / Open Source')}
            {renderSummary(summary)}
          </div>
        </div>
      </div>
    )
  }

  if (config.layout === 'two-column') {
    return (
      <div className={containerClasses}>
        {headerElement}
        <div className={styles.layoutTwoColumn}>
          <div className={styles.colLeft}>
            {renderWorkExperience(workExperience)}
            {renderProjects(personalProjects, '项目经历 / Projects')}
          </div>
          <div className={styles.colRight}>
            {renderEducation(education)}
            {renderSkills(skills)}
            {renderProjects(openSource, '开源经历 / Open Source')}
            {renderAwards(awards)}
            {renderSummary(summary)}
          </div>
        </div>
      </div>
    )
  }

  // Single-column default
  return (
    <div className={containerClasses}>
      {headerElement}
      <div className={styles.layoutSingleColumn}>
        {sortedSections.map((sec) => {
          switch (sec.key) {
            case 'education':
              return <React.Fragment key={sec.id}>{renderEducation(education)}</React.Fragment>
            case 'workExperience':
              return <React.Fragment key={sec.id}>{renderWorkExperience(workExperience)}</React.Fragment>
            case 'personalProjects':
              return <React.Fragment key={sec.id}>{renderProjects(personalProjects, `${sec.displayName} / Projects`)}</React.Fragment>
            case 'openSource':
              return <React.Fragment key={sec.id}>{renderProjects(openSource, `${sec.displayName} / Open Source`)}</React.Fragment>
            case 'skills':
              return <React.Fragment key={sec.id}>{renderSkills(skills)}</React.Fragment>
            case 'awards':
              return <React.Fragment key={sec.id}>{renderAwards(awards)}</React.Fragment>
            case 'summary':
              return <React.Fragment key={sec.id}>{renderSummary(summary)}</React.Fragment>
            default:
              return null
          }
        })}
      </div>
    </div>
  )
}

export default ResumeAsuVariant
