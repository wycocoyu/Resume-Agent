import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import {
  ChevronRight,
  LogIn,
  LogOut,
  Github,
  Bot,
  Sun,
  Moon,
  X,
  FileText,
  Wand2,
  Target,
  BarChart3,
  Download,
  ScanLine,
  Star,
  ArrowUpRight,
  CornerDownLeft,
  Clock,
  Frown,
  Upload,
  Palette,
} from 'lucide-react'
import { useEffect, useState, useRef } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { BetaBadge } from '@/components/BetaBadge'
import { useAuth } from '@/contexts/AuthContext'
import { useTheme } from '@/hooks/useTheme'
import { canUseAdminFeature, isAgentEnabled } from '@/lib/runtimeEnv'
import { setHeroHandoffImages } from '@/lib/heroHandoff'
import { SkinPickerModal } from '@/pages/Workspace/v2/components/SkinPickerModal'

/** 微信 logo（Simple Icons 路径），用于「联系我」——点开是微信二维码。 */
function WechatIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 4.882-1.98 7.32-1.434C20.49 5.7 16.96 2.188 8.691 2.188zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178A1.17 1.17 0 0 1 4.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178 1.17 1.17 0 0 1-1.162-1.178c0-.651.52-1.18 1.162-1.18zm5.34 2.867c-1.797-.052-3.746.512-5.28 1.786-1.72 1.428-2.687 3.72-1.78 6.22.942 2.453 3.666 4.229 6.884 4.229.826 0 1.622-.12 2.361-.336a.722.722 0 0 1 .598.082l1.584.926a.272.272 0 0 0 .14.047c.134 0 .24-.111.24-.247 0-.06-.023-.12-.038-.177l-.327-1.233a.582.582 0 0 1-.023-.156.49.49 0 0 1 .201-.398C23.024 18.48 24 16.82 24 14.98c0-3.21-2.931-5.837-6.656-6.088zm-2.53 3.274c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.97-.982zm4.844 0c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.969-.982z" />
    </svg>
  )
}

// 刷新时标题/副标题轻微淡入上浮（防 spring 黑框闪烁：走 tween，不用 scale）
const popIn = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const }
}

const REPO_URL = 'https://github.com/wycocoyu/cococv'

// 首屏输入框下方的示例快捷入口：一点即进对话（降低冷启动，并埋「按岗位改一版」的高频钩子）
// 「按 JD 改简历」chip 特殊处理：进对话后打开结构化 JD 优化交互卡（而非发文字给 Agent）
const JD_OPTIMIZE_CHIP = '按目标岗位 JD 帮我改简历'
const HERO_CHIPS = [
  '我是应届生、帮我做一份简历',
  // 暂时下掉这两个入口（前端先不展示），代码保留方便以后恢复
  // JD_OPTIMIZE_CHIP,
  // '帮我把经历写得更专业',
]

// 简历制作核心能力（均为现有产品功能，不含面试类）
const CAPABILITIES = [
  {
    icon: FileText,
    title: '自然语言生成',
    desc: '一句话描述经历、自动生成结构化、可直接编辑的简历。',
    span: 'lg:col-span-3',
    variant: 'command'
  },
  {
    icon: Wand2,
    title: '划词润色改写',
    desc: '选中任意一段、一键润色、量化、换强动词。',
    span: 'lg:col-span-3',
    variant: 'standard'
  },
  {
    icon: Target,
    title: 'JD 岗位匹配',
    desc: '对照目标岗位诊断缺口、缺失关键词可一键融入经历。',
    span: 'lg:col-span-2',
    variant: 'standard'
  },
  {
    icon: ScanLine,
    title: '智能解析导入',
    desc: 'PDF 或文本简历一键解析为可编辑结构。',
    span: 'lg:col-span-2',
    variant: 'standard'
  },
  {
    icon: BarChart3,
    title: '简历质量评分',
    desc: '完整性、表达、匹配度多维打分并给出修改建议。',
    span: 'lg:col-span-2',
    variant: 'standard'
  },
  {
    icon: Download,
    title: '像素级 PDF 导出',
    desc: 'LaTeX 排版引擎、一键导出干净精美的 PDF。',
    span: 'lg:col-span-6',
    variant: 'pdf'
  }
] as const

// 痛点区：说出求职者正在经历的麻烦（对应 Landing"解决我正在烦的问题"这一职）
const PAIN_POINTS = [
  {
    icon: Moon,
    title: '改到半夜还是没底',
    desc: '一句话经历不知道怎么写成简历、反复删改、仍然不确定写得够不够好。'
  },
  {
    icon: Frown,
    title: '投了几十份没回音',
    desc: '不知道简历到底卡在哪、缺了什么关键词、也没人帮你对照岗位诊断。'
  },
  {
    icon: Clock,
    title: '时间全耗在排版上',
    desc: 'Word 调格式、对齐、换字体、真正该打磨的内容反而没精力顾。'
  }
] as const

// 使用流程：输入 -> 处理 -> 得到结果（对应"买时间"链路里的体验环节）
const STEPS = [
  {
    icon: ScanLine,
    title: '输入或导入',
    desc: '一句话描述经历、或上传已有 PDF / 文本简历一键解析为可编辑结构。'
  },
  {
    icon: Wand2,
    title: 'AI 协助打磨',
    desc: '划词润色、按 JD 补缺口、多维评分给建议、对话式改到满意为止。'
  },
  {
    icon: Download,
    title: '导出投递',
    desc: 'LaTeX 排版实时预览、一键导出干净无水印的 A4 PDF、直接投递。'
  }
] as const

