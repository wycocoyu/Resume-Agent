import React from 'react'
import { Link } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useRuntimeFeatures } from '@/lib/runtimeEnv'

export default function UserMenu() {
  const { user, isAuthenticated, logout, openModal } = useAuth()
  const { authEnabled } = useRuntimeFeatures()

  if (!isAuthenticated) {
    if (!authEnabled) return null
    return (
      <button
        onClick={() => openModal('login')}
        className="text-sm text-gray-600 hover:text-gray-900"
      >
        登录/注册
      </button>
    )
  }

  return (
    <div className="flex items-center gap-3">
      {/* 额度徽章 —— 额度迁移期间暂不展示（恢复：删 false &&） */}
      {false && (
        <Link
          to="/pricing"
          className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-blue-50 text-blue-600 text-xs font-bold hover:bg-blue-100 transition-colors"
          title="查看套餐 / 购买额度"
        >
          <Zap className="w-3 h-3" />
          {user?.credits ?? 0} 额度
        </Link>
      )}

      {/* 用户名 → 账户页 */}
      <Link
        to="/account"
        className="text-sm text-gray-700 hover:text-gray-900 hover:underline"
      >
        {user?.username || user?.email}
      </Link>

      <button
        className="text-sm text-gray-500 hover:text-gray-900"
        onClick={logout}
      >
        退出
      </button>
    </div>
  )
}
