import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { X, FlaskConical } from 'lucide-react'

const SEEN_KEY = 'seen_beta_notice'

/**
 * Beta 提示弹窗：用户首次访问时弹一次，说明当前为测试版。
 * 点「了解」后在 localStorage 记下标识，不再重复弹出。
 */
export function BetaNoticeModal() {
  const location = useLocation()
  const inWorkspace = location.pathname.startsWith('/workspace')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (inWorkspace) return
    try {
      const seen = localStorage.getItem(SEEN_KEY)
      if (!seen) setOpen(true)
    } catch {
      /* localStorage 不可用时静默跳过 */
    }
  }, [inWorkspace])

  const dismiss = () => {
    try {
      localStorage.setItem(SEEN_KEY, '1')
    } catch {
      /* ignore */
    }
    setOpen(false)
  }

  if (inWorkspace) return null

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm"
          onClick={dismiss}
        >
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.96 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="w-full max-w-md overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="relative px-6 pt-6 pb-4">
              <button
                type="button"
                onClick={dismiss}
                aria-label="关闭"
                className="absolute right-4 top-4 rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
              >
                <X className="h-4 w-4" />
              </button>
              <div className="flex items-center gap-3">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500 to-amber-400 text-white shadow-lg shadow-amber-500/30">
                  <FlaskConical className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-lg font-black text-slate-900 dark:text-slate-100">当前为 Beta 测试版</h2>
                  <p className="text-xs font-medium text-slate-400">感谢你愿意陪它一起成长</p>
                </div>
              </div>
            </div>

            <div className="space-y-3 px-6 pb-2">
              <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                CocoCV 目前仍在积极打磨中、部分功能（例如 PDF 上传解析）可能较慢、偶尔也会有小瑕疵。
              </p>
              <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                当前（Beta 测试版）期间、下载 PDF、渲染 PDF 和 AI 功能都是免费的、放心使用。
              </p>
              <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                如果遇到问题或有建议、欢迎随时反馈、我会持续优化 ✨
              </p>
            </div>

            <div className="px-6 py-4">
              <button
                type="button"
                onClick={dismiss}
                className="w-full rounded-xl bg-amber-500 py-2.5 text-sm font-bold text-white transition-colors hover:bg-amber-600 active:scale-[0.99]"
              >
                了解
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
