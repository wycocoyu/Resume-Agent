/**
 * ASu 18 套变体原子模板实现
 * 规范实现：Issue #45, #72（对齐 Hisn00w/ASu-skills 01..18-大厂极简简历模板.html 与 frame/base.css）
 */
import React from 'react'
import { Mail, Phone, MapPin, Github, Globe } from 'lucide-react'
import type { BuilderResumeData, Project, Experience, Education, CustomSectionItem } from '../types'
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
  showEnglish?: boolean
  hasModernIndex?: boolean
  isTwoPage?: boolean
}

export const ASU_VARIANTS_CONFIG: Record<AsuVariantId, VariantConfig> = {
  'asu-01': { layout: 'single-column', classNames: [styles.variantBlueLine] },
  'asu-02': { layout: 'single-column', classNames: [styles.variantBand] },
  'asu-03': { layout: 'single-column', classNames: [styles.variantEnglish, styles.wideHeader, styles.variantTimeline], hasTimeline: true, showEnglish: true },
  'asu-04': { layout: 'single-column', classNames: [styles.variantTopBanner], hasTopBanner: true },
  'asu-05': { layout: 'sidebar', classNames: [styles.variantGray, styles.variantSidebar] },
  'asu-06': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantTimeline, styles.variantTwoPage], hasTimeline: true, isTwoPage: true },
  'asu-07': { layout: 'single-column', classNames: [styles.variantRightRail] },
  'asu-08': { layout: 'two-column', classNames: [styles.variantBand, styles.variantTwoPage], isTwoPage: true },
  'asu-09': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantCards, styles.variantTwoPage], isTwoPage: true },
  'asu-10': { layout: 'single-column', classNames: [styles.variantRibbon], showEnglish: true },
  'asu-11': { layout: 'single-column', classNames: [styles.variantGray, styles.variantSerif, styles.variantSplit] },
  'asu-12': { layout: 'single-column', classNames: [styles.variantCentered, styles.variantCompact, styles.variantTwoPage], showEnglish: true, isTwoPage: true },
  'asu-13': { layout: 'sidebar', classNames: [styles.variantBlack, styles.variantCompact, styles.variantSidebar] },
  'asu-14': { layout: 'two-column', classNames: [styles.variantBlueLine, styles.variantCompact, styles.variantTwoPage], isTwoPage: true },
  'asu-15': { layout: 'single-column', classNames: [styles.variantBand, styles.variantModern], hasModernIndex: true },
  'asu-16': { layout: 'two-column', classNames: [styles.variantDense, styles.variantTwoPage], isTwoPage: true },
  'asu-17': { layout: 'single-column', classNames: [styles.variantBlack, styles.variantCompact, styles.variantTwoPage, styles.variantAcademic, styles.variantSerif], showEnglish: true, isTwoPage: true },
  'asu-18': { layout: 'single-column', classNames: [styles.variantBlueLine, styles.variantCompact, styles.variantTwoPage, styles.variantModern], hasModernIndex: true, isTwoPage: true },
}

const SECTION_EN_MAP: Record<string, string> = {
  education: 'Education',
  workExperience: 'Experience',
  personalProjects: 'Projects',
  openSource: 'Open Source',
  skills: 'Skills',
  awards: 'Honors & Awards',
  summary: 'Summary',
}

const SHORT_ROLE_MAX_LEN = 24
const SENTENCE_PUNCT_RE = /[。！？；;\n]/

function isShortRole(role?: string): boolean {
  if (!role || typeof role !== 'string') return false
  const trimmed = role.trim()
  return trimmed.length > 0 && trimmed.length <= SHORT_ROLE_MAX_LEN && !SENTENCE_PUNCT_RE.test(trimmed)
}

