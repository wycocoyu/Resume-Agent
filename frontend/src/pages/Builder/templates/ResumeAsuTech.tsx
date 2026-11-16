/**
 * ASu-Tech 单栏高密度技术简历模板
 * 规范实现：Issue #43, #44, #70, #72（对齐 Hisn00w/ASu-skills 母版）
 */
import React from 'react'
import { Mail, Phone, Globe, Github, User } from 'lucide-react'
import type { BuilderResumeData, Project, Experience, Education, CustomSectionItem } from '../types'
import { getSortedSections, formatDateRange } from '../types'
import { SafeHtml, InlineBold } from './SafeHtml'
import { TemplateLogo } from './TemplateLogo'
import styles from './styles/asuTech.module.css'

interface ResumeAsuTechProps {
  data: BuilderResumeData
  showContactIcons?: boolean
  compactMode?: boolean
}

const SHORT_ROLE_MAX_LEN = 24
const SENTENCE_PUNCT_RE = /[。！？；;\n]/

function isShortInlineRole(role?: string): boolean {
  if (!role || typeof role !== 'string') return false
  const trimmed = role.trim()
  return trimmed.length > 0 && trimmed.length <= SHORT_ROLE_MAX_LEN && !SENTENCE_PUNCT_RE.test(trimmed)
}

function isProjectSubheader(cleanHtml: string): boolean {
  const plain = cleanHtml.replace(/<[^>]+>/g, '').trim()
  if (!plain || plain.length > 68) return false
  if (!(plain.includes('　|　') || plain.includes(' | '))) return false
  // 含 "背景与目标：" 等冒号标签的正文条目不按项目小标题渲染
  const firstSegment = plain.split(/　\|　|\s\|\s/)[0] || ''
  return !/[：:]/.test(firstSegment)
}

function normalizeSectionTitle(displayName?: string, fallback?: string): string {
  const raw = (displayName || fallback || '').trim()
  if (!raw) return fallback || ''
  return raw.split(' / ')[0].trim() || raw
}

function toExternalHref(rawUrl: string): string {
  return rawUrl.startsWith('http://') || rawUrl.startsWith('https://')
    ? rawUrl
    : `https://${rawUrl}`
}

