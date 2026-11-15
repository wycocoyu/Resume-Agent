/**
/**
 * ASu-Tech 单栏高密度技术简历模板
 * 规范实现：Issue #43, #44
 */
import React from 'react'
import { Mail, Phone, MapPin, Globe, Github, ExternalLink } from 'lucide-react'
import type { BuilderResumeData, Project, Experience, Education } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import styles from './styles/asuTech.module.css'

interface ResumeAsuTechProps {
  data: BuilderResumeData
  showContactIcons?: boolean
}

export const ResumeAsuTech: React.FC<ResumeAsuTechProps> = ({
  data,
  showContactIcons = true,
}) => {
  const { personalInfo, summary, workExperience, education, personalProjects, openSource, skills, awards } = data
  const sortedSections = getSortedSections(data)

  const renderBullets = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <ul className={styles.bulletList}>
        {items.map((bullet, idx) => {
          if (!bullet || typeof bullet !== 'string') return null
          const isNested = bullet.startsWith('  ') || bullet.startsWith('\t')
          const isNestedDeep = bullet.startsWith('    ') || bullet.startsWith('\t\t')
          const cleanText = bullet.trim()
          const itemClass = isNestedDeep
            ? `${styles.bulletItem} ${styles.nestedDeep}`
            : isNested
            ? `${styles.bulletItem} ${styles.nested}`
            : styles.bulletItem

          return (
            <li key={idx} className={itemClass}>
              <SafeHtml html={cleanText} />
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
        <div className={styles.sectionTitle}>
          <span>工作与实习经历 / Work Experience</span>
        </div>
        {items.map((exp) => (
          <div key={exp.id} className={styles.experienceItem}>
            <div className={styles.companyBar}>
              <div className={styles.companyBarLeft}>
                {exp.companyLogoUrl ? (
                  <TemplateLogo
                    src={exp.companyLogoUrl}
                    alt={exp.company || 'Company'}
                    size={exp.companyLogoSize || 27}
                    className={styles.companyLogo}
                  />
                ) : null}
                <span className={styles.institutionName}>
                  <InlineBold text={exp.company || ''} />
                </span>
                {exp.title && (
                  <span className={styles.institutionSubtitle}>| {exp.title}</span>
                )}
                {exp.location && (
                  <span className={styles.institutionSubtitle}>({exp.location})</span>
                )}
              </div>
              <div className={styles.entryDate}>{formatDateRange(exp.years)}</div>
            </div>
            {renderBullets(exp.description)}
          </div>
        ))}
      </div>
    )
  }

  const renderEducation = (items?: Education[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>
          <span>教育背景 / Education</span>
        </div>
        {items.map((edu) => (
          <div key={edu.id} className={styles.educationItem}>
            <div className={styles.companyBar}>
              <div className={styles.companyBarLeft}>
                {edu.schoolLogoUrl ? (
                  <TemplateLogo
                    src={edu.schoolLogoUrl}
                    alt={edu.institution || 'School'}
                    size={edu.schoolLogoSize || 27}
                    className={styles.companyLogo}
                  />
                ) : null}
                <span className={styles.institutionName}>
                  <InlineBold text={edu.institution || ''} />
                </span>
                {edu.degree && (
                  <span className={styles.institutionSubtitle}>| {edu.degree}</span>
                )}
              </div>
              <div className={styles.entryDate}>{formatDateRange(edu.years)}</div>
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
        <div className={styles.sectionTitle}>
          <span>{title}</span>
        </div>
        {items.map((proj) => (
          <div key={proj.id} className={styles.projectEntry}>
            <div className={styles.projectHeader}>
              <div className={styles.projectTitleRow}>
                <span className={styles.projectTitle}>{proj.name}</span>
                {proj.role && <span className={styles.projectRole}>({proj.role})</span>}
                {proj.github && (
                  <a
                    href={proj.github.startsWith('http') ? proj.github : `https://${proj.github}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.projectLinkPill}
                  >
                    <Github size={11} />
                    <span>GitHub</span>
                  </a>
                )}
                {proj.website && (
                  <a
                    href={proj.website.startsWith('http') ? proj.website : `https://${proj.website}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.projectLinkPill}
                  >
                    <ExternalLink size={11} />
                    <span>Demo</span>
                  </a>
                )}
              </div>
              <div className={styles.entryDate}>{formatDateRange(proj.years)}</div>
            </div>
            {renderBullets(proj.description)}
          </div>
        ))}
      </div>
    )
  }

  const renderSkills = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>
          <span>专业技能 / Technical Skills</span>
        </div>
        {renderBullets(items)}
      </div>
    )
  }

  const renderAwards = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>
          <span>荣誉奖项 / Honors & Awards</span>
        </div>
        {renderBullets(items)}
      </div>
    )
  }

  const renderSummary = (items?: string[]) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <div className={styles.sectionTitle}>
          <span>自我评价 / Summary</span>
        </div>
        {items.length === 1 ? (
          <p style={{ margin: '4px 0', fontSize: '10pt', lineHeight: '1.34' }}>
            <SafeHtml html={items[0]} />
          </p>
        ) : (
          renderBullets(items)
        )}
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {/* 顶部 Header */}
      <div className={styles.headerGrid}>
        <div className={styles.headerLeft}>
          <h1 className={styles.candidateName}>{personalInfo?.name || 'Your Name'}</h1>
          {personalInfo?.title && (
            <div className={styles.candidateTitle}>{personalInfo.title}</div>
          )}
          <div className={styles.metaRow}>
            {personalInfo?.phone && (
              <span className={styles.metaItem}>
                {showContactIcons && <Phone size={11} />}
                <span>{personalInfo.phone}</span>
              </span>
            )}
            {personalInfo?.email && (
              <>
                <span className={styles.metaDivider}>|</span>
                <span className={styles.metaItem}>
                  {showContactIcons && <Mail size={11} />}
                  <a href={`mailto:${personalInfo.email}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                    {personalInfo.email}
                  </a>
                </span>
              </>
            )}
            {personalInfo?.location && (
              <>
                <span className={styles.metaDivider}>|</span>
                <span className={styles.metaItem}>
                  {showContactIcons && <MapPin size={11} />}
                  <span>{personalInfo.location}</span>
                </span>
              </>
            )}
            {personalInfo?.github && (
              <>
                <span className={styles.metaDivider}>|</span>
                <span className={styles.metaItem}>
                  {showContactIcons && <Github size={11} />}
                  <a
                    href={personalInfo.github.startsWith('http') ? personalInfo.github : `https://${personalInfo.github}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'inherit', textDecoration: 'none' }}
                  >
                    {personalInfo.github.replace(/^https?:\/\//, '')}
                  </a>
                </span>
              </>
            )}
            {personalInfo?.website && (
              <>
                <span className={styles.metaDivider}>|</span>
                <span className={styles.metaItem}>
                  {showContactIcons && <Globe size={11} />}
                  <a
                    href={personalInfo.website.startsWith('http') ? personalInfo.website : `https://${personalInfo.website}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'inherit', textDecoration: 'none' }}
                  >
                    {personalInfo.website.replace(/^https?:\/\//, '')}
                  </a>
                </span>
              </>
            )}
          </div>
        </div>

        {/* 照片插槽 */}
        <div className={`${styles.photoSlot} ${!personalInfo?.photo ? styles.photoSlotNoPhoto : ''}`}>
          {personalInfo?.photo ? (
            <img src={personalInfo.photo} alt="Profile" className={styles.photoImg} />
          ) : (
            <div className={styles.photoSlotEmpty}>28×36mm</div>
          )}
        </div>
      </div>

      {/* 按照 sectionMeta 排序渲染各章节 */}
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
  )
}

export default ResumeAsuTech