function normalizeSectionTitle(displayName?: string, fallback?: string): string {
  const raw = (displayName || fallback || '').trim()
  if (!raw) return fallback || ''
  return raw.split(' / ')[0].trim() || raw
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
  const {
    personalInfo,
    summary,
    workExperience,
    fullTimeExperience,
    internships,
    education,
    personalProjects,
    openSource,
    skills,
    awards,
    customSections,
  } = data
  const internshipItems = internships !== undefined ? internships : workExperience
  const config = ASU_VARIANTS_CONFIG[variantId] || ASU_VARIANTS_CONFIG['asu-01']
  const sortedSections = getSortedSections(data)

  const renderSectionTitle = (title: string, secKey: string, idx: number) => {
    const numPrefix = config.hasModernIndex ? (
      <span className={styles.sectionNum}>{String(idx + 1).padStart(2, '0')}</span>
    ) : null
    const enLabel = config.showEnglish ? SECTION_EN_MAP[secKey] : undefined
    return (
      <h2 className={styles.sectionTitle}>
        <span className={styles.sectionMain}>
          {numPrefix}
          <span>{title}</span>
        </span>
        {enLabel && <span className={styles.sectionEn}>{enLabel}</span>}
      </h2>
    )
  }

  const renderBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    const valid = items.filter((b): b is string => typeof b === 'string' && b.trim().length > 0)
    if (valid.length === 0) return null
    return (
      <ul className={styles.bulletList}>
        {valid.map((bullet, idx) => {
          const isNested = bullet.startsWith('  ') || bullet.startsWith('\t') || bullet.trimStart().startsWith('○')
          const cleanText = bullet.replace(/^[\s\t]*[○▪]\s*/, '').trim()
          if (!cleanText) return null
          return (
            <li key={idx} className={isNested ? `${styles.bulletItem} ${styles.nested}` : styles.bulletItem}>
              <SafeHtml html={cleanText} />
            </li>
          )
        })}
      </ul>
    )
  }

  const renderWorkExperience = (items?: Experience[], title = '实习经历', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, 'workExperience', idx)}
        <div className={config.hasTimeline ? styles.timelineContainer : undefined}>
          {items.map((exp) => {
            const dateStr = formatDateRange(exp.years)
            return (
              <div key={exp.id} data-no-break="true" className={styles.entryItem}>
                <div className={dateStr ? styles.entryHead : `${styles.entryHead} ${styles.entryHeadNoDate}`}>
                  {dateStr && <span className={styles.entryDate}>{dateStr}</span>}
                  <span className={styles.entryOrg}>
                    {exp.companyLogoUrl && (
                      <TemplateLogo
                        src={exp.companyLogoUrl}
                        alt={exp.company || 'Company'}
                        size={20}
                      />
                    )}
                    <InlineBold text={exp.company || ''} />
                  </span>
                  {exp.title && <span className={styles.entryRole}>{exp.title}</span>}
                </div>
                {renderBullets(exp.description)}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const renderEducation = (items?: Education[], title = '教育背景', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, 'education', idx)}
        {items.map((edu) => {
          const dateStr = formatDateRange(edu.years)
          return (
            <div key={edu.id} data-no-break="true" className={styles.entryItem}>
              <div className={dateStr ? styles.entryHead : `${styles.entryHead} ${styles.entryHeadNoDate}`}>
                {dateStr && <span className={styles.entryDate}>{dateStr}</span>}
                <span className={styles.entryOrg}>
                  {edu.schoolLogoUrl && (
                    <TemplateLogo
                      src={edu.schoolLogoUrl}
                      alt={edu.institution || 'School'}
                      size={20}
                    />
                  )}
                  <InlineBold text={edu.institution || ''} />
                </span>
                {edu.degree && <span className={styles.entryRole}>{edu.degree}</span>}
              </div>
              {renderBullets(edu.description)}
            </div>
          )
        })}
      </div>
    )
  }

  const renderProjects = (items?: Project[], title = '项目经历', secKey = 'personalProjects', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, secKey, idx)}
        <div className={config.hasTimeline ? styles.timelineContainer : undefined}>
          {items.map((proj) => {
            const roleText = proj.role?.trim() || ''
            const shortRoleText = isShortRole(roleText) ? roleText : ''
            const longRoleText = roleText && !shortRoleText ? roleText : ''
            const dateStr = formatDateRange(proj.years)

            return (
              <div key={proj.id} data-no-break="true" className={styles.entryItem}>
                <div className={dateStr ? styles.entryHead : `${styles.entryHead} ${styles.entryHeadNoDate}`}>
                  {dateStr && <span className={styles.entryDate}>{dateStr}</span>}
                  <span className={styles.entryOrg}>
                    {proj.name}
                    {(proj.github || proj.website) && (
                      <a
                        href={(proj.github || proj.website)!.startsWith('http') ? (proj.github || proj.website)! : `https://${proj.github || proj.website}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-current opacity-70 hover:opacity-100"
                      >
                        <Github size={12} />
                      </a>
                    )}
                  </span>
                  {shortRoleText && <span className={styles.entryRole}>{shortRoleText}</span>}
                </div>
                {longRoleText && <div className={styles.entryOverview}>{longRoleText}</div>}
                {renderBullets(proj.description)}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const renderSkills = (items?: string[], title = '专业技能', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, 'skills', idx)}
        {renderBullets(items)}
      </div>
    )
  }

  const renderAwards = (items?: string[], title = '荣誉奖项', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, 'awards', idx)}
        {renderBullets(items)}
      </div>
    )
  }

  const renderSummary = (items?: string[], title = '自我评价', idx = 0) => {
    const valid = (items || []).filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
    if (valid.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, 'summary', idx)}
        {valid.length === 1 ? (
          <p className={styles.sectionCopy}>
            <SafeHtml html={valid[0].trim()} />
          </p>
        ) : (
          renderBullets(valid)
        )}
      </div>
    )
  }

  const renderCustomSection = (items?: CustomSectionItem[], title = '其他经历', secKey = 'custom', idx = 0) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        {renderSectionTitle(title, secKey, idx)}
        {items.map((item) => {
          const dateStr = formatDateRange(item.years)
          return (
            <div key={item.id} data-no-break="true" className={styles.entryItem}>
              <div className={dateStr ? styles.entryHead : `${styles.entryHead} ${styles.entryHeadNoDate}`}>
                {dateStr && <span className={styles.entryDate}>{dateStr}</span>}
                <span className={styles.entryOrg}>
                  <InlineBold text={item.title || ''} />
                </span>
                {item.subtitle && <span className={styles.entryRole}>{item.subtitle}</span>}
              </div>
              {renderBullets(item.description)}
            </div>
          )
        })}
      </div>
    )
  }

  const headerElement = (
    <div className={`${styles.headerBlock} ${config.hasTopBanner ? styles.topBanner : ''}`}>
      <div className={styles.identity}>
        <h1 className={styles.candidateName}>{personalInfo?.name || 'Your Name'}</h1>
        {personalInfo?.title && <div className={styles.candidateTitle}>{personalInfo.title}</div>}
        <div className={styles.contactGrid}>
          {personalInfo?.phone && (
            <span className={styles.metaItem}>
              {showContactIcons && <Phone size={11} />}
              <span>{personalInfo.phone}</span>
            </span>
          )}
          {personalInfo?.email && (
            <span className={styles.metaItem}>
              {showContactIcons && <Mail size={11} />}
              <span>{personalInfo.email}</span>
            </span>
          )}
          {personalInfo?.location && (
            <span className={styles.metaItem}>
              {showContactIcons && <MapPin size={11} />}
              <span>{personalInfo.location}</span>
            </span>
          )}
          {personalInfo?.github && (
            <span className={styles.metaItem}>
              {showContactIcons && <Github size={11} />}
              <span>{personalInfo.github.replace(/^https?:\/\//, '')}</span>
            </span>
          )}
          {personalInfo?.website && (
            <span className={styles.metaItem}>
              {showContactIcons && <Globe size={11} />}
              <span>{personalInfo.website.replace(/^https?:\/\//, '')}</span>
            </span>
          )}
        </div>
      </div>
      {personalInfo?.photo && (
        <figure className={styles.photoFrame}>
          <img src={personalInfo.photo} alt="Profile" className={styles.photoImg} />
        </figure>
      )}
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
            {renderEducation(education, '教育背景', 0)}
            {renderSkills(skills, '专业技能', 1)}
            {renderAwards(awards, '荣誉奖项', 2)}
          </div>
          <div className={styles.sidebarContent}>
            {fullTimeExperience?.length ? renderWorkExperience(fullTimeExperience, '工作经历', 0) : null}
            {renderWorkExperience(internshipItems, '实习经历', 0)}
            {renderProjects(personalProjects, '项目经历', 'personalProjects', 1)}
            {renderProjects(openSource, '开源经历', 'openSource', 2)}
            {renderSummary(summary, '自我评价', 3)}
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
            {fullTimeExperience?.length ? renderWorkExperience(fullTimeExperience, '工作经历', 0) : null}
            {renderWorkExperience(internshipItems, '实习经历', 0)}
            {renderProjects(personalProjects, '项目经历', 'personalProjects', 1)}
          </div>
          <div className={styles.colRight}>
            {renderEducation(education, '教育背景', 0)}
            {renderSkills(skills, '专业技能', 1)}
            {renderProjects(openSource, '开源经历', 'openSource', 2)}
            {renderAwards(awards, '荣誉奖项', 3)}
            {renderSummary(summary, '自我评价', 4)}
          </div>
        </div>
      </div>
    )
  }

  const renderedSections = sortedSections.reduce<React.ReactNode[]>((acc, sec) => {
    const idx = acc.length
    let node: React.ReactNode = null
    switch (sec.key) {
      case 'education':
        node = renderEducation(education, normalizeSectionTitle(sec.displayName, '教育背景'), idx)
        break
      case 'fullTimeExperience':
        node = renderWorkExperience(fullTimeExperience, normalizeSectionTitle(sec.displayName, '工作经历'), idx)
        break
      case 'workExperience':
        node = renderWorkExperience(internshipItems, normalizeSectionTitle(sec.displayName, '实习经历'), idx)
        break
      case 'personalProjects':
        node = renderProjects(personalProjects, normalizeSectionTitle(sec.displayName, '项目经历'), 'personalProjects', idx)
        break
      case 'openSource':
        node = renderProjects(openSource, normalizeSectionTitle(sec.displayName, '开源经历'), 'openSource', idx)
        break
      case 'skills':
        node = renderSkills(skills, normalizeSectionTitle(sec.displayName, '专业技能'), idx)
        break
      case 'awards':
        node = renderAwards(awards, normalizeSectionTitle(sec.displayName, '荣誉奖项'), idx)
        break
      case 'summary':
        node = renderSummary(summary, normalizeSectionTitle(sec.displayName, '自我评价'), idx)
        break
      default: {
        const custom = customSections?.[sec.key]
        if (custom?.items?.length) {
          node = renderCustomSection(custom.items, normalizeSectionTitle(sec.displayName, sec.key), sec.key, idx)
        }
        break
      }
    }
    if (node) {
      acc.push(<React.Fragment key={sec.id}>{node}</React.Fragment>)
    }
    return acc
  }, [])

  return (
    <div className={containerClasses}>
      {headerElement}
      <div className={styles.layoutSingleColumn}>
        {renderedSections}
      </div>
    </div>
  )
}

export default ResumeAsuVariant
