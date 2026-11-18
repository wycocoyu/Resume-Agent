import { useSyncExternalStore } from 'react'

export type RuntimeEnv = 'local' | 'remote-dev'

export interface RuntimeFeatures {
  auth_enabled: boolean
  agent_enabled: boolean
  editor_ai_enabled: boolean
}

export interface RuntimeFeaturesSnapshot {
  authEnabled: boolean
  agentEnabled: boolean
  editorAiEnabled: boolean
  auth_enabled: boolean
  agent_enabled: boolean
  editor_ai_enabled: boolean
  loaded: boolean
}

const ENV_STORAGE_KEY = 'resume_agent_env'
const AUTH_ENABLED_OVERRIDE_KEY = 'cococv_auth_enabled_override'
const AGENT_ENABLED_OVERRIDE_KEY = 'resume_agent_enabled_override'
const DEFAULT_LOCAL_API_BASE = 'http://127.0.0.1:9000'
const DEFAULT_REMOTE_API_BASE = 'https://cococv.cn'
const TRUE_ENV_VALUES = new Set(['1', 'true', 'yes', 'on', 'enabled'])

let _runtimeFeatures: RuntimeFeatures | null = null
let _runtimeFeaturesPromise: Promise<RuntimeFeatures | null> | null = null
const _featureListeners = new Set<() => void>()
let _cachedFeaturesSnapshot: RuntimeFeaturesSnapshot | null = null

function notifyFeatureListeners(): void {
  _cachedFeaturesSnapshot = null
  _featureListeners.forEach((listener) => {
    try {
      listener()
    } catch {
      // ignore subscriber errors
    }
  })
}

function normalizeBaseUrl(url: string): string {
  const raw = String(url || '').trim()
  if (!raw) return ''
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw
  return `https://${raw}`
}

function envBaseMap(): Record<RuntimeEnv, string> {
  const legacyApiBase = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE || '')
  const localDefault = import.meta.env.PROD ? '' : DEFAULT_LOCAL_API_BASE
  const localBase =
    normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL_LOCAL || '') ||
    legacyApiBase ||
    localDefault
  const remoteBase =
    normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL_REMOTE_DEV || '') ||
    normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL_REMOTE || '') ||
    DEFAULT_REMOTE_API_BASE
  return {
    local: localBase,
    'remote-dev': remoteBase,
  }
}

function isRuntimeEnv(value: string): value is RuntimeEnv {
  return value === 'local' || value === 'remote-dev'
}

export function getDefaultRuntimeEnv(): RuntimeEnv {
  const configured = String(import.meta.env.VITE_ENV_DEFAULT || '').trim()
  return configured === 'remote-dev' ? 'remote-dev' : 'local'
}

export function getRuntimeEnv(): RuntimeEnv {
  try {
    const saved = localStorage.getItem(ENV_STORAGE_KEY)
    if (saved && isRuntimeEnv(saved)) return saved
  } catch {
    // no-op
  }
  return getDefaultRuntimeEnv()
}

export function setRuntimeEnv(env: RuntimeEnv): void {
  localStorage.setItem(ENV_STORAGE_KEY, env)
}

/**
 * 业务主机直连基址：**刻意不优先走 auth-web 代理**。
 *
 * 只有不需要 BetterAuth cookie 的接口才应该用它（典型是 PDF 渲染预览：
 * 后端用 get_current_user_optional，匿名即可渲染）。走代理意味着请求要先绕到
 * auth-web 所在区域、再跨境回源业务主机，这一段固定开销常常数倍于接口本身。
 * 需要登录态的接口（额度查询/记账、admin 端点等）必须继续用 getApiBaseUrl()。
 */
export function getDirectApiBaseUrl(env: RuntimeEnv = getRuntimeEnv()): string {
  const baseMap = envBaseMap()
  // 本地开发时：
  // - local 走同源代理（'' -> localhost:5173/api/...）
  // - remote-dev 直连远程域名，确保环境切换生效
  // 生产构建下 local 分支为 ''，即与页面同源（前端与 FastAPI 同域部署）。
  if (import.meta.env.DEV && env === 'local') return ''
  return env === 'remote-dev' ? baseMap['remote-dev'] : baseMap.local
}

export function getApiBaseUrl(env: RuntimeEnv = getRuntimeEnv()): string {
  // 本地 Vite 开发默认使用 FastAPI 直连/本地代理，不依赖可能未启动的
  // BetterAuth Web 服务。否则只要 .env 配置了 VITE_AUTH_WEB_URL，
  // /api/agent/stream 就会被改写到 localhost:3000，浏览器最终只显示
  // “Failed to fetch”，而本地 9000 后端其实是可用的。
  if (import.meta.env.DEV && env === 'local') {
    return getDirectApiBaseUrl(env)
  }
  const authProxyBase = getAuthWebApiProxyBaseUrl()
  if (authProxyBase) return authProxyBase
  return getDirectApiBaseUrl(env)
}

