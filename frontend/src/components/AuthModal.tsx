import React, { useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2, LogIn } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { buildAuthWebUrl, isAuthWebEnabled, useRuntimeFeatures } from '@/lib/runtimeEnv'

/**
 * 认证 Modal —— 统一认证入口。
 *
 * BetterAuth 启用时（VITE_AUTH_WEB_URL 已配置）：
 *   Modal 弹出后自动重定向到 Next.js 认证页 (/account)，
 *   所有登录/注册（Google + 账号密码）都在那里完成。
 *
 * BetterAuth 未启用时（独立部署）：
 *   不渲染任何内容（openModal 也不会被调用）。
 */
export const AuthModal: React.FC = () => {
  const { isModalOpen, closeModal } = useAuth()
  const { authEnabled } = useRuntimeFeatures()
  const authWebEnabled = authEnabled && isAuthWebEnabled()

  useEffect(() => {
    if (isModalOpen && authWebEnabled) {
      const url = buildAuthWebUrl(
        '/account',
        `${window.location.origin}${window.location.pathname}${window.location.search}`,
      )
      if (url) {
        closeModal()
        window.location.assign(url)
      }
    }
  }, [isModalOpen, authWebEnabled, closeModal])

  if (!authWebEnabled) return null

  return (
    <AnimatePresence>
      {isModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="relative w-full max-w-[400px] bg-white rounded-[32px] shadow-2xl border border-slate-100 overflow-hidden p-10 text-center"
          >
            <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-blue-500 via-indigo-500 to-violet-500" />
            <button
              onClick={closeModal}
              className="absolute top-6 right-6 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-all"
            >
              <X className="w-5 h-5" />
            </button>
            <div className="flex flex-col items-center gap-4 py-8">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
              <p className="text-slate-600 font-medium">正在跳转登录页…</p>
              <LogIn className="w-5 h-5 text-slate-300" />
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
