import { z } from "zod";

/**
 * 联系方式
 */
export const ContactSchema = z.object({
  phone: z.string().optional(),
  email: z.string().optional(),
  role: z.string().optional(),
  location: z.string().optional(),
  github: z.string().optional(),
  wechat: z.string().optional(),
  website: z.string().optional(),
  blog: z.string().optional(),
}).passthrough();

export type Contact = z.infer<typeof ContactSchema>;

/**
 * 带日期的经历条目（如工作、实习）
 */
export const DatedEntrySchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  date: z.string(),
  highlights: z.array(z.string()).optional(),
  details: z.array(z.string()).optional(),
  location: z.string().optional(),
}).passthrough();

export type DatedEntry = z.infer<typeof DatedEntrySchema>;

/**
 * 项目经验中的详细项
 */
export const ProjectItemSchema = z.object({
  title: z.string(),
  details: z.array(z.string()),
}).passthrough();

export type ProjectItem = z.infer<typeof ProjectItemSchema>;

/**
 * 项目经历
 */
export const ProjectSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  date: z.string().optional(),
  items: z.array(ProjectItemSchema).optional(),
  highlights: z.array(z.string()).optional(),
  link: z.string().optional(),
}).passthrough();

export type Project = z.infer<typeof ProjectSchema>;

/**
 * 开源经历
 */
export const OpenSourceContributionSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  items: z.array(z.string()),
  link: z.string().optional(),
}).passthrough();

export type OpenSourceContribution = z.infer<typeof OpenSourceContributionSchema>;

/**
 * 技能条目
 */
export const SkillSchema = z.object({
  category: z.string(),
  details: z.string(),
}).passthrough();

export type Skill = z.infer<typeof SkillSchema>;

/**
 * 教育经历
 */
export const EducationSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  degree: z.string().optional(),
  date: z.string(),
  details: z.array(z.string()).optional(),
  honors: z.string().optional(),
  gpa: z.string().optional(),
}).passthrough();

export type Education = z.infer<typeof EducationSchema>;

/**
 * 竞赛获奖
 */
export const CompetitionItemSchema = z.object({
  title: z.string(),
  award: z.string().optional(),
  date: z.string().optional(),
  details: z.string().optional(),
}).passthrough();

export type CompetitionItem = z.infer<typeof CompetitionItemSchema>;

/**
 * 论文出版物
 */
export const PublicationItemSchema = z.object({
  title: z.string(),
  authors: z.array(z.string()).optional(),
  venue: z.string().optional(),
  date: z.string().optional(),
}).passthrough();

export type PublicationItem = z.infer<typeof PublicationItemSchema>;

/**
 * 自定义模块标题
 */
export const SectionTitlesSchema = z.object({
  education: z.string().optional(),
  experience: z.string().optional(),
  internships: z.string().optional(),
  projects: z.string().optional(),
  skills: z.string().optional(),
  awards: z.string().optional(),
  summary: z.string().optional(),
  openSource: z.string().optional(),
  competitions: z.string().optional(),
  publications: z.string().optional(),
}).passthrough();

export type SectionTitles = z.infer<typeof SectionTitlesSchema>;

/**
 * 核心简历数据模型 (ResumeDataSchema)
 * 单一权威事实信源 (Single Source of Truth)
 */
export const ResumeDataSchema = z.object({
  name: z.string().default(""),
  contact: ContactSchema.default({}),
  objective: z.string().optional(),
  summary: z.string().optional(),
  internships: z.array(DatedEntrySchema).optional(),
  experience: z.array(DatedEntrySchema).optional(),
  projects: z.array(ProjectSchema).optional(),
  openSource: z.array(OpenSourceContributionSchema).optional(),
  skills: z.array(z.union([SkillSchema, z.string()])).optional(),
  education: z.array(EducationSchema).optional(),
  awards: z.array(z.string()).optional(),
  competitions: z.array(CompetitionItemSchema).optional(),
  publications: z.array(PublicationItemSchema).optional(),
  sectionTitles: SectionTitlesSchema.optional(),
  metadata: z.record(z.string(), z.any()).optional(),
}).passthrough();

export type ResumeData = z.infer<typeof ResumeDataSchema>;

/**
 * 校验并解析简历数据
 */
export function parseResumeData(data: unknown): ResumeData {
  return ResumeDataSchema.parse(data);
}

/**
 * 安全解析简历数据
 */
export function safeParseResumeData(data: unknown) {
  return ResumeDataSchema.safeParse(data);
}

/**
 * 类型守卫判断是否为有效简历数据
 */
export function isResumeData(data: unknown): data is ResumeData {
  return safeParseResumeData(data).success;
}