// FAQ：解释费用、格式、隐私、可靠性与退款，承接页脚法务页
const FAQ_ITEMS: { q: string; a: ReactNode }[] = [
  {
    q: '这个产品收费吗？',
    a: '基础功能可直接体验、含一定 AI 生成额度；额度用尽后可按需购买一次性积分包，具体价格见定价页。'
  },
  {
    q: '支持导入哪些简历格式？',
    a: '支持 PDF 与纯文本简历，上传后会自动解析为可编辑的结构化内容。'
  },
  {
    q: '我的简历数据安全吗？',
    a: (
      <>
        我们仅在为你提供功能所必需的范围内处理简历数据，具体收集与使用方式见{' '}
        <Link to="/privacy" className="text-blue-600 dark:text-blue-400 hover:underline">
          隐私政策
        </Link>
        。
      </>
    )
  },
  {
    q: 'AI 生成的内容可靠吗？',
    a: (
      <>
        AI 生成的文本与建议仅供参考，可能存在不准确之处，请在采用前自行核对，详见{' '}
        <Link to="/terms" className="text-blue-600 dark:text-blue-400 hover:underline">
          服务条款
        </Link>
        。
      </>
    )
  },
  {
    q: '未来会收费吗？能退款吗？',
    a: (
      <>
        付费积分包的计费与退款规则以定价页说明与《退款政策》为准，可先参阅{' '}
        <Link to="/refund" className="text-blue-600 dark:text-blue-400 hover:underline">
          退款政策
        </Link>
        。
      </>
    )
  }
]

// 自然语言生成卡内的小型"命令条"预览（real component preview，非 fake screenshot）
function CommandBar() {
  const phrases = [
    '一段在字节做推荐算法的实习，整理成简历条目',
    '把大二做的课程设计包装成项目经历',
    '把项目经历按 STAR 法则重写'
  ]
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setIdx((i) => (i + 1) % phrases.length), 3200)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="relative mt-4 border-2 fresh:border border-black fresh:border-slate-200 bg-white px-3.5 py-2.5 flex items-center gap-2.5">
      <span className="inline-block h-2 w-2 bg-[#1a73e8] shrink-0" />
      <div className="flex-1 min-w-0 relative h-5 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.span
            key={idx}
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -12, opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="absolute inset-0 text-[13px] text-slate-700 truncate"
          >
            {phrases[idx]}
          </motion.span>
        </AnimatePresence>
      </div>
      <span className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono fresh:font-sans text-slate-500 border border-black fresh:border-slate-200 px-1.5 py-0.5 shrink-0">
        <CornerDownLeft className="w-3 h-3" />
        回车
      </span>
    </div>
  )
}