export function getAuthWebBaseUrl(): string {
  return normalizeBaseUrl(import.meta.env.VITE_AUTH_WEB_URL || '')
}

export function isAuthWebEnabled(): boolean {
  return Boolean(getAuthWebBaseUrl())
}

/**
 * 本地开发时没有单独启动 BetterAuth 服务，使用后端显式开启的本地开发身份。
 * 该分支只在 Vite DEV 构建生效，生产构建永远不会自动带本地身份头。
 */
export function isLocalDevAuthEnabled(): boolean {
  if (!import.meta.env.DEV) return false
  if (!isAuthEnabled()) return false
  const configured = String(import.meta.env.VITE_LOCAL_DEV_AUTH ?? '').trim().toLowerCase()
  if (!configured) return true
  return TRUE_ENV_VALUES.has(configured)
}

export function buildAuthWebUrl(path = '/account', returnTo?: string): string {
  const base = getAuthWebBaseUrl()
  if (!base) return ''

  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(normalizedPath, `${base}/`)
  if (returnTo) {
    url.searchParams.set('returnTo', returnTo)
  }
  return url.toString()
}

export function getAuthWebApiProxyBaseUrl(): string {
  const authBase = getAuthWebBaseUrl()
  if (!authBase) return ''
  return `${authBase}/api/fastapi/proxy`
}

export function getRuntimeEnvOptions() {
  const baseMap = envBaseMap()
  return [
    { key: 'local' as const, label: '本地环境', baseUrl: baseMap.local },
    { key: 'remote-dev' as const, label: '远程开发', baseUrl: baseMap['remote-dev'] },
  ]
}

export function isAuthEnabled(): boolean {
  try {
    const override = localStorage.getItem(AUTH_ENABLED_OVERRIDE_KEY)
    if (override === 'true') return true
    if (override === 'false') return false
  } catch {
    // no-op
  }
  if (_runtimeFeatures !== null) {
    return Boolean(_runtimeFeatures.auth_enabled)
  }
  const raw = String(import.meta.env.VITE_AUTH_ENABLED ?? 'false').trim().toLowerCase()
  return TRUE_ENV_VALUES.has(raw)
}

export function setAuthEnabledOverride(enabled: boolean | null): void {
  try {
    if (enabled === null) {
      localStorage.removeItem(AUTH_ENABLED_OVERRIDE_KEY)
    } else {
      localStorage.setItem(AUTH_ENABLED_OVERRIDE_KEY, enabled ? 'true' : 'false')
    }
  } catch {
    // no-op
  }
  notifyFeatureListeners()
}

export function isAgentEnabled(): boolean {
  try {
    const override = localStorage.getItem(AGENT_ENABLED_OVERRIDE_KEY)
    if (override === 'true') return true
    if (override === 'false') return false
  } catch {
    // no-op
  }
  // 后端运行时开关已加载时优先于静态环境回退（含 DEV 模式）
  if (_runtimeFeatures !== null) {
    return Boolean(_runtimeFeatures.agent_enabled)
  }
  // 首屏默认关闭，避免加载 /api/features 前出现侧边栏 Agent 闪烁
  const raw = String(import.meta.env.VITE_AGENT_ENABLED ?? 'false').trim().toLowerCase()
  return TRUE_ENV_VALUES.has(raw)
}

export function isEditorAiEnabled(): boolean {
  if (_runtimeFeatures !== null) {
    return Boolean(_runtimeFeatures.editor_ai_enabled)
  }
  return true
}

export function isAskingModeEnabled(): boolean {
  return TRUE_ENV_VALUES.has(
    String(import.meta.env.VITE_AGENT_ASKING_MODE_ENABLED ?? 'false').trim().toLowerCase(),
  )
}

export function isAgentStructuredEventEnabled(type: string): boolean {
  return type !== 'ask_question' || isAskingModeEnabled()
}

export function filterAgentStructuredEvents<T extends { type: string }>(items: T[]): T[] {
  return items.filter((item) => isAgentStructuredEventEnabled(item.type))
}

export function setAgentEnabledOverride(enabled: boolean): void {
  localStorage.setItem(AGENT_ENABLED_OVERRIDE_KEY, enabled ? 'true' : 'false')
  notifyFeatureListeners()
}

/**
 * 从后端直连基址拉取运行时功能开关（/api/features），并通知所有订阅组件更新。
 */