export const ResumeAsuTech: React.FC<ResumeAsuTechProps> = ({
  data,
  showContactIcons = true,
  compactMode = false,
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
  const sortedSections = getSortedSections(data)

  const renderBullets = (items?: string[], allowProjectSubheaders = false) => {
    if (!items || items.length === 0) return null

    const blocks: Array<{ type: 'subheader'; html: string } | { type: 'list'; items: Array<{ html: string; cls: string }> }> = []

    const pushBullet = (html: string, cls: string) => {
      const last = blocks[blocks.length - 1]
      if (last && last.type === 'list') {
        last.items.push({ html, cls })
      } else {
        blocks.push({ type: 'list', items: [{ html, cls }] })
      }
    }

    items.forEach((bullet) => {
      if (!bullet || typeof bullet !== 'string') return
      const isNestedDeep = bullet.startsWith('    ') || bullet.startsWith('\t\t')
      const isNested = !isNestedDeep && (bullet.startsWith('  ') || bullet.startsWith('\t') || bullet.trimStart().startsWith('○'))
      const cleanText = bullet.replace(/^[\s\t]*[○▪]\s*/, '').trim()
      if (!cleanText) return

      if (allowProjectSubheaders && !isNested && !isNestedDeep && isProjectSubheader(cleanText)) {
        blocks.push({ type: 'subheader', html: cleanText })
        return
      }

      const itemClass = isNestedDeep
        ? `${styles.bulletItem} ${styles.nestedDeep}`
        : isNested
        ? `${styles.bulletItem} ${styles.nested}`
        : styles.bulletItem
      pushBullet(cleanText, itemClass)
    })

    if (blocks.length === 0) return null

    return (
      <>
        {blocks.map((block, bIdx) => {
          if (block.type === 'subheader') {
            return (
              <div key={`sub-${bIdx}`} className={styles.projectTitle}>
                <SafeHtml html={block.html} />
              </div>
            )
          }
          return (
            <ul key={`ul-${bIdx}`} className={styles.bulletList}>
              {block.items.map((item, iIdx) => (
                <li key={iIdx} className={item.cls}>
                  <SafeHtml html={item.html} />
                </li>
              ))}
            </ul>
          )
        })}
      </>
    )
  }

  const renderWorkExperience = (items?: Experience[], title = '工作经历') => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {items.map((exp) => (
          <div key={exp.id} data-no-break="true" className={styles.experienceItem}>
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
                  {exp.title ? ` · ${exp.title}` : ''}
                  {exp.location ? ` (${exp.location})` : ''}
                </span>
              </div>
              <div className={styles.entryDate}>{formatDateRange(exp.years)}</div>
            </div>
            {renderBullets(exp.description, true)}
          </div>
        ))}
      </div>
    )
  }

  const renderEducation = (items?: Education[], title = '教育经历') => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {items.map((edu) => (
          <div key={edu.id} data-no-break="true" className={styles.educationItem}>
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
                  {edu.degree && (
                    <span className={styles.educationMajor}>· {edu.degree}</span>
                  )}
                </span>
              </div>
              <div className={styles.entryDate}>{formatDateRange(edu.years)}</div>
            </div>
            {renderBullets(edu.description, false)}
          </div>
        ))}
      </div>
    )
  }

  const renderProjects = (items?: Project[], title = '项目经历', isOpenSource = false) => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {items.map((proj) => {
          const roleText = proj.role?.trim() || ''
          const shortRole = isShortInlineRole(roleText) ? roleText : ''
          const longRole = roleText && !shortRole ? roleText : ''
          const primaryLink = proj.github || proj.website || ''
          const secondaryLink = proj.github && proj.website ? proj.website : ''

          return (
            <div key={proj.id} data-no-break="true" className={styles.projectEntry}>
              <div className={styles.companyBar}>
                <div className={styles.companyBarLeft}>
                  {(isOpenSource || proj.github) && (
                    <Github className={styles.companyIcon} aria-hidden="true" />
                  )}
                  <span className={styles.institutionName}>
                    {proj.name}
                    {shortRole ? ` · ${shortRole}` : ''}
                  </span>
                </div>
                <div className={styles.entryDate}>{formatDateRange(proj.years)}</div>
              </div>

              {primaryLink && (
                <div className={styles.evidenceLink}>
                  <span>{isOpenSource ? '项目地址：' : '仓库链接：'}</span>
                  <a
                    href={toExternalHref(primaryLink)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {primaryLink}
                  </a>
                  {secondaryLink && (
                    <a
                      href={toExternalHref(secondaryLink)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Demo
                    </a>
                  )}
                </div>
              )}

              {longRole && <div className={styles.projectLead}>{longRole}</div>}

              {renderBullets(proj.description, true)}
            </div>
          )
        })}
      </div>
    )
  }

  const renderSkills = (items?: string[], title = '专业技能') => {
    const valid = (items || []).filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
    if (valid.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        <div className={styles.skillsBlock}>
          {valid.map((skill, idx) => (
            <div key={idx} className={styles.skillLine}>
              <SafeHtml html={skill.trim()} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderAwards = (items?: string[], title = '荣誉奖项') => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {renderBullets(items, false)}
      </div>
    )
  }

  const renderSummary = (items?: string[], title = '自我评价') => {
    const valid = (items || []).filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
    if (valid.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {valid.length === 1 ? (
          <p className={styles.summaryParagraph}>
            <SafeHtml html={valid[0].trim()} />
          </p>
        ) : (
          renderBullets(valid, false)
        )}
      </div>
    )
  }

  const renderCustomSection = (items?: CustomSectionItem[], title = '其他经历') => {
    if (!items || items.length === 0) return null
    return (
      <div className={styles.sectionBlock}>
        <h2 className={styles.sectionTitle}>{title}</h2>
        {items.map((item) => (
          <div key={item.id} data-no-break="true" className={styles.projectEntry}>
            <div className={styles.companyBar}>
              <div className={styles.companyBarLeft}>
                <span className={styles.institutionName}>
                  <InlineBold text={item.title || ''} />
                  {item.subtitle ? ` · ${item.subtitle}` : ''}
                </span>
              </div>
              <div className={styles.entryDate}>{formatDateRange(item.years)}</div>
            </div>
            {renderBullets(item.description, true)}
          </div>
        ))}
      </div>
    )
  }

  // Row 1：手机 | 邮箱 | 个人站点（无 GitHub 时）| 城市（无头衔时）
  const contactSegments: React.ReactNode[] = []
  if (personalInfo?.phone) {
    contactSegments.push(
      <span key="phone" className={styles.metaItem}>
        {showContactIcons && <Phone className={styles.metaIcon} />}
        <span>{personalInfo.phone}</span>
      </span>
    )
  }
  if (personalInfo?.email) {
    contactSegments.push(
      <span key="email" className={styles.metaItem}>
        {showContactIcons && <Mail className={styles.metaIcon} />}
        <a href={`mailto:${personalInfo.email}`}>{personalInfo.email}</a>
      </span>
    )
  }
  if (!personalInfo?.title && personalInfo?.location) {
    contactSegments.push(
      <span key="location" className={styles.metaItem}>
        <span>{personalInfo.location}</span>
      </span>
    )
  }
  if (!personalInfo?.github && personalInfo?.website) {
    contactSegments.push(
      <span key="website-inline" className={styles.metaItem}>
        {showContactIcons && <Globe className={styles.metaIcon} />}
        <a href={toExternalHref(personalInfo.website)} target="_blank" rel="noopener noreferrer">
          {personalInfo.website.replace(/^https?:\/\//, '')}
        </a>
      </span>
    )
  }

  // Row 2：城市 · 求职定位（加粗强行）
  const identityText = personalInfo?.title
    ? [personalInfo.location, personalInfo.title].filter(Boolean).join(' · ')
    : ''

  // Row 3：GitHub / 主页强行
  const hasRepoRow = Boolean(personalInfo?.github)

  return (
    <div className={`${styles.container} ${compactMode ? styles.compact : ''}`}>
      {/* 顶部 Header */}
      <div className={`${styles.headerGrid} ${!personalInfo?.photo ? styles.headerGridNoPhoto : ''}`}>
        <div className={styles.headerLeft}>
          <h1 className={styles.candidateName}>{personalInfo?.name || 'Your Name'}</h1>

          {contactSegments.length > 0 && (
            <div className={styles.metaRow}>
              {contactSegments.map((seg, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <span className={styles.metaDivider}>|</span>}
                  {seg}
                </React.Fragment>
              ))}
            </div>
          )}

          {identityText && (
            <div className={styles.metaRow}>
              {showContactIcons && <User className={styles.metaIcon} />}
              <strong>{identityText}</strong>
            </div>
          )}

          {hasRepoRow && (
            <div className={styles.metaRow}>
              {showContactIcons && <Github className={styles.metaIcon} />}
              <strong>
                <a
                  href={toExternalHref(personalInfo!.github!)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {personalInfo!.github!.replace(/^https?:\/\//, '')}
                </a>
                {personalInfo?.website && (
                  <>
                    {' · '}
                    <a
                      href={toExternalHref(personalInfo.website)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {personalInfo.website.replace(/^https?:\/\//, '')}
                    </a>
                  </>
                )}
              </strong>
            </div>
          )}
        </div>

        {/* 照片插槽（28×36mm） */}
        <div
          className={`${styles.photoSlot} ${
            personalInfo?.photo ? styles.photoSlotHasPhoto : styles.photoSlotNoPhoto
          }`}
        >
          {personalInfo?.photo ? (
            <img src={personalInfo.photo} alt="Profile" className={styles.photoImg} />
          ) : (
            <div className={styles.photoSlotEmpty}>证件照<br />28×36mm</div>
          )}
        </div>
      </div>

      {/* 按照 sectionMeta 排序渲染各章节（纯中文标题） */}
      {sortedSections.map((sec) => {
        switch (sec.key) {
          case 'education':
            return (
              <React.Fragment key={sec.id}>
                {renderEducation(education, normalizeSectionTitle(sec.displayName, '教育经历'))}
              </React.Fragment>
            )
          case 'fullTimeExperience':
            return (
              <React.Fragment key={sec.id}>
                {renderWorkExperience(fullTimeExperience, normalizeSectionTitle(sec.displayName, '工作经历'))}
              </React.Fragment>
            )
          case 'workExperience':
            return (
              <React.Fragment key={sec.id}>
                {renderWorkExperience(internshipItems, normalizeSectionTitle(sec.displayName, '实习经历'))}
              </React.Fragment>
            )
          case 'personalProjects':
            return (
              <React.Fragment key={sec.id}>
                {renderProjects(personalProjects, normalizeSectionTitle(sec.displayName, '项目经历'), false)}
              </React.Fragment>
            )
          case 'openSource':
            return (
              <React.Fragment key={sec.id}>
                {renderProjects(openSource, normalizeSectionTitle(sec.displayName, '开源经历'), true)}
              </React.Fragment>
            )
          case 'skills':
            return (
              <React.Fragment key={sec.id}>
                {renderSkills(skills, normalizeSectionTitle(sec.displayName, '专业技能'))}
              </React.Fragment>
            )
          case 'awards':
            return (
              <React.Fragment key={sec.id}>
                {renderAwards(awards, normalizeSectionTitle(sec.displayName, '荣誉奖项'))}
              </React.Fragment>
            )
          case 'summary':
            return (
              <React.Fragment key={sec.id}>
                {renderSummary(summary, normalizeSectionTitle(sec.displayName, '自我评价'))}
              </React.Fragment>
            )
          default: {
            const custom = customSections?.[sec.key]
            if (custom?.items?.length) {
              return (
                <React.Fragment key={sec.id}>
                  {renderCustomSection(custom.items, normalizeSectionTitle(sec.displayName, sec.key))}
                </React.Fragment>
              )
            }
            return null
          }
        }
      })}
    </div>
  )
}

export default ResumeAsuTech
