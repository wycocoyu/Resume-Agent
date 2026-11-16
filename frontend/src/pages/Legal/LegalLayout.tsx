import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { BetaBadge } from '@/components/BetaBadge'

type LegalLayoutProps = {
  title: string
  lastUpdated: string
  children: ReactNode
}

/** 法务页共享外壳：顶部返回首页、标题与更新日期、底部互链。 */
export function LegalLayout({ title, lastUpdated, children }: LegalLayoutProps) {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      <header className="border-b border-slate-200 dark:border-slate-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回首页
          </Link>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-gradient-to-br from-blue-600 to-blue-500 rounded-lg flex items-center justify-center shrink-0">
              <span className="text-white font-black text-[10px] italic">CV</span>
            </div>
            <span className="text-sm font-bold text-slate-700 dark:text-slate-300">CocoCV</span>
            <BetaBadge className="translate-y-[-5px]" />
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <h1 className="text-3xl font-black text-slate-900 dark:text-slate-100 mb-2">{title}</h1>
        <p className="text-sm text-slate-400 dark:text-slate-500 mb-10">最后更新：{lastUpdated}</p>
        <div className="space-y-8">{children}</div>
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800 px-6 py-8">
        <div className="max-w-3xl mx-auto flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
          <Link to="/terms" className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
            服务条款
          </Link>
          <Link to="/privacy" className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
            隐私政策
          </Link>
          <Link to="/refund" className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
            退款政策
          </Link>
        </div>
      </footer>
    </div>
  )
}

/** 法务页内的一节：小标题 + 正文。 */
export function LegalSection({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-3">{heading}</h2>
      <div className="space-y-3 text-[15px] leading-relaxed text-slate-600 dark:text-slate-300">
        {children}
      </div>
    </section>
  )
}

/** 法务页正文常用的无序列表。 */
export function LegalList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="list-disc pl-5 space-y-1.5 marker:text-slate-400">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

export const SUPPORT_EMAIL = '3658043236@qq.com'
