import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildAuthWebUrl,
  hydrateRuntimeFeatures,
  isAuthEnabled,
  isAuthWebEnabled,
  isLocalDevAuthEnabled,
  useRuntimeFeatures,
} from '@/lib/runtimeEnv'
import { fetchUserEntitlement } from '@/services/api'
import {
  fetchBetterAuthSession,
  fetchLegacyUserInfo,
  signOutBetterAuth,
  type BetterAuthSessionUser,
} from '@/services/betterAuthSession'
import {
  setResumeStorageSession,
  syncLocalResumesToCurrentAccount,
} from '@/services/resumeStorage'

// 2026-07-17 身份统一：id = BetterAuth "user".id（32 位字符串，唯一身份锚点）。
// 旧 JWT 登录（用户名/密码表单、localStorage auth_token、legacy_token 回跳）已全面下架，
// 登录唯一入口 = Next.js(BetterAuth)，本 Context 只承载 BetterAuth 会话态。
type User = {
  id: string
  username: string
  email?: string
  image?: string | null
  betterAuthUserId?: string
  role?: string
  credits?: number
  plan?: string
}

type AuthContextValue = {
  user: User | null
  token: string | null
  loading: boolean
  isAuthenticated: boolean
  logout: () => void
  refreshEntitlement: () => Promise<void>
  isModalOpen: boolean
  openModal: (mode?: 'login' | 'register') => void
  closeModal: () => void
  modalMode: 'login' | 'register'
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

const TOKEN_KEY = 'auth_token'   // 旧 JWT 存储键，仅用于启动时清理历史残留
const USER_KEY = 'auth_user'
/** BetterAuth 登录态的占位 token（非真实凭证）。
 * 把它当 Bearer 发出去会触发 auth-web 的 bearer 插件校验失败、连带 cookie session 一起判空，
 * 所以手动附 Authorization 头前必须用它判断“跳过 Bearer、纯走 cookie”。 */
export const BETTER_AUTH_TOKEN = 'better-auth-session'
const LOGIN_SYNC_DELAY_MS = 2500

function mapBetterAuthUser(sessionUser: BetterAuthSessionUser): User {
  return {
    id: sessionUser.id,
    username: sessionUser.name || sessionUser.email.split('@')[0],
    email: sessionUser.email,
    image: sessionUser.image,
    betterAuthUserId: sessionUser.id,
  }
}

function resumeStorageIdentity(user: User | null): string | null {
  if (!user) return null
  // 与身份统一前的 BetterAuth 用户 scoped key 保持一致（better-auth:<id>），
  // 迁移后同一账号的本地缓存命名空间不变。
  const id = user.betterAuthUserId || user.id
  return id ? `better-auth:${id}` : null
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { authEnabled, loaded: featuresLoaded } = useRuntimeFeatures()
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState<'login' | 'register'>('login')
  const hasInitializedRef = useRef(false)

  const applyAuthState = useCallback((nextUser: User | null, nextToken: string | null) => {
    setResumeStorageSession(resumeStorageIdentity(nextUser))
    setUser(nextUser)
    setToken(nextToken)
  }, [])

  useEffect(() => {
    void hydrateRuntimeFeatures()
  }, [])

  useEffect(() => {
    let cancelled = false
    const init = async () => {
      applyAuthState(null, null)
      try {
        // 清理旧 JWT 时代的本地残留（token 已无任何后端可用它）
        localStorage.removeItem(TOKEN_KEY)

        if (isLocalDevAuthEnabled()) {
          const localUser: User = {
            id: 'codex-local-user',
            username: 'local',
            email: 'local@localhost',
            betterAuthUserId: 'codex-local-user',
            role: 'user',
          }
          if (!cancelled) applyAuthState(localUser, null)
          try {
            localStorage.setItem(USER_KEY, JSON.stringify(localUser))
          } catch {
            // 本地身份仅用于开发，不影响页面继续运行
          }
          return
        }

        if (!authEnabled) {
          if (featuresLoaded) {
            localStorage.removeItem(USER_KEY)
          }
          return
        }

        if (!isAuthWebEnabled()) {
          // 未配置 BetterAuth（VITE_AUTH_WEB_URL 为空）时没有任何登录方式：
          // 旧 JWT 已下架，独立部署必须启用 auth-web（.env.example 已注明）。
          console.warn('[Auth] VITE_AUTH_WEB_URL 未配置，登录不可用（JWT 已下架）')
          return
        }

        const sessionUser = await fetchBetterAuthSession()
        if (cancelled) return
        if (!sessionUser) {
          localStorage.removeItem(USER_KEY)
          return
        }

        applyAuthState(mapBetterAuthUser(sessionUser), BETTER_AUTH_TOKEN)
        // 异步回填 role（经 proxy + trusted headers 从 entitlements 实时读），不阻塞首屏。
        void fetchLegacyUserInfo().then(({ id, role }) => {
          if (cancelled) return
          setUser((prev) => {
            if (!prev) return prev
            const next: User = { ...prev }
            if (id) next.id = id
            if (role) next.role = role
            // 角色落到 auth_user，供 getStoredAuthRole / canUseAdminFeature 同步读取。
            try {
              localStorage.setItem(USER_KEY, JSON.stringify(next))
            } catch {
              // 持久化失败不影响登录态
            }
            return next
          })
        })
        // 异步拉取额度，不阻塞首屏
        void fetchUserEntitlement().then((ent) => {
          if (cancelled) return
          setUser((prev) =>
            prev ? { ...prev, credits: ent.credits, plan: ent.plan } : prev,
          )
        }).catch(() => {/* 拉取失败不影响登录态 */})

        // 登录态就绪后延迟同步本地匿名简历到账号（原 JWT 登录后的同步时机平移到这里）
        const storageIdentity = resumeStorageIdentity(mapBetterAuthUser(sessionUser))
        window.setTimeout(() => {
          if (cancelled) return
          void syncLocalResumesToCurrentAccount(storageIdentity).catch(() => {
            // 同步失败不影响登录流程
          })
        }, LOGIN_SYNC_DELAY_MS)
      } finally {
        hasInitializedRef.current = true
        if (!cancelled) setLoading(false)
      }
    }

    void init()
    return () => {
      cancelled = true
    }
  }, [applyAuthState, authEnabled, featuresLoaded])

  const refreshEntitlement = useCallback(async () => {
    try {
      const ent = await fetchUserEntitlement()
      setUser((prev) => (prev ? { ...prev, credits: ent.credits, plan: ent.plan } : prev))
    } catch {
      // ignore
    }
  }, [])

  const logout = useCallback(() => {
    void (async () => {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      // 先关闭本地会话并中止在途简历请求，避免退出请求清 Cookie 的窗口里继续写云端。
      applyAuthState(null, null)
      await signOutBetterAuth()
    })()
  }, [applyAuthState])

  const openModal = useCallback((_mode: 'login' | 'register' = 'login') => {
    if (!isAuthEnabled() && !isLocalDevAuthEnabled()) {
      return
    }
    // 统一登录入口：重定向到 Next.js(BetterAuth) 认证页
    const url = buildAuthWebUrl('/account', `${window.location.origin}${window.location.pathname}${window.location.search}`)
    if (url) {
      window.location.assign(url)
      return
    }
    console.warn('[Auth] VITE_AUTH_WEB_URL 未配置，无法打开登录页（JWT 已下架）')
  }, [])

  const closeModal = useCallback(() => {
    setIsModalOpen(false)
  }, [])

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      isAuthenticated: Boolean(user),
      logout,
      refreshEntitlement,
      isModalOpen,
      openModal,
      closeModal,
      modalMode
    }),
    [user, token, loading, logout, refreshEntitlement, isModalOpen, openModal, closeModal, modalMode]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
