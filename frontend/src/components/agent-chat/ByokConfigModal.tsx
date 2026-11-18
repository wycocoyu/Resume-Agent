import { useEffect, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Eye, EyeOff, KeyRound, ShieldCheck, Trash2, X } from 'lucide-react'
import {
  BYOK_PROVIDER_LIST,
  BYOK_PROVIDER_PRESETS,
  clearByokConfig,
  getDefaultByokConfig,
  loadByokConfig,
  saveByokConfig,
  type ByokConfig,
  type ByokProviderId,
} from '@/services/agentByokConfig'

export const BYOK_PRIVACY_NOTICE =
  'API Key 仅保存在当前浏览器的本地存储（localStorage）中，仅在发起对话时直接透传模型请求，服务器不会落盘或保留您的密钥。'

export interface ByokConfigModalProps {
  open: boolean
  onClose: () => void
  onConfigChange?: (config: ByokConfig) => void
}

function isValidHttpUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:'
  } catch {
    return false
  }
}

export default function ByokConfigModal({
  open,
  onClose,
  onConfigChange,
}: ByokConfigModalProps) {
  const [enabled, setEnabled] = useState(true)
  const [provider, setProvider] = useState<ByokProviderId>('deepseek')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(BYOK_PROVIDER_PRESETS.deepseek.baseUrl)
  const [model, setModel] = useState(BYOK_PROVIDER_PRESETS.deepseek.model)
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const saved = loadByokConfig()
    setProvider(saved.provider)
    setApiKey(saved.apiKey)
    setBaseUrl(saved.baseUrl)
    setModel(saved.model)
    // 首次尚未填密钥时默认勾选启用，填好保存即可生效；已有密钥则尊重上次开关态
    setEnabled(saved.apiKey.trim() ? saved.enabled : true)
    setShowKey(false)
    setError(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open) return null

  const preset = BYOK_PROVIDER_PRESETS[provider] ?? BYOK_PROVIDER_PRESETS.deepseek

  const handleProviderChange = (nextProvider: ByokProviderId) => {
    const nextPreset = BYOK_PROVIDER_PRESETS[nextProvider]
    setProvider(nextProvider)
    setBaseUrl(nextPreset.baseUrl)
    setModel(nextPreset.model)
    setError(null)
  }

  const handleSave = (event: FormEvent) => {
    event.preventDefault()
    const trimmedKey = apiKey.trim()
    const trimmedUrl = baseUrl.trim()
    const trimmedModel = model.trim()

    if (enabled) {
      if (!trimmedKey) {
        setError('请填写 API Key，或先关闭「启用自带 API Key」开关。')
        return
      }
      if (!trimmedUrl || !isValidHttpUrl(trimmedUrl)) {
        setError('请填写有效的服务 Base URL（例如 https://api.deepseek.com）。')
        return
      }
      if (!trimmedModel) {
        setError('请填写模型 ID。')
        return
      }
    }

    const saved = saveByokConfig({
      enabled,
      provider,
      apiKey: trimmedKey,
      baseUrl: trimmedUrl,
      model: trimmedModel,
    })
    onConfigChange?.(saved)
    onClose()
  }

  const handleClear = () => {
    clearByokConfig()
    const reset = getDefaultByokConfig('deepseek')
    onConfigChange?.(reset)
    onClose()
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="byok-modal-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-none border-2 border-black bg-white p-6 shadow-[6px_6px_0px_0px_#000000] fresh:rounded-2xl fresh:border fresh:border-slate-200 fresh:shadow-2xl dark:border-white dark:bg-slate-900 dark:shadow-[6px_6px_0px_0px_#ffffff]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-none border border-black bg-blue-50 text-[#3367D6] fresh:rounded-xl fresh:border-blue-100 dark:border-slate-700 dark:bg-blue-950/50 dark:text-blue-400">
              <KeyRound className="h-4 w-4" />
            </span>
            <div>
              <h2
                id="byok-modal-title"
                className="text-base font-bold text-slate-900 dark:text-slate-100"
              >
                自带 API Key
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                使用你自己的大模型接口，不消耗站点免费体验额度
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭弹窗"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSave} className="mt-5 space-y-4">
          {/* 启用开关 */}
          <div className="flex items-center justify-between rounded-none border border-black bg-slate-50 px-3.5 py-2.5 fresh:rounded-xl fresh:border-slate-200 dark:border-slate-700 dark:bg-slate-800/60">
            <div>
              <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
                启用自带 API Key
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                开启后 AI 助手请求将直连下方配置的模型服务
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="启用自带 API Key"
              onClick={() => {
                setEnabled((prev) => !prev)
                setError(null)
              }}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border transition-colors ${
                enabled
                  ? 'border-[#3367D6] bg-[#4285F4]'
                  : 'border-slate-300 bg-slate-200 dark:border-slate-600 dark:bg-slate-700'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* 服务商预设 */}
          <div>
            <label
              htmlFor="byok-provider"
              className="mb-1.5 block text-xs font-semibold text-slate-700 dark:text-slate-300"
            >
              模型服务商
            </label>
            <select
              id="byok-provider"
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value as ByokProviderId)}
              className="w-full rounded-none border border-black bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-[#4285F4] fresh:rounded-lg fresh:border-slate-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            >
              {BYOK_PROVIDER_LIST.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            {preset.hint && (
              <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                {preset.hint}
              </p>
            )}
          </div>

          {/* API Key */}
          <div>
            <label
              htmlFor="byok-api-key"
              className="mb-1.5 block text-xs font-semibold text-slate-700 dark:text-slate-300"
            >
              API Key
            </label>
            <div className="relative">
              <input
                id="byok-api-key"
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value)
                  setError(null)
                }}
                placeholder="sk-..."
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-none border border-black bg-white py-2 pl-3 pr-10 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-[#4285F4] fresh:rounded-lg fresh:border-slate-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
              <button
                type="button"
                onClick={() => setShowKey((prev) => !prev)}
                aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Base URL + Model */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="byok-base-url"
                className="mb-1.5 block text-xs font-semibold text-slate-700 dark:text-slate-300"
              >
                Base URL
              </label>
              <input
                id="byok-base-url"
                type="url"
                value={baseUrl}
                onChange={(e) => {
                  setBaseUrl(e.target.value)
                  setError(null)
                }}
                placeholder="https://api.deepseek.com"
                spellCheck={false}
                className="w-full rounded-none border border-black bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-[#4285F4] fresh:rounded-lg fresh:border-slate-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>

            <div>
              <label
                htmlFor="byok-model"
                className="mb-1.5 block text-xs font-semibold text-slate-700 dark:text-slate-300"
              >
                模型 ID
              </label>
              <input
                id="byok-model"
                type="text"
                value={model}
                onChange={(e) => {
                  setModel(e.target.value)
                  setError(null)
                }}
                placeholder={preset.modelPlaceholder || '例如 deepseek-chat'}
                spellCheck={false}
                className="w-full rounded-none border border-black bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-[#4285F4] fresh:rounded-lg fresh:border-slate-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
          </div>

          {/* 隐私说明 */}
          <div className="flex items-start gap-2 rounded-none border border-blue-200 bg-blue-50/70 px-3 py-2.5 text-xs leading-relaxed text-blue-900 fresh:rounded-xl dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-200">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#3367D6] dark:text-blue-400" />
            <span>{BYOK_PRIVACY_NOTICE}</span>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-none border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 fresh:rounded-lg dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
            >
              {error}
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
            <button
              type="button"
              onClick={handleClear}
              className="inline-flex items-center gap-1.5 rounded-none border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 fresh:rounded-lg dark:border-slate-700 dark:bg-slate-800 dark:text-red-400 dark:hover:bg-red-950/40"
            >
              <Trash2 className="h-3.5 w-3.5" />
              清除密钥
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-none border border-black bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-100 fresh:rounded-lg fresh:border-slate-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                取消
              </button>
              <button
                type="submit"
                className="rounded-none border border-black bg-[#4285F4] px-4 py-2 text-xs font-semibold text-white shadow-[2px_2px_0px_0px_#000000] transition-all hover:bg-[#3367D6] fresh:rounded-lg fresh:border-transparent fresh:shadow-sm"
              >
                保存配置
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}
