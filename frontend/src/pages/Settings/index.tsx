import { toast } from '@/lib/toast'
/**
 * 设置页面：独立界面
 * 包含：AI 与 OCR 服务配置、账号与权限、主题、语言、PDF 导出偏好、快捷键
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Shield,
  Palette,
  Languages,
  Keyboard,
  FolderOpen,
  KeyRound,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import WorkspaceLayout from '@/pages/WorkspaceLayout'
import { Avatar } from '@/components/Avatar'
import { useAuth } from '@/contexts/AuthContext'
import { useTheme } from '@/hooks/useTheme'
import type { Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { getAuthHeaders } from '@/lib/authHeaders'
import { canUseAdminFeature, getApiBaseUrl, getRuntimeEnv } from '@/lib/runtimeEnv'
import {
  getPDFExportPreferences,
  setPDFExportPreferences,
  supportsDirectoryPicker,
  saveDefaultPDFDirectoryHandle,
  hasDefaultPDFDirectory,
  clearDefaultPDFDirectoryHandle,
  getDefaultPDFDirectoryLabel,
} from '@/services/pdfExportPreferences'

const LANGUAGE_KEY = 'app-language'

type ProviderId = 'deepseek' | 'zhipu'

interface ProviderKeyStatus {
  configured: boolean
  preview: string
  env_key?: string
  model?: string
}

interface KeysStatusResponse {
  deepseek: ProviderKeyStatus
  zhipu: ProviderKeyStatus
}

interface ProviderTestState {
  status: 'idle' | 'testing' | 'ok' | 'error'
  error?: string
}

function getRoleFromToken(): string {
  // 2026-07-17 身份统一：旧 JWT 解码分支已删，角色唯一来源 = auth_user
  // （AuthContext 从 /api/auth/me(entitlements) 回填后落盘）。
  try {
    const authUserRaw = localStorage.getItem('auth_user')
    if (authUserRaw) {
      const authUser = JSON.parse(authUserRaw)
      return String(authUser?.role || '').toLowerCase()
    }
    return ''
  } catch {
    return ''
  }
}

function isLocalHostEnv(): boolean {
  if (import.meta.env.DEV && getRuntimeEnv() === 'local') return true
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    return host === 'localhost' || host === '127.0.0.1'
  }
  return false
}

const LANG_OPTIONS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
]

const SHORTCUTS = [
  { action: '打开命令面板', keys: ['Ctrl', 'K'] },
  { action: '保存当前简历', keys: ['Ctrl', 'S'] },
  { action: '下载 PDF', keys: ['Ctrl', 'D'] },
]

function Card({
  icon,
  title,
  desc,
  badge,
  headerAction,
  children,
}: {
  icon: React.ReactNode
  title: string
  desc?: React.ReactNode
  badge?: React.ReactNode
  headerAction?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
      <div className="px-5 pt-5 pb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 flex items-center justify-center">
              {icon}
            </div>
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">{title}</h2>
            {badge}
          </div>
          {desc && <p className="text-sm text-slate-500 dark:text-slate-400 mt-2">{desc}</p>}
        </div>
        {headerAction}
      </div>
      <div className="px-5 pb-5">{children}</div>
    </section>
  )
}

export default function SettingsPage() {
  const { user, isAuthenticated } = useAuth()
  const roleFromToken = getRoleFromToken()
  const [liveRole, setLiveRole] = useState<string>('')
  const { theme, setTheme } = useTheme()
  // 深色模式功能仅管理员可见/可用
  const canUseDarkMode = isAuthenticated && canUseAdminFeature()
  const canManageKeys =
    isLocalHostEnv() ||
    liveRole === 'admin' ||
    roleFromToken === 'admin' ||
    canUseAdminFeature()

  // 从 /api/auth/me 实时读 role（用 getApiBaseUrl 确保经过 BetterAuth 代理层）
  useEffect(() => {
    const url = `${getApiBaseUrl()}/api/auth/me`
    fetch(url, { headers: getAuthHeaders(), credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.role) setLiveRole(String(data.role).toLowerCase())
      })
      .catch(() => {})
  }, [])

  // ============ AI 与 OCR 密钥管理状态 ============
  const [keysLoading, setKeysLoading] = useState(false)
  const [keysStatus, setKeysStatus] = useState<KeysStatusResponse>({
    deepseek: { configured: false, preview: '', env_key: 'DEEPSEEK_API_KEY', model: 'deepseek-flash' },
    zhipu: { configured: false, preview: '', env_key: 'ZHIPU_API_KEY', model: 'glm-ocr' },
  })
  const [deepseekInput, setDeepseekInput] = useState('')
  const [zhipuInput, setZhipuInput] = useState('')
  const [showDeepseekKey, setShowDeepseekKey] = useState(false)
  const [showZhipuKey, setShowZhipuKey] = useState(false)
  const [savingProvider, setSavingProvider] = useState<ProviderId | null>(null)
  const [testingAll, setTestingAll] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<ProviderId | null>(null)
  const [testStates, setTestStates] = useState<Record<ProviderId, ProviderTestState>>({
    deepseek: { status: 'idle' },
    zhipu: { status: 'idle' },
  })

  const fetchKeysStatus = useCallback(async () => {
    if (!canManageKeys) return
    setKeysLoading(true)
    try {
      const resp = await fetch(`${getApiBaseUrl()}/api/config/keys`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (!resp.ok) return
      const data = await resp.json()
      setKeysStatus({
        deepseek: {
          configured: Boolean(data?.deepseek?.configured),
          preview: data?.deepseek?.preview || '',
          env_key: data?.deepseek?.env_key || 'DEEPSEEK_API_KEY',
          model: data?.deepseek?.model || 'deepseek-flash',
        },
        zhipu: {
          configured: Boolean(data?.zhipu?.configured),
          preview: data?.zhipu?.preview || '',
          env_key: data?.zhipu?.env_key || 'ZHIPU_API_KEY',
          model: data?.zhipu?.model || 'glm-ocr',
        },
      })
    } catch {
      // 忽略首次探测静默错误
    } finally {
      setKeysLoading(false)
    }
  }, [canManageKeys])

  useEffect(() => {
    fetchKeysStatus()
  }, [fetchKeysStatus])

  const handleSaveKey = async (provider: ProviderId) => {
    const raw = (provider === 'deepseek' ? deepseekInput : zhipuInput).trim()
    if (!raw) {
      toast.error('请先输入新的 API Key 再点击保存')
      return
    }
    setSavingProvider(provider)
    try {
      const payload =
        provider === 'deepseek'
          ? { deepseek_key: raw }
          : { zhipu_key: raw }
      const resp = await fetch(`${getApiBaseUrl()}/api/config/keys`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify(payload),
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err?.detail || `HTTP ${resp.status}`)
      }
      if (provider === 'deepseek') setDeepseekInput('')
      else setZhipuInput('')
      setTestStates((prev) => ({ ...prev, [provider]: { status: 'idle' } }))
      await fetchKeysStatus()
      toast.success(
        `${provider === 'deepseek' ? 'DeepSeek' : '智谱 GLM-OCR'} 密钥已保存并立即生效`
      )
    } catch (e: any) {
      toast.error(`保存失败: ${e?.message || '请稍后重试'}`)
    } finally {
      setSavingProvider(null)
    }
  }

  const handleDeleteKey = async (provider: ProviderId) => {
    setConfirmDelete(null)
    try {
      const resp = await fetch(`${getApiBaseUrl()}/api/config/keys/${provider}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err?.detail || `HTTP ${resp.status}`)
      }
      setTestStates((prev) => ({ ...prev, [provider]: { status: 'idle' } }))
      await fetchKeysStatus()
      toast.success(`已删除 ${provider === 'deepseek' ? 'DeepSeek' : '智谱 GLM-OCR'} 密钥`)
    } catch (e: any) {
      toast.error(`删除失败: ${e?.message || '请稍后重试'}`)
    }
  }

  const handleTestProvider = async (provider?: ProviderId) => {
    const targets: ProviderId[] = provider ? [provider] : ['deepseek', 'zhipu']
    if (!provider) setTestingAll(true)
    setTestStates((prev) => {
      const next = { ...prev }
      for (const p of targets) {
        if (keysStatus[p].configured) {
          next[p] = { status: 'testing' }
        }
      }
      return next
    })

    try {
      const query = provider ? `?provider=${provider}` : ''
      const resp = await fetch(`${getApiBaseUrl()}/api/ai/test-keys${query}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err?.detail || `HTTP ${resp.status}`)
      }
      const data = await resp.json()
      setTestStates((prev) => {
        const next = { ...prev }
        for (const p of targets) {
          const item = data?.[p]
          if (!item || !item.configured) {
            next[p] = { status: 'idle' }
          } else if (item.ok) {
            next[p] = { status: 'ok' }
          } else {
            next[p] = { status: 'error', error: item.error || '连通性测试未通过' }
          }
        }
        return next
      })

      if (provider) {
        const res = data?.[provider]
        if (res?.ok) {
          toast.success(`${provider === 'deepseek' ? 'DeepSeek' : '智谱 GLM-OCR'} 接口连通正常`)
        } else {
          toast.error(`检测未通过: ${res?.error || '请检查密钥是否有效'}`)
        }
      } else {
        const allOk = targets.every((p) => !keysStatus[p].configured || data?.[p]?.ok)
        if (allOk) {
          toast.success('已配置密钥连通性检测通过')
        } else {
          toast.error('部分密钥检测未通过，请查看具体报错提示')
        }
      }
    } catch (e: any) {
      setTestStates((prev) => {
        const next = { ...prev }
        for (const p of targets) {
          next[p] = { status: 'error', error: e?.message || '请求失败' }
        }
        return next
      })
      toast.error(`检测失败: ${e?.message || '请稍后重试'}`)
    } finally {
      if (!provider) setTestingAll(false)
    }
  }

  const [displayName, setDisplayName] = useState(user?.username ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [language, setLanguage] = useState(() => {
    try {
      return localStorage.getItem(LANGUAGE_KEY) || 'zh'
    } catch {
      return 'zh'
    }
  })
  const [saved, setSaved] = useState(false)
  const [pdfPrefs, setPdfPrefs] = useState(() => getPDFExportPreferences())
  const [hasDefaultPdfDir, setHasDefaultPdfDir] = useState(false)
  const [defaultPdfDirLabel, setDefaultPdfDirLabel] = useState<string | null>(null)
  const [savingPdfDir, setSavingPdfDir] = useState(false)

  useEffect(() => {
    if (user) {
      setDisplayName(user.username)
      setEmail(user.email ?? '')
    }
  }, [user])

  useEffect(() => {
    hasDefaultPDFDirectory()
      .then(setHasDefaultPdfDir)
      .catch(() => setHasDefaultPdfDir(false))
    setDefaultPdfDirLabel(getDefaultPDFDirectoryLabel())
  }, [])

  const handleSaveAccount = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  const handleLanguageChange = (v: string) => {
    setLanguage(v)
    try {
      localStorage.setItem(LANGUAGE_KEY, v)
    } catch {}
  }

  const handlePDFBehaviorChange = (behavior: 'alwaysAsk' | 'preferDefault') => {
    const next = { behavior }
    setPdfPrefs(next)
    setPDFExportPreferences(next)
  }

  const handlePickPDFDirectory = async () => {
    if (!supportsDirectoryPicker()) {
      toast.error('当前浏览器不支持默认路径设置，请使用最新版 Chromium 浏览器。')
      return
    }
    setSavingPdfDir(true)
    try {
      const dirHandle = await (window as any).showDirectoryPicker({
        mode: 'readwrite',
      })
      await saveDefaultPDFDirectoryHandle(dirHandle)
      setHasDefaultPdfDir(true)
      setDefaultPdfDirLabel(getDefaultPDFDirectoryLabel())
      if (pdfPrefs.behavior !== 'preferDefault') {
        const next = { behavior: 'preferDefault' as const }
        setPdfPrefs(next)
        setPDFExportPreferences(next)
      }
      toast.success('默认 PDF 保存路径设置成功')
    } catch (error: any) {
      if (error?.name !== 'AbortError') {
        console.error('设置默认 PDF 路径失败:', error)
        toast.error('设置失败，请重试')
      }
    } finally {
      setSavingPdfDir(false)
    }
  }

  const handleClearPDFDirectory = async () => {
    try {
      await clearDefaultPDFDirectoryHandle()
      setHasDefaultPdfDir(false)
      setDefaultPdfDirLabel(null)
      toast.error('已清除默认 PDF 保存路径')
    } catch (error) {
      console.error('清除默认 PDF 路径失败:', error)
      toast.error('清除失败，请重试')
    }
  }

  const readyCount =
    (keysStatus.deepseek.configured ? 1 : 0) + (keysStatus.zhipu.configured ? 1 : 0)

  return (
    <WorkspaceLayout>
      <div className="h-full overflow-y-auto bg-slate-50 dark:bg-slate-950">
        <div className="max-w-3xl mx-auto p-6 sm:p-8 space-y-6">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">设置</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              管理账号、AI 与 OCR 密钥、显示偏好与工作区行为。
            </p>
          </div>

          {canManageKeys && (
            <Card
              icon={<KeyRound className="w-4 h-4" />}
              title="AI 与 OCR 服务配置"
              badge={
                <span
                  className={cn(
                    'px-2 py-0.5 text-xs font-semibold rounded-full',
                    readyCount === 2
                      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                      : readyCount === 1
                        ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                        : 'bg-red-500/15 text-red-600 dark:text-red-400'
                  )}
                >
                  {readyCount} / 2 已就绪
                </span>
              }
              desc={
                <>
                  配置驱动系统所需的 2 个核心密钥，保存后直接写入服务端{' '}
                  <code className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-xs font-mono">
                    .env
                  </code>{' '}
                  并立即生效（无需重启后端）。
                </>
              }
              headerAction={
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => fetchKeysStatus()}
                    disabled={keysLoading}
                    title="刷新配置状态"
                    className="inline-flex items-center gap-1 px-2.5 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition disabled:opacity-50"
                  >
                    <RefreshCw className={cn('w-3.5 h-3.5', keysLoading && 'animate-spin')} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleTestProvider()}
                    disabled={testingAll || readyCount === 0}
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {testingAll ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                    )}
                    <span>{testingAll ? '正在检测...' : '一键检测连通性'}</span>
                  </button>
                </div>
              }
            >
              <div className="space-y-4 border-t border-slate-100 dark:border-slate-800 pt-4">
                {/* 1. DeepSeek 官方 API Key */}
                <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 p-4 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
                          1. DeepSeek 官方 API Key
                        </span>
                        <span className="px-2 py-0.5 text-xs font-semibold rounded bg-indigo-500/15 text-indigo-600 dark:text-indigo-400">
                          必填 · 核心对话与生成
                        </span>
                        <span
                          className={cn(
                            'px-2 py-0.5 text-xs font-semibold rounded',
                            keysStatus.deepseek.configured
                              ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                              : 'bg-red-500/15 text-red-600 dark:text-red-400'
                          )}
                        >
                          {keysStatus.deepseek.configured ? '● 已配置' : '○ 未配置'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        用于 AI 助手对话、简历诊断、润色改写及导入后的 JSON 结构化组装。默认模型：
                        <code className="font-mono ml-1 text-slate-700 dark:text-slate-300">
                          {keysStatus.deepseek.model || 'deepseek-flash'}
                        </code>
                      </p>
                    </div>
                    <a
                      href="https://platform.deepseek.com/api_keys"
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
                    >
                      前往 DeepSeek 开放平台获取
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>

                  {keysStatus.deepseek.configured && (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-slate-500 dark:text-slate-400">
                          当前生效密钥 (<code className="font-mono">DEEPSEEK_API_KEY</code>)：
                        </span>
                        <code className="font-mono font-semibold text-slate-800 dark:text-slate-100">
                          {keysStatus.deepseek.preview}
                        </code>
                        {testStates.deepseek.status === 'testing' && (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/15 text-amber-600 dark:text-amber-400">
                            检测中...
                          </span>
                        )}
                        {testStates.deepseek.status === 'ok' && (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                            ✓ 连通正常
                          </span>
                        )}
                        {testStates.deepseek.status === 'error' && (
                          <span
                            title={testStates.deepseek.error}
                            className="px-2 py-0.5 rounded text-xs font-medium bg-red-500/15 text-red-600 dark:text-red-400"
                          >
                            ✗ 检测失败: {testStates.deepseek.error}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => handleTestProvider('deepseek')}
                          disabled={testStates.deepseek.status === 'testing'}
                          className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium disabled:opacity-50"
                        >
                          测试
                        </button>
                        {confirmDelete === 'deepseek' ? (
                          <button
                            type="button"
                            onClick={() => handleDeleteKey('deepseek')}
                            onBlur={() => setConfirmDelete(null)}
                            className="px-2 py-0.5 rounded bg-red-600 text-white font-semibold"
                          >
                            确认删除
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDelete('deepseek')}
                            className="text-red-600 dark:text-red-400 hover:underline font-medium"
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="flex flex-col sm:flex-row gap-2">
                    <div className="relative flex-1">
                      <input
                        type={showDeepseekKey ? 'text' : 'password'}
                        value={deepseekInput}
                        onChange={(e) => setDeepseekInput(e.target.value)}
                        placeholder={
                          keysStatus.deepseek.configured
                            ? '输入新的 sk-... 密钥以覆盖（留空则保持不变）'
                            : '输入 DeepSeek API Key（sk-...）'
                        }
                        className="w-full pl-3 pr-10 py-2 text-sm font-mono rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                      />
                      <button
                        type="button"
                        onClick={() => setShowDeepseekKey((v) => !v)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                        title={showDeepseekKey ? '隐藏密钥' : '显示密钥'}
                      >
                        {showDeepseekKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleSaveKey('deepseek')}
                      disabled={savingProvider === 'deepseek'}
                      className="px-4 py-2 text-sm font-semibold rounded-lg bg-slate-800 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-200 transition shrink-0 disabled:opacity-50"
                    >
                      {savingProvider === 'deepseek' ? '保存中...' : '保存 DeepSeek 密钥'}
                    </button>
                  </div>
                </div>

                {/* 2. 智谱 GLM-OCR API Key */}
                <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 p-4 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
                          2. 智谱 GLM-OCR API Key
                        </span>
                        <span className="px-2 py-0.5 text-xs font-semibold rounded bg-amber-500/15 text-amber-600 dark:text-amber-400">
                          核心推荐 · PDF 与图片导入
                        </span>
                        <span
                          className={cn(
                            'px-2 py-0.5 text-xs font-semibold rounded',
                            keysStatus.zhipu.configured
                              ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                              : 'bg-red-500/15 text-red-600 dark:text-red-400'
                          )}
                        >
                          {keysStatus.zhipu.configured ? '● 已配置' : '○ 未配置'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        用于上传 PDF 简历与图片简历时的版面识别与文字提取。默认模型：
                        <code className="font-mono ml-1 text-slate-700 dark:text-slate-300">
                          {keysStatus.zhipu.model || 'glm-ocr'}
                        </code>
                      </p>
                    </div>
                    <a
                      href="https://open.bigmodel.cn/usercenter/apikeys"
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
                    >
                      前往智谱清言开放平台获取
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>

                  {keysStatus.zhipu.configured && (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-slate-500 dark:text-slate-400">
                          当前生效密钥 (<code className="font-mono">ZHIPU_API_KEY</code>)：
                        </span>
                        <code className="font-mono font-semibold text-slate-800 dark:text-slate-100">
                          {keysStatus.zhipu.preview}
                        </code>
                        {testStates.zhipu.status === 'testing' && (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/15 text-amber-600 dark:text-amber-400">
                            检测中...
                          </span>
                        )}
                        {testStates.zhipu.status === 'ok' && (
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                            ✓ 连通正常
                          </span>
                        )}
                        {testStates.zhipu.status === 'error' && (
                          <span
                            title={testStates.zhipu.error}
                            className="px-2 py-0.5 rounded text-xs font-medium bg-red-500/15 text-red-600 dark:text-red-400"
                          >
                            ✗ 检测失败: {testStates.zhipu.error}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => handleTestProvider('zhipu')}
                          disabled={testStates.zhipu.status === 'testing'}
                          className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium disabled:opacity-50"
                        >
                          测试
                        </button>
                        {confirmDelete === 'zhipu' ? (
                          <button
                            type="button"
                            onClick={() => handleDeleteKey('zhipu')}
                            onBlur={() => setConfirmDelete(null)}
                            className="px-2 py-0.5 rounded bg-red-600 text-white font-semibold"
                          >
                            确认删除
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDelete('zhipu')}
                            className="text-red-600 dark:text-red-400 hover:underline font-medium"
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="flex flex-col sm:flex-row gap-2">
                    <div className="relative flex-1">
                      <input
                        type={showZhipuKey ? 'text' : 'password'}
                        value={zhipuInput}
                        onChange={(e) => setZhipuInput(e.target.value)}
                        placeholder={
                          keysStatus.zhipu.configured
                            ? '输入新的智谱 API Key（格式如 xxx.xxx，留空保持不变）'
                            : '输入智谱 GLM API Key（用于 PDF 与图片 OCR）'
                        }
                        className="w-full pl-3 pr-10 py-2 text-sm font-mono rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                      />
                      <button
                        type="button"
                        onClick={() => setShowZhipuKey((v) => !v)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                        title={showZhipuKey ? '隐藏密钥' : '显示密钥'}
                      >
                        {showZhipuKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleSaveKey('zhipu')}
                      disabled={savingProvider === 'zhipu'}
                      className="px-4 py-2 text-sm font-semibold rounded-lg bg-slate-800 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-200 transition shrink-0 disabled:opacity-50"
                    >
                      {savingProvider === 'zhipu' ? '保存中...' : '保存智谱密钥'}
                    </button>
                  </div>
                </div>
              </div>
            </Card>
          )}

          <Card icon={<Shield className="w-4 h-4" />} title="账号与权限" desc="账号基础信息与当前权限角色。">
            <div className="flex items-center gap-4 mb-5">
              <Avatar
                src={user?.image}
                name={displayName || user?.username}
                email={email || user?.email}
                className="w-16 h-16"
                textClassName="text-2xl"
              />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
                  {displayName || user?.username || '未设置昵称'}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">头像来自你的登录账户</p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">显示名称</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  disabled={!isAuthenticated}
                  className="w-full px-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">邮箱</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={!isAuthenticated}
                  className="w-full px-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <div className="text-sm text-slate-500 dark:text-slate-400">
                当前角色：<span className="font-semibold text-slate-700 dark:text-slate-200">{liveRole || roleFromToken || (user as any)?.role || 'user'}</span>
              </div>
              <button
                type="button"
                onClick={handleSaveAccount}
                className="px-4 py-2 text-sm font-semibold rounded-lg bg-slate-800 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-200"
              >
                {saved ? '已保存' : '保存修改'}
              </button>
            </div>
          </Card>

          {canUseDarkMode && (
          <Card icon={<Palette className="w-4 h-4" />} title="主题" desc="切换工作区外观主题。">
            <div className="flex flex-wrap gap-2">
              {[
                { value: 'light' as Theme, label: '亮色' },
                { value: 'dark' as Theme, label: '深色' },
                { value: 'system' as Theme, label: '系统' },
              ].map((opt) => {
                const active = theme === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setTheme(opt.value)}
                    className={cn(
                      'px-4 py-2 rounded-lg border text-sm font-medium transition-all',
                      active
                        ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-400 text-indigo-700 dark:text-indigo-300'
                        : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300'
                    )}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </Card>
          )}

          <Card icon={<Languages className="w-4 h-4" />} title="语言" desc="设置系统展示语言。">
            <select
              value={language}
              onChange={(e) => handleLanguageChange(e.target.value)}
              className="w-full sm:w-64 px-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            >
              {LANG_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </Card>

          <Card icon={<FolderOpen className="w-4 h-4" />} title="PDF 导出偏好" desc="设置另存为 PDF 时的默认保存行为。">
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">导出行为</label>
                <div className="flex flex-wrap gap-2">
                  {[
                    { value: 'alwaysAsk' as const, label: '每次询问保存位置' },
                    { value: 'preferDefault' as const, label: '优先使用默认路径' },
                  ].map((opt) => {
                    const active = pdfPrefs.behavior === opt.value
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => handlePDFBehaviorChange(opt.value)}
                        className={cn(
                          'px-4 py-2 rounded-lg border text-sm font-medium transition-all',
                          active
                            ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-400 text-indigo-700 dark:text-indigo-300'
                            : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300'
                        )}
                      >
                        {opt.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 p-3">
                <div className="text-sm text-slate-700 dark:text-slate-200">
                  默认路径状态：
                  <span className={cn(
                    'ml-1 font-semibold',
                    hasDefaultPdfDir ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500 dark:text-slate-400'
                  )}>
                    {hasDefaultPdfDir ? '已设置' : '未设置'}
                  </span>
                </div>
                <div className="text-sm text-slate-700 dark:text-slate-200 mt-1">
                  当前默认保存路径：
                  <span className={cn(
                    'ml-1 font-medium',
                    hasDefaultPdfDir ? 'text-slate-700 dark:text-slate-200' : 'text-slate-500 dark:text-slate-400'
                  )}>
                    {hasDefaultPdfDir
                      ? (defaultPdfDirLabel ? `${defaultPdfDirLabel}（仅显示目录名）` : '已设置（目录名不可用）')
                      : '未设置'}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  基于浏览器文件权限能力，若权限失效会自动回退为手动选择路径。
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handlePickPDFDirectory}
                    disabled={savingPdfDir}
                    className="px-3 py-2 text-sm font-semibold rounded-lg bg-slate-800 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {savingPdfDir ? '设置中...' : '选择默认保存路径'}
                  </button>
                  <button
                    type="button"
                    onClick={handleClearPDFDirectory}
                    disabled={!hasDefaultPdfDir}
                    className="px-3 py-2 text-sm font-medium rounded-lg border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    清除默认路径
                  </button>
                </div>
              </div>
            </div>
          </Card>

          <Card icon={<Keyboard className="w-4 h-4" />} title="快捷键" desc="常用操作键位说明。">
            <div className="space-y-2">
              {SHORTCUTS.map((item) => (
                <div key={item.action} className="flex items-center justify-between rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 px-3 py-2">
                  <span className="text-sm text-slate-700 dark:text-slate-200">{item.action}</span>
                  <span className="inline-flex items-center gap-1">
                    {item.keys.map((k) => (
                      <kbd key={k} className="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-xs font-semibold text-slate-600 dark:text-slate-300">
                        {k}
                      </kbd>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </Card>

        </div>
      </div>
    </WorkspaceLayout>
  )
}