export async function hydrateRuntimeFeatures(force = false): Promise<RuntimeFeatures | null> {
  if (_runtimeFeatures !== null && !force) {
    return _runtimeFeatures
  }
  if (_runtimeFeaturesPromise && !force) {
    return _runtimeFeaturesPromise
  }

  const url = `${getDirectApiBaseUrl()}/api/features`
  _runtimeFeaturesPromise = (async () => {
    try {
      const resp = await fetch(url, { cache: 'no-store' })
      if (!resp.ok) return null
      const data = (await resp.json()) as Partial<RuntimeFeatures> | null
      if (!data || typeof data !== 'object') return null
      _runtimeFeatures = {
        auth_enabled: Boolean(data.auth_enabled),
        agent_enabled: Boolean(data.agent_enabled),
        editor_ai_enabled: data.editor_ai_enabled === undefined ? true : Boolean(data.editor_ai_enabled),
      }
      notifyFeatureListeners()
      return _runtimeFeatures
    } catch {
      return null
    } finally {
      _runtimeFeaturesPromise = null
    }
  })()

  return _runtimeFeaturesPromise
}

export function subscribeRuntimeFeatures(listener: () => void): () => void {
  _featureListeners.add(listener)
  return () => {
    _featureListeners.delete(listener)
  }
}

export function getRuntimeFeaturesSnapshot(): RuntimeFeaturesSnapshot {
  const authEnabled = isAuthEnabled()
  const agentEnabled = isAgentEnabled()
  const editorAiEnabled = isEditorAiEnabled()
  const loaded = _runtimeFeatures !== null
  if (
    _cachedFeaturesSnapshot &&
    _cachedFeaturesSnapshot.authEnabled === authEnabled &&
    _cachedFeaturesSnapshot.agentEnabled === agentEnabled &&
    _cachedFeaturesSnapshot.editorAiEnabled === editorAiEnabled &&
    _cachedFeaturesSnapshot.loaded === loaded
  ) {
    return _cachedFeaturesSnapshot
  }
  _cachedFeaturesSnapshot = {
    authEnabled,
    agentEnabled,
    editorAiEnabled,
    auth_enabled: authEnabled,
    agent_enabled: agentEnabled,
    editor_ai_enabled: editorAiEnabled,
    loaded,
  }
  return _cachedFeaturesSnapshot
}

export function useRuntimeFeatures(): RuntimeFeaturesSnapshot {
  return useSyncExternalStore(
    subscribeRuntimeFeatures,
    getRuntimeFeaturesSnapshot,
    getRuntimeFeaturesSnapshot,
  )
}

export function setRuntimeFeaturesForTest(features: Partial<RuntimeFeatures> | null): void {
  if (features === null) {
    _runtimeFeatures = null
  } else {
    _runtimeFeatures = {
      auth_enabled: Boolean(features.auth_enabled),
      agent_enabled: Boolean(features.agent_enabled),
      editor_ai_enabled: features.editor_ai_enabled === undefined ? true : Boolean(features.editor_ai_enabled),
    }
  }
  _runtimeFeaturesPromise = null
  notifyFeatureListeners()
}

export function resetRuntimeFeaturesForTest(): void {
  _runtimeFeatures = null
  _runtimeFeaturesPromise = null
  notifyFeatureListeners()
}

export function getStoredAuthRole(): string {
  // 2026-07-17 身份统一：旧 JWT 解码分支已随 JWT 下架删除，角色唯一来源 = auth_user
  // （AuthContext 从 /api/auth/me(entitlements) 回填后落盘）。
  try {
    const authUserRaw = localStorage.getItem('auth_user')
    if (authUserRaw) {
      const authUser = JSON.parse(authUserRaw)
      return String(authUser?.role || '').toLowerCase()
    }
  } catch {
    // no-op
  }
  return ''
}

export function canUseAgentFeature(): boolean {
  // 仅判定 Agent 功能开关；登录态由唯一调用方 WorkspaceLayout 的 isAuthenticated 统一把关。
  // 不在此重新从 localStorage 推导登录态——BetterAuth 用 cookie 鉴权、不写 legacy auth_token，
  // 旧的 token 存在性判断会在 BetterAuth 登录态下把历史会话等 Agent 入口整体隐藏。
  return isAgentEnabled()
}

export function canUseAdminFeature(): boolean {
  // 角色即权限来源：legacy 模式从 JWT、BetterAuth 模式从 auth_user 取角色。
  // 不再要求 legacy token（BetterAuth 登录态下 auth_token 为空，会误杀管理员）。
  // 后台/运营入口仅 admin；staff/member 都没有后台权限。
  return getStoredAuthRole() === 'admin'
}
