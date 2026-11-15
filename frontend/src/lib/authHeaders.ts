import { isLocalDevAuthEnabled } from '@/lib/runtimeEnv'

export const BETTER_AUTH_SESSION_TOKEN = 'better-auth-session'

/**
 * 2026-07-17 身份统一：旧 JWT 已全面下架，认证一律走 BetterAuth cookie
 * （configureAuthWebRequests 给同源代理请求自动带 credentials）。
 * 本函数保留签名兼容既有调用方，不再注入 Authorization Bearer。
 */
export function getAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  if (!isLocalDevAuthEnabled()) return { ...extra }
  return {
    'X-Local-Dev-User': 'codex-local-user',
    ...extra,
  }
}
