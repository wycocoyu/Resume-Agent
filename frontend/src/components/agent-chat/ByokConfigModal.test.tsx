// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ByokConfigModal, { BYOK_PRIVACY_NOTICE } from './ByokConfigModal'
import {
  isByokActive,
  loadByokConfig,
  saveByokConfig,
} from '@/services/agentByokConfig'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function setInputValue(input: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto =
    input instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  setter?.call(input, value)
  input.dispatchEvent(new Event('change', { bubbles: true }))
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('ByokConfigModal', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => {
      root.unmount()
    })
    container.remove()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('auto-fills preset baseUrl and model, displays privacy notice, saves and clears config', async () => {
    const onClose = vi.fn()
    const onConfigChange = vi.fn()

    await act(async () => {
      root.render(
        <ByokConfigModal open={true} onClose={onClose} onConfigChange={onConfigChange} />,
      )
    })

    expect(document.body.textContent).toContain(BYOK_PRIVACY_NOTICE)

    const select = document.getElementById('byok-provider') as HTMLSelectElement
    const keyInput = document.getElementById('byok-api-key') as HTMLInputElement
    const baseUrlInput = document.getElementById('byok-base-url') as HTMLInputElement
    const modelInput = document.getElementById('byok-model') as HTMLInputElement

    await act(async () => {
      setInputValue(select, 'siliconflow')
    })

    expect(baseUrlInput.value).toBe('https://api.siliconflow.cn/v1')
    expect(modelInput.value).toBe('deepseek-ai/DeepSeek-V3')

    // Toggle key visibility
    const toggleEye = document.querySelector('button[aria-label="显示 API Key"]') as HTMLButtonElement
    expect(keyInput.type).toBe('password')
    await act(async () => {
      toggleEye.click()
    })
    expect(keyInput.type).toBe('text')

    await act(async () => {
      setInputValue(keyInput, 'sk-sf-123456')
    })

    const saveBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === '保存配置',
    ) as HTMLButtonElement
    await act(async () => {
      saveBtn.click()
    })

    expect(onConfigChange).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        provider: 'siliconflow',
        apiKey: 'sk-sf-123456',
      }),
    )
    expect(isByokActive()).toBe(true)
    expect(onClose).toHaveBeenCalledTimes(1)

    // Re-open and clear
    await act(async () => {
      root.render(
        <ByokConfigModal open={true} onClose={onClose} onConfigChange={onConfigChange} />,
      )
    })
    const clearBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('清除密钥'),
    ) as HTMLButtonElement
    await act(async () => {
      clearBtn.click()
    })
    expect(isByokActive()).toBe(false)
    expect(loadByokConfig().apiKey).toBe('')
  })

  it('validates missing key when enabled and allows saving disabled key without losing it', async () => {
    saveByokConfig({
      enabled: false,
      provider: 'openai',
      apiKey: 'sk-saved-key',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
    })
    const onClose = vi.fn()

    await act(async () => {
      root.render(<ByokConfigModal open={true} onClose={onClose} />)
    })

    const switchBtn = document.querySelector('button[role="switch"]') as HTMLButtonElement
    expect(switchBtn.getAttribute('aria-checked')).toBe('false')

    // Enable and clear key input -> validation alert
    await act(async () => {
      switchBtn.click()
    })
    const keyInput = document.getElementById('byok-api-key') as HTMLInputElement
    await act(async () => {
      setInputValue(keyInput, '')
    })
    const saveBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === '保存配置',
    ) as HTMLButtonElement
    await act(async () => {
      saveBtn.click()
    })
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('API Key')
    expect(onClose).not.toHaveBeenCalled()
  })
})