// PDF 导出卡内的迷你简历预览条（结构化 hairline 简历骨架，非 div fake screenshot）
function PdfPreview() {
  return (
    <div className="mt-5 border-2 fresh:border border-black fresh:border-slate-200 bg-white p-4">
      <div className="grid grid-cols-12 gap-x-4 gap-y-3 text-slate-700">
        <div className="col-span-12 flex items-end justify-between border-b border-black fresh:border-slate-200 pb-3">
          <div>
            <div className="h-3 w-28 bg-black" />
            <div className="mt-1.5 h-2 w-20 bg-slate-400" />
          </div>
          <div className="flex items-center gap-1.5 text-[10px] font-mono fresh:font-sans text-slate-500">
            <span className="inline-block h-1.5 w-1.5 bg-[#1a73e8]" />
            A4 · 1 页
          </div>
        </div>
        <div className="col-span-12 mt-1">
          <div className="h-1.5 w-12 bg-[#1a73e8] mb-2" />
          <div className="space-y-1.5">
            <div className="h-1.5 w-full bg-slate-300" />
            <div className="h-1.5 w-[92%] bg-slate-300" />
            <div className="h-1.5 w-[78%] bg-slate-300" />
          </div>
        </div>
        <div className="col-span-7">
          <div className="h-1.5 w-16 bg-[#1a73e8] mb-2" />
          <div className="space-y-1.5">
            <div className="h-1.5 w-[88%] bg-slate-300" />
            <div className="h-1.5 w-[70%] bg-slate-300" />
          </div>
        </div>
        <div className="col-span-5">
          <div className="h-1.5 w-12 bg-[#1a73e8] mb-2" />
          <div className="flex flex-wrap gap-1">
            <span className="h-3 w-10 bg-slate-300" />
            <span className="h-3 w-14 bg-slate-300" />
            <span className="h-3 w-8 bg-slate-300" />
            <span className="h-3 w-12 bg-slate-300" />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function LandingPage() {
  const navigate = useNavigate()
  const { isAuthenticated, user, logout, openModal } = useAuth()
  const { isDark, setTheme } = useTheme()
  const agentEnabled = isAgentEnabled()
  // 深色模式功能仅管理员可见/可用，其余用户不展示切换入口
  const canUseDarkMode = isAuthenticated && canUseAdminFeature()
  // 皮肤选择框开关(「网站皮肤」按钮点击弹出,复用工作台 SkinPickerModal)
  const [showSkinPicker, setShowSkinPicker] = useState(false)
  const reduceMotion = useReducedMotion()
  const [showLogoutMenu, setShowLogoutMenu] = useState(false)
  const [showWechatCard, setShowWechatCard] = useState(false)
  const [githubStars, setGithubStars] = useState<number | null>(null)
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [heroInput, setHeroInput] = useState('')
  const [heroImages, setHeroImages] = useState<File[]>([])
  const logoutMenuRef = useRef<HTMLDivElement>(null)
  const wechatMenuRef = useRef<HTMLDivElement>(null)

  const handleOpenAgent = () => {
    if (!agentEnabled) return
    navigate('/agent/new')
  }

  // 首屏输入即体验：把用户输入（文字 / 粘贴的截图）交给对话页作为第一条。
  // 文字走 sessionStorage、图片走 heroHandoff 内存交接；fromHome 让对话页跳过「加载最近会话」，直接开新对话。
  const startWithText = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed && heroImages.length === 0) return
    if (agentEnabled) {
      if (heroImages.length > 0) {
        setHeroHandoffImages(heroImages.slice(0, 2))
      }
      sessionStorage.setItem('agent_initial_text', trimmed)
      navigate('/agent/new', { state: { fromHome: Date.now() } })
    } else {
      navigate('/create-new')
    }
  }

  const handleHeroSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    startWithText(heroInput)
  }

  // 打开对话内「按 JD 优化简历」交互卡
  const startJdOptimize = () => {
    if (agentEnabled) {
      sessionStorage.setItem('agent_open_jd_card', '1')
      navigate('/agent/new', { state: { fromHome: Date.now() } })
    } else {
      navigate('/create-new')
    }
  }

  // 粘贴截图：从剪贴板取图片文件，挂到 hero（最多 2 张），阻止默认的图片/文件名文本粘贴
  const handleHeroPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData?.items || [])
      .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
      .map((it) => it.getAsFile())
      .filter((f): f is File => !!f)
    if (files.length === 0) return
    e.preventDefault()
    setHeroImages((prev) => [...prev, ...files].slice(0, 2))
  }

  const removeHeroImage = (idx: number) =>
    setHeroImages((prev) => prev.filter((_, i) => i !== idx))

  // 拉取 GitHub star 数（公开 API，无需 token）
  useEffect(() => {
    fetch('https://api.github.com/repos/wycocoyu/cococv')
      .then((res) => res.json())
      .then((data) => {
        if (typeof data.stargazers_count === 'number') setGithubStars(data.stargazers_count)
      })
      .catch(() => {})
  }, [])

  // 点击外部区域关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (logoutMenuRef.current && !logoutMenuRef.current.contains(event.target as Node)) {
        setShowLogoutMenu(false)
      }
      if (wechatMenuRef.current && !wechatMenuRef.current.contains(event.target as Node)) {
        setShowWechatCard(false)
      }
    }

    if (showLogoutMenu || showWechatCard) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [showLogoutMenu, showWechatCard])

  // 进入视口时的轻量上浮（尊重 prefers-reduced-motion）
  const reveal = {
    initial: reduceMotion ? false : { opacity: 0, y: 24 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.3 },
    transition: { duration: 0.6, ease: [0.16, 1, 0.3, 1] as const }
  }

  return (
    <div className="min-h-screen bg-[#F6F3EC] fresh:bg-slate-50 bg-[linear-gradient(rgba(10,10,10,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(10,10,10,0.05)_1px,transparent_1px)] fresh:bg-none bg-[size:32px_32px] text-slate-900 font-hero antialiased selection:bg-[#D7E7FF] selection:text-[#0a0a0a]">
      {/* 顶部导航 - neo-brutalist 风格 */}
      <nav className={`fixed top-0 left-0 right-0 z-50 bg-[#F6F3EC] fresh:bg-slate-50 border-b-[1.5px] fresh:border-b border-black fresh:border-slate-200 transition-all duration-300`}>
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between h-14">
          <div className="flex items-center gap-2.5 cursor-pointer group shrink-0 min-w-0" onClick={() => navigate('/')}>
            <div className="w-9 h-9 bg-[#4285F4] flex items-center justify-center border border-black fresh:border-slate-200 shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm group-hover:translate-x-[1px] group-hover:translate-y-[1px] group-hover:shadow-none transition-all shrink-0">
              <span className="text-white font-mono fresh:font-sans font-black text-sm italic">RA</span>
            </div>
            <span className="text-black font-mono fresh:font-sans font-bold text-base uppercase fresh:normal-case tracking-wide fresh:tracking-normal">Resume.AI</span>
            <BetaBadge className="-ml-1 translate-y-[-6px]" />
          </div>

          <div className="flex items-center gap-2">
            {/* 次要工具统一收进一个容器，避免每个入口都像主按钮。 */}
            <div className="flex h-10 items-center gap-0.5 border-2 fresh:border border-black fresh:border-slate-200 bg-white p-0.5 shadow-[2px_2px_0px_0px_#000000] fresh:rounded-lg fresh:shadow-sm">
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="hidden h-8 items-center gap-1.5 bg-black px-2 text-white transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-md md:flex"
                title="在 GitHub 查看项目"
                aria-label={githubStars === null ? '在 GitHub 查看项目' : `在 GitHub 查看项目，${githubStars.toLocaleString()} 个 Star`}
              >
                <Github className="h-4 w-4 shrink-0" />
                {githubStars !== null && (
                  <span className="tabular-nums text-xs font-mono fresh:font-sans font-semibold tracking-tight">{githubStars.toLocaleString()}</span>
                )}
              </a>
              {canUseDarkMode && (
                <button
                  type="button"
                  onClick={() => setTheme(isDark ? 'light' : 'dark')}
                  className="flex h-8 items-center justify-center gap-1.5 px-2 text-slate-700 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-md"
                  title={isDark ? '切换到浅色模式' : '切换到深色模式'}
                  aria-label={isDark ? '切换到浅色模式' : '切换到深色模式'}
                >
                  {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                  <span className="hidden text-xs font-medium lg:inline">{isDark ? '浅色' : '深色'}</span>
                </button>
              )}
              <div className="relative hidden md:block" ref={wechatMenuRef}>
                <button
                  type="button"
                  onClick={() => setShowWechatCard((prev) => !prev)}
                  className="flex h-8 items-center justify-center gap-1.5 px-2 text-slate-700 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-md"
                  title="联系我"
                  aria-label="联系我"
                >
                  <WechatIcon className="h-4 w-4 shrink-0 text-[#07C160]" />
                  <span className="hidden text-xs font-medium lg:inline">联系</span>
                </button>
                <AnimatePresence>
                  {showWechatCard && (
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 8 }}
                      transition={{ duration: 0.15 }}
                      className="absolute right-0 top-full z-50 mt-2 w-[220px] border-2 fresh:border border-black fresh:border-slate-200 bg-white shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md"
                    >
                      <div className="p-4 border-b-2 border-black fresh:border-slate-200">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-bold">联系我</div>
                            <div className="mt-1 text-xs text-slate-500">微信扫码、直接沟通</div>
                          </div>
                          <button
                            type="button"
                            onClick={() => setShowWechatCard(false)}
                            className="rounded p-1 text-slate-400 hover:bg-slate-100 transition-colors"
                            aria-label="关闭联系卡片"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                      <div className="p-4">
                        <img
                          src="https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com/contact-qr.jpg"
                          alt="微信二维码"
                          className="w-full object-cover"
                        />
                        <div className="mt-3 text-center text-[11px] text-slate-400">
                          扫码后备注：简历站
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
              {/* 界面皮肤:点击弹出选择框(Landing 与 Workspace 共用同一 localStorage + <html> data-skin) */}
              <button
                type="button"
                onClick={() => setShowSkinPicker(true)}
                className="flex h-8 items-center justify-center gap-1.5 px-2 text-slate-700 transition-colors hover:bg-[#D7E7FF] hover:text-[#1a73e8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-md"
                title="选择界面皮肤"
                aria-label="界面皮肤"
              >
                <Palette className="h-4 w-4 shrink-0" />
                <span className="hidden text-xs font-medium lg:inline">皮肤</span>
              </button>
              <SkinPickerModal
                open={showSkinPicker}
                onPicked={() => setShowSkinPicker(false)}
                onClose={() => setShowSkinPicker(false)}
              />
              <button
                type="button"
                onClick={() => navigate('/changelog')}
                className="hidden h-8 items-center justify-center gap-1.5 px-2 text-slate-700 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-md md:flex"
                title="查看更新日志"
                aria-label="查看更新日志"
              >
                <Clock className="w-4 h-4 shrink-0" />
                <span className="hidden text-xs font-medium lg:inline">更新</span>
              </button>
            </div>
            {agentEnabled && (
              <button
                type="button"
                onClick={handleOpenAgent}
                className="hidden h-10 items-center gap-2 border-2 fresh:border border-black fresh:border-slate-200 bg-white px-3 text-sm font-bold text-slate-800 shadow-[2px_2px_0px_0px_#000000] transition-colors hover:bg-[#D7E7FF] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] fresh:rounded-lg fresh:font-sans fresh:shadow-sm md:flex"
              >
                <Bot className="h-4 w-4 shrink-0 text-[#4285F4]" />
                <span>AI 助手</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => navigate('/my-resumes')}
              className="inline-flex h-10 items-center justify-center gap-2 border-2 fresh:border border-black fresh:border-[#356fd6] bg-[#4285F4] px-3 text-sm font-bold text-white shadow-[2px_2px_0px_0px_#000000] transition-colors hover:bg-[#3478e5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4285F4] focus-visible:ring-offset-2 fresh:rounded-lg fresh:font-sans fresh:shadow-sm sm:px-4"
            >
              <FileText className="h-4 w-4 shrink-0" />
              我的简历
            </button>
          </div>
        </div>
      </nav>

      {/* Hero 区域 */}
      <section className="relative px-6 pb-14 pt-24 sm:pt-28">
        <div className="max-w-4xl mx-auto text-center">
          {/* 超大 serif 标题 + mono 标签 */}
          <motion.div {...popIn} className="border-2 fresh:border border-black fresh:border-slate-200 bg-[#fffdf8] fresh:bg-white p-8 sm:p-10 shadow-[6px_6px_0px_0px_#000000] fresh:rounded-2xl fresh:shadow-[0_12px_32px_rgba(15,23,42,0.08)] dark:border-white dark:bg-slate-900 dark:shadow-[6px_6px_0px_0px_#ffffff]">
            <div className="mb-5 inline-flex bg-[#D7E7FF] px-2 py-1 text-[10px] font-black uppercase fresh:rounded-full fresh:normal-case tracking-[0.06em] text-[#1a73e8]">
              // AI RESUME PLATFORM
            </div>
            <motion.h1
              {...popIn}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: 0.08 }}
              className="text-4xl sm:text-5xl lg:text-6xl font-serif font-bold tracking-tight leading-[1.1] text-black dark:text-white"
            >
              帮你把经历<span className="text-[#4285F4]">聊成</span>一份好简历
            </motion.h1>
            <motion.p
              {...popIn}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: 0.16 }}
              className="mt-5 text-base sm:text-lg text-slate-600 dark:text-slate-400 leading-relaxed"
            >
              说一句你的经历、AI 陪你把它理成条理清晰、对得上岗位的简历。
            </motion.p>
          </motion.div>

          {agentEnabled ? (
            <motion.div
              {...popIn}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: 0.24 }}
              className="mx-auto mt-5 max-w-3xl"
            >
              <form onSubmit={handleHeroSubmit} className="relative border-2 fresh:border border-black fresh:border-slate-200 bg-white shadow-[4px_4px_0px_0px_#000000] fresh:rounded-xl fresh:shadow-sm focus-within:shadow-[2px_2px_0px_0px_#000000] fresh:focus-within:border-blue-400 fresh:focus-within:shadow-[0_8px_24px_rgba(59,130,246,0.12)] focus-within:translate-x-[2px] fresh:focus-within:translate-x-0 focus-within:translate-y-[2px] fresh:focus-within:translate-y-0 transition-all dark:border-white dark:bg-slate-900 dark:shadow-[4px_4px_0px_0px_#ffffff] dark:focus-within:shadow-[2px_2px_0px_0px_#ffffff] dark:focus-within:translate-x-[2px] dark:focus-within:translate-y-[2px]">
                {heroImages.length > 0 && (
                  <div className="flex flex-wrap gap-2 px-4 pt-4">
                    {heroImages.map((file, i) => (
                      <div key={i} className="relative h-16 w-16 overflow-hidden border border-black fresh:border-slate-200 dark:border-white">
                        <img src={URL.createObjectURL(file)} alt="粘贴的简历截图" className="h-full w-full object-cover" />
                        <button
                          type="button"
                          aria-label="移除图片"
                          onClick={() => removeHeroImage(i)}
                          className="absolute right-0.5 top-0.5 flex h-4 w-4 items-center justify-center border border-black fresh:border-slate-200 bg-white text-black hover:bg-red-500 hover:text-white dark:border-white dark:bg-slate-900 dark:text-white dark:hover:bg-red-500"
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <textarea
                  value={heroInput}
                  onChange={(e) => setHeroInput(e.target.value)}
                  onPaste={handleHeroPaste}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault()
                      startWithText(heroInput)
                    }
                  }}
                  rows={3}
                  placeholder="说说你做过什么，我来帮你写成简历（也可以直接粘贴简历截图）"
                  className="w-full resize-none bg-transparent px-5 py-4 pr-16 text-base text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none"
                />
                <button
                  type="submit"
                  aria-label="开始"
                  disabled={!heroInput.trim() && heroImages.length === 0}
                  className="absolute right-3 bottom-3 h-11 w-11 flex items-center justify-center border-2 fresh:border border-black fresh:border-blue-500 bg-[#D7E7FF] fresh:bg-[#4285F4] text-black fresh:text-white hover:bg-[#bcdaff] fresh:hover:bg-[#3478e5] disabled:opacity-40 disabled:cursor-not-allowed transition-all fresh:rounded-lg active:translate-x-[1px] fresh:active:translate-x-0 active:translate-y-[1px] fresh:active:translate-y-0 active:shadow-none dark:border-white"
                >
                  <ArrowUpRight className="w-5 h-5" strokeWidth={2.5} />
                </button>
              </form>

              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                {HERO_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => (chip === JD_OPTIMIZE_CHIP ? startJdOptimize() : startWithText(chip))}
                    className="px-3.5 py-1.5 border-2 fresh:border border-black fresh:border-slate-200 bg-white text-xs font-mono fresh:font-sans text-slate-700 hover:bg-slate-100 active:translate-x-[1px] fresh:active:translate-x-0 active:translate-y-[1px] fresh:active:translate-y-0 active:shadow-none transition-all shadow-[2px_2px_0px_0px_#000000] fresh:rounded-full fresh:shadow-none dark:border-white dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:shadow-[2px_2px_0px_0px_#ffffff]"
                  >
                    {chip}
                  </button>
                ))}
              </div>

              <div className="mt-6">
                <div className="mb-3 flex items-center justify-center gap-3">
                  <span className="h-px w-8 bg-slate-300 dark:bg-slate-600" />
                  <span className="text-xs font-mono fresh:font-sans font-bold tracking-wide fresh:tracking-normal text-slate-400 dark:text-slate-500">
                    已有简历？也可以直接开始
                  </span>
                  <span className="h-px w-8 bg-slate-300 dark:bg-slate-600" />
                </div>
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <button
                    type="button"
                    onClick={() => navigate('/create-new')}
                    className="inline-flex h-12 min-w-36 items-center justify-center gap-2 px-5 border-2 fresh:border border-black fresh:border-slate-200 bg-white text-slate-900 font-bold text-sm hover:bg-[#D7E7FF] active:translate-x-[2px] fresh:active:translate-x-0 active:translate-y-[2px] fresh:active:translate-y-0 active:shadow-none transition-all shadow-[4px_4px_0px_0px_#000000] fresh:rounded-lg fresh:shadow-sm dark:border-white dark:bg-slate-900 dark:text-white dark:hover:bg-slate-800 dark:shadow-[4px_4px_0px_0px_#ffffff]"
                  >
                    <Upload className="w-5 h-5" strokeWidth={2.5} />
                    直接导入
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/my-resumes')}
                    className="inline-flex h-12 min-w-36 items-center justify-center gap-2 px-5 border-2 fresh:border border-black fresh:border-slate-200 bg-white text-slate-900 font-bold text-sm hover:bg-[#D7E7FF] active:translate-x-[2px] fresh:active:translate-x-0 active:translate-y-[2px] fresh:active:translate-y-0 active:shadow-none transition-all shadow-[4px_4px_0px_0px_#000000] fresh:rounded-lg fresh:shadow-sm dark:border-white dark:bg-slate-900 dark:text-white dark:hover:bg-slate-800 dark:shadow-[4px_4px_0px_0px_#ffffff]"
                  >
                    <FileText className="w-5 h-5" strokeWidth={2.5} />
                    选择已有简历
                  </button>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              {...popIn}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: 0.24 }}
              className="mt-9 flex items-center justify-center"
            >
              <button
                onClick={() => navigate('/create-new')}
                className="px-7 py-3.5 border-2 fresh:border border-black fresh:border-slate-200 bg-[#D7E7FF] text-black font-bold text-base hover:bg-[#bcdaff] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none transition-all shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md"
              >
                开始创建
                <ChevronRight className="inline w-5 h-5 ml-2" strokeWidth={2.5} />
              </button>
            </motion.div>
          )}

          <motion.a
            {...popIn}
            transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1], delay: 0.32 }}
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-[#1a73e8] dark:hover:text-[#4285F4] transition-colors"
          >
            <Star className="w-4 h-4" />
            觉得有用、欢迎在 GitHub 点个 Star
          </motion.a>
        </div>
      </section>

      {/* 痛点区 */}
      <section className="px-6 pt-12 pb-16 bg-[#EFE9F8] border-y-[1.5px] border-black fresh:border-slate-200">
        <div className="max-w-5xl mx-auto">
          <motion.div {...reveal} className="max-w-2xl mb-10">
            <div className="mb-3 inline-flex bg-[#D7E7FF] px-2 py-1 text-[10px] font-black uppercase fresh:normal-case tracking-[0.06em] text-[#1a73e8]">
              // PAIN POINTS
            </div>
            <h2 className="text-3xl sm:text-4xl font-serif font-bold tracking-tight text-black dark:text-white">
              写简历的累・你应该最懂
            </h2>
            <p className="mt-3 text-base text-slate-600 dark:text-slate-400 leading-relaxed">
              不是你不会写，是没人陪你把零散经历理清楚、对着岗位改到位。
            </p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-0">
            {PAIN_POINTS.map((pain, i) => {
              const Icon = pain.icon
              return (
                <motion.div
                  key={pain.title}
                  initial={reduceMotion ? false : { opacity: 0, y: 24 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.55, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  className="border border-black fresh:border-slate-200 bg-white p-6 dark:border-white dark:bg-slate-900"
                >
                  <div className="flex items-center justify-center w-10 h-10 border-2 fresh:border border-black fresh:border-slate-200 bg-slate-100 mb-4 dark:border-white dark:bg-slate-800">
                    <Icon className="w-5 h-5 text-slate-600 dark:text-slate-300" />
                  </div>
                  <h3 className="text-base font-bold text-black dark:text-white">{pain.title}</h3>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 leading-relaxed">{pain.desc}</p>
                </motion.div>
              )
            })}
          </div>
        </div>
      </section>

      {/* 能力区域 - bento 网格 */}
      <section className="px-6 pt-16 pb-16 bg-[#EAF8E0] border-y-[1.5px] border-black fresh:border-slate-200">
        <div className="max-w-5xl mx-auto">
          <motion.div {...reveal} className="max-w-2xl mb-10">
            <div className="mb-3 inline-flex bg-[#D7E7FF] px-2 py-1 text-[10px] font-black uppercase fresh:normal-case tracking-[0.06em] text-[#1a73e8]">
              // CAPABILITIES
            </div>
            <h2 className="text-3xl sm:text-4xl font-serif font-bold tracking-tight text-black dark:text-white">
              一份简历・从写到投・都帮你想到了
            </h2>
            <p className="mt-3 text-base text-slate-600 dark:text-slate-400 leading-relaxed">
              围绕简历制作的全流程能力，每一步都由 AI 协助。
            </p>
          </motion.div>

          <div className="grid grid-cols-1 lg:grid-cols-6 gap-0">
            {CAPABILITIES.map((cap, i) => {
              const Icon = cap.icon
              const isHero = cap.variant === 'command' || cap.variant === 'pdf'
              return (
                <motion.div
                  key={cap.title}
                  initial={reduceMotion ? false : { opacity: 0, y: 24 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.55, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
                  className={`${cap.span} border border-black fresh:border-slate-200 p-6 bg-white dark:border-white dark:bg-slate-900 ${
                    isHero ? 'bg-[#D7E7FF] dark:bg-[#D7E7FF]/80' : ''
                  }`}
                >
                  <div className={`flex items-center justify-center w-10 h-10 border-2 fresh:border border-black fresh:border-slate-200 mb-4 ${
                    isHero ? 'bg-[#4285F4] text-white border-black fresh:bg-[#4285F4] fresh:text-white fresh:border-slate-200' : 'bg-[#4285F4] text-white border-black fresh:border-slate-200'
                  }`}>
                    <Icon className="w-5 h-5" strokeWidth={2.5} />
                  </div>
                  <h3 className={`text-base font-bold ${isHero ? 'text-black' : 'text-black dark:text-white'}`}>{cap.title}</h3>
                  <p className={`mt-2 text-sm leading-relaxed ${isHero ? 'text-[#1b3a66]' : 'text-slate-600 dark:text-slate-400'}`}>{cap.desc}</p>
                  {cap.variant === 'command' && <CommandBar />}
                  {cap.variant === 'pdf' && <PdfPreview />}
                </motion.div>
              )
            })}
          </div>
        </div>
      </section>

      {/* 使用流程区：三步 */}
      <section className="px-6 py-16 bg-[#fffdf8] border-y-[1.5px] border-black fresh:border-slate-200 dark:border-white">
        <div className="max-w-5xl mx-auto">
          <motion.div {...reveal} className="max-w-2xl mb-10">
            <div className="mb-3 inline-flex bg-[#D7E7FF] px-2 py-1 text-[10px] font-black uppercase fresh:normal-case tracking-[0.06em] text-[#1a73e8]">
              // WORKFLOW
            </div>
            <h2 className="text-3xl sm:text-4xl font-serif font-bold tracking-tight text-black dark:text-white">
              三步：把零散经历变成能投的简历
            </h2>
            <p className="mt-3 text-base text-slate-600 dark:text-slate-400 leading-relaxed">
              从输入到导出，全程 AI 协助，不需要排版，不需要纠结措辞。
            </p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-0">
            {STEPS.map((step, i) => {
              const Icon = step.icon
              return (
                <motion.div
                  key={step.title}
                  initial={reduceMotion ? false : { opacity: 0, y: 24 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.55, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  className="border border-black fresh:border-slate-200 bg-white p-6 dark:border-white dark:bg-slate-900"
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center justify-center w-11 h-11 border-2 fresh:border border-black fresh:border-slate-200 bg-[#D7E7FF] text-black dark:border-white">
                      <Icon className="w-5 h-5" strokeWidth={2.5} />
                    </div>
                    <span className="text-4xl font-serif font-black text-[#1a73e8] leading-none select-none" style={{ WebkitTextStroke: '1.5px #0a0a0a' }}>
                      {i + 1}
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-black dark:text-white">{step.title}</h3>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 leading-relaxed">{step.desc}</p>
                </motion.div>
              )
            })}
          </div>
        </div>
      </section>

      {/* FAQ 区 */}
      <section className="px-6 py-16">
        <div className="max-w-3xl mx-auto">
          <motion.div {...reveal} className="mb-10">
            <div className="mb-3 inline-flex bg-[#D7E7FF] px-2 py-1 text-[10px] font-black uppercase fresh:normal-case tracking-[0.06em] text-[#1a73e8]">
              // FAQ
            </div>
            <h2 className="text-3xl sm:text-4xl font-serif font-bold tracking-tight text-black dark:text-white">
              常见问题
            </h2>
          </motion.div>

          <div className="border-2 fresh:border border-black fresh:border-slate-200 dark:border-white">
            {FAQ_ITEMS.map((item, i) => {
              const open = openFaq === i
              return (
                <div key={item.q}>
                  <button
                    type="button"
                    onClick={() => setOpenFaq(open ? null : i)}
                    aria-expanded={open}
                    className="w-full flex items-center justify-between gap-4 py-5 px-6 text-left border-b border-black fresh:border-slate-200 dark:border-white last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors"
                  >
                    <span className="text-[15px] sm:text-base font-bold text-black dark:text-white">
                      {item.q}
                    </span>
                    <ChevronRight
                      className={`w-5 h-5 shrink-0 text-slate-400 transition-transform ${open ? 'rotate-90' : ''}`}
                    />
                  </button>
                  <AnimatePresence initial={false}>
                    {open && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                        className="overflow-hidden"
                      >
                        <p className="pb-5 px-6 text-[15px] leading-relaxed text-slate-600 dark:text-slate-400">
                          {item.a}
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* 结尾 CTA 区块 */}
      <section className="px-6 pb-16">
        <motion.div
          {...reveal}
          className="max-w-5xl mx-auto border-2 fresh:border border-black fresh:border-slate-200 bg-[#D7E7FF] shadow-[6px_6px_0px_0px_#000000] fresh:shadow-lg"
        >
          <div className="p-10 sm:p-14 text-center">
            <div className="mb-3 inline-flex bg-white px-2 py-1 text-[10px] font-bold uppercase fresh:normal-case tracking-[0.06em] text-blue-700 border border-slate-200">
              // READY?
            </div>
            <h2 className="text-3xl sm:text-4xl font-serif font-bold tracking-tight text-black">
              开始制作你的简历
            </h2>
            <p className="mt-4 text-base text-[#1b3a66] max-w-md mx-auto leading-relaxed font-semibold">
              打开就能写，专业排版一键导出。
            </p>
            <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
              <button
                onClick={() => navigate('/create-new')}
                className="w-full sm:w-auto px-7 py-3.5 border-2 fresh:border border-black fresh:border-slate-200 bg-black text-white font-bold text-base hover:bg-slate-800 active:translate-x-[2px] active:translate-y-[2px] active:shadow-none transition-all shadow-[4px_4px_0px_0px_#0a0a0a] fresh:shadow-md"
              >
                开始创建
                <ChevronRight className="inline w-5 h-5 ml-2" strokeWidth={2.5} />
              </button>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full sm:w-auto px-7 py-3.5 border-2 fresh:border border-black fresh:border-slate-200 bg-white text-black font-bold text-base hover:bg-slate-100 active:translate-x-[2px] active:translate-y-[2px] active:shadow-none transition-all shadow-[4px_4px_0px_0px_#0a0a0a] fresh:shadow-md"
              >
                <Github className="inline w-5 h-5 mr-2" />
                GitHub 点个 Star
              </a>
            </div>
          </div>
        </motion.div>
      </section>

      {/* 底部信息 */}
      <footer className="border-t-[1.5px] border-black fresh:border-slate-200 dark:border-white px-6 py-8 bg-[#F6F3EC] fresh:bg-slate-50">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#4285F4] flex items-center justify-center border border-black fresh:border-slate-200 shrink-0">
              <span className="text-white font-mono fresh:font-sans font-black text-xs italic">RA</span>
            </div>
            <span className="text-sm font-mono fresh:font-sans font-bold text-black dark:text-white">Resume.AI</span>
            <BetaBadge className="-ml-0.5 translate-y-[-5px]" />
            <span className="text-sm text-slate-500 dark:text-slate-400">公益 AI 简历制作</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
            <Link
              to="/terms"
              className="text-sm font-mono fresh:font-sans text-slate-500 dark:text-slate-400 hover:text-black dark:hover:text-white transition-colors"
            >
              服务条款
            </Link>
            <Link
              to="/privacy"
              className="text-sm font-mono fresh:font-sans text-slate-500 dark:text-slate-400 hover:text-black dark:hover:text-white transition-colors"
            >
              隐私政策
            </Link>
            <Link
              to="/refund"
              className="text-sm font-mono fresh:font-sans text-slate-500 dark:text-slate-400 hover:text-black dark:hover:text-white transition-colors"
            >
              退款政策
            </Link>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm font-mono fresh:font-sans text-slate-500 dark:text-slate-400 hover:text-black dark:hover:text-white transition-colors"
            >
              <Github className="w-4 h-4" />
              开源于 GitHub
            </a>
          </div>
        </div>
        {/* ICP 备案号（工信部合规要求：首页底部展示并链接至备案官网） */}
        <div className="max-w-5xl mx-auto mt-4 text-center sm:text-right">
          <a
            href="https://beian.miit.gov.cn"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-mono fresh:font-sans text-slate-400 dark:text-slate-500 hover:text-black dark:hover:text-white transition-colors"
          >
            粤ICP备2026011127号-2
          </a>
        </div>
      </footer>

      {/* 左下角登录按钮 */}
      <motion.div
        ref={logoutMenuRef}
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.5 }}
        className="fixed bottom-6 left-6 z-50"
      >
        {isAuthenticated ? (
          <div className="relative">
            <div
              className="flex items-center gap-2.5 pl-2 pr-4 py-2 border-2 fresh:border border-black fresh:border-slate-200 bg-white cursor-pointer hover:bg-slate-100 active:translate-x-[1px] fresh:active:translate-x-0 active:translate-y-[1px] fresh:active:translate-y-0 active:shadow-none transition-all shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
              onClick={() => setShowLogoutMenu(!showLogoutMenu)}
            >
              <Avatar
                src={user?.image}
                name={user?.username}
                email={user?.email}
                className="w-8 h-8"
                textClassName="text-sm"
              />
              <span className="text-sm font-mono fresh:font-sans font-bold text-black max-w-[150px] truncate">
                {user?.username || user?.email}
              </span>
            </div>

            {/* 退出按钮下拉菜单 */}
            <AnimatePresence>
              {showLogoutMenu && (
                <motion.div
                  initial={{ opacity: 0, y: -10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -10, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className="absolute bottom-full left-0 mb-2 min-w-[140px] border-2 fresh:border border-black fresh:border-slate-200 bg-white shadow-[4px_4px_0px_0px_#000000] fresh:shadow-md"
                >
                  <button
                    type="button"
                    onClick={() => {
                      setShowLogoutMenu(false)
                      logout()
                    }}
                    className="w-full flex items-center justify-center gap-2 whitespace-nowrap px-4 py-2.5 text-sm font-bold text-red-600 hover:bg-red-50 transition-colors"
                  >
                    <LogOut className="w-4 h-4" />
                    退出登录
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => openModal('login')}
            className="flex items-center gap-2.5 pl-2 pr-5 py-2 border-2 fresh:border border-black fresh:border-slate-200 bg-white hover:bg-slate-100 active:translate-x-[1px] fresh:active:translate-x-0 active:translate-y-[1px] fresh:active:translate-y-0 active:shadow-none transition-all shadow-[2px_2px_0px_0px_#000000] fresh:shadow-sm"
          >
            <span className="w-8 h-8 border-2 fresh:border border-black fresh:border-slate-200 bg-[#4285F4] flex items-center justify-center shrink-0">
              <LogIn className="w-4 h-4 text-white" strokeWidth={2.5} />
            </span>
            <span className="text-sm font-mono fresh:font-sans font-bold text-black">登录 / 注册</span>
          </button>
        )}
      </motion.div>
    </div>
  )
}
