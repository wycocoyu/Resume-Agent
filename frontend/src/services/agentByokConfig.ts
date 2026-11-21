import { getAuthHeaders } from '@/lib/authHeaders'
import { getOrCreateAnonAgentToken } from '@/services/agentLocalHistory'

export const BYOK_STORAGE_KEY = 'cococv_agent_byok_v1'
export const BYOK_UPDATED_EVENT = 'cococv:agent-byok-updated'

export type ByokProviderId =
  | 'deepseek'
  | 'openai'
  | 'openrouter'
  | 'siliconflow'
  | 'moonshot'
  | 'doubao'
  | 'zhipu'
  | 'custom'

export interface ByokProviderPreset {
  id: ByokProviderId
  label: string
  baseUrl: string
  model: string
  modelPlaceholder?: string
  hint?: string
}

export interface ByokConfig {
  enabled: boolean
  provider: ByokProviderId
  apiKey: string
  baseUrl: string
  model: string
}

export const BYOK_PROVIDER_PRESETS: Record<ByokProviderId, ByokProviderPreset> = {
  deepseek: {
    id: 'deepseek',
    label: 'DeepSeek 官方',
    baseUrl: 'https://api.deepseek.com',
    model: 'deepseek-chat',
    hint: '常用模型：deepseek-chat / deepseek-reasoner',
  },
  openai: {
    id: 'openai',
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    hint: '常用模型：gpt-4o-mini / gpt-4o',
  },
  openrouter: {
    id: 'openrouter',
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    model: 'deepseek/deepseek-chat',
    hint: '支持聚合多家模型，按 OpenRouter 模型 ID 填写',
  },
  siliconflow: {
    id: 'siliconflow',
    label: '硅基流动 SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    model: 'deepseek-ai/DeepSeek-V3',
    hint: '国内低延迟节点，按硅基流动模型 ID 填写',
  },
  moonshot: {
    id: 'moonshot',
    label: '月之暗面 Moonshot (Kimi)',
    baseUrl: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-32k',
    hint: '常用模型：moonshot-v1-32k / kimi-k2-0711-preview',
  },
  doubao: {
    id: 'doubao',
    label: '火山方舟 豆包',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    model: '',
    modelPlaceholder: '填写推理接入点 ID（如 ep-xxxxxxxx）',
    hint: '请在火山方舟控制台创建推理接入点后填入 Endpoint ID',
  },
  zhipu: {
    id: 'zhipu',
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4-flash',
    hint: '常用模型：glm-4-flash / glm-4-plus',
  },
  custom: {
    id: 'custom',
    label: '自定义 (OpenAI 兼容)',
    baseUrl: '',
    model: '',
    modelPlaceholder: '例如 gpt-4o / qwen-max',
    hint: '仅支持公网 HTTPS OpenAI 兼容接口地址',
  },
}

export const BYOK_PROVIDER_LIST: ByokProviderPreset[] = Object.values(BYOK_PROVIDER_PRESETS)

function isByokProviderId(value: unknown): value is ByokProviderId {
  return typeof value === 'string' && value in BYOK_PROVIDER_PRESETS
}

export function getDefaultByokConfig(provider: ByokProviderId = 'deepseek'): ByokConfig {
  const preset = BYOK_PROVIDER_PRESETS[provider] ?? BYOK_PROVIDER_PRESETS.deepseek
  return {
    enabled: false,
    provider: preset.id,
    apiKey: '',
    baseUrl: preset.baseUrl,
    model: preset.model,
  }
}

function dispatchByokUpdated(): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(BYOK_UPDATED_EVENT))
  } catch {
    // ignore event errors
  }
}

export function loadByokConfig(): ByokConfig {
  const defaults = getDefaultByokConfig('deepseek')
  try {
    const raw = localStorage.getItem(BYOK_STORAGE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<ByokConfig> | null
    if (!parsed || typeof parsed !== 'object') return defaults

    const provider: ByokProviderId = isByokProviderId(parsed.provider) ? parsed.provider : 'deepseek'
    const preset = BYOK_PROVIDER_PRESETS[provider]
    return {
      enabled: Boolean(parsed.enabled),
      provider,
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : preset.baseUrl,
      model: typeof parsed.model === 'string' ? parsed.model : preset.model,
    }
  } catch {
    return defaults
  }
}

export function saveByokConfig(config: Partial<ByokConfig>): ByokConfig {
  const current = loadByokConfig()
  const provider: ByokProviderId = isByokProviderId(config.provider)
    ? config.provider
    : current.provider
  const preset = BYOK_PROVIDER_PRESETS[provider]
  const next: ByokConfig = {
    enabled: config.enabled ?? current.enabled,
    provider,
    apiKey: (config.apiKey ?? current.apiKey).trim(),
    baseUrl: (config.baseUrl ?? preset.baseUrl).trim(),
    model: (config.model ?? preset.model).trim(),
  }

  try {
    localStorage.setItem(BYOK_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // ignore storage errors
  }
  dispatchByokUpdated()
  return next
}

export function clearByokConfig(): void {
  try {
    localStorage.removeItem(BYOK_STORAGE_KEY)
  } catch {
    // ignore
  }
  dispatchByokUpdated()
}

export function isByokActive(config: ByokConfig = loadByokConfig()): boolean {
  return Boolean(config.enabled && config.apiKey.trim())
}

export function getAgentRequestHeaders(
  extra: Record<string, string> = {},
): Record<string, string> {
  const headers: Record<string, string> = {
    ...getAuthHeaders(),
    'X-Anon-Session-Token': getOrCreateAnonAgentToken(),
  }

  const byok = loadByokConfig()
  if (isByokActive(byok)) {
    const preset = BYOK_PROVIDER_PRESETS[byok.provider] ?? BYOK_PROVIDER_PRESETS.deepseek
    headers['X-AI-Provider'] = byok.provider
    headers['X-AI-Api-Key'] = byok.apiKey.trim()
    headers['X-AI-Base-Url'] = (byok.baseUrl || preset.baseUrl).trim()
    headers['X-AI-Model'] = (byok.model || preset.model).trim()
  }

  return {
    ...headers,
    ...extra,
  }
}
