// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearLocalPortraitPhotos,
  deleteLocalPortraitPhoto,
  duplicateLocalPortraitPhoto,
  getLocalPortraitPhoto,
  readAndCompressPortraitPhoto,
  saveLocalPortraitPhoto,
} from './localPhotoStore'
import { LocalStorageAdapter } from './LocalStorageAdapter'

const SAMPLE_PNG_DATA_URL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

describe('localPhotoStore & LocalStorageAdapter portrait photo isolation', () => {
  beforeEach(async () => {
    localStorage.clear()
    await clearLocalPortraitPhotos()
  })

  afterEach(async () => {
    localStorage.clear()
    await clearLocalPortraitPhotos()
    vi.restoreAllMocks()
  })

  it('falls back to in-memory store when indexedDB is undefined and supports CRUD + duplicate', async () => {
    expect(typeof indexedDB).toBe('undefined')

    await saveLocalPortraitPhoto('r1', SAMPLE_PNG_DATA_URL)
    expect(await getLocalPortraitPhoto('r1')).toBe(SAMPLE_PNG_DATA_URL)

    await duplicateLocalPortraitPhoto('r1', 'r2')
    expect(await getLocalPortraitPhoto('r2')).toBe(SAMPLE_PNG_DATA_URL)

    await deleteLocalPortraitPhoto('r1')
    expect(await getLocalPortraitPhoto('r1')).toBeNull()
    expect(await getLocalPortraitPhoto('r2')).toBe(SAMPLE_PNG_DATA_URL)
  })

  it('keeps localStorage stripped while hydrating basic.photo via localPhotoStore', async () => {
    const adapter = new LocalStorageAdapter()
    const saved = await adapter.saveResume(
      {
        basic: {
          name: '张三',
          title: '前端工程师',
          email: 'a@b.com',
          phone: '13800138000',
          location: '杭州',
          photo: SAMPLE_PNG_DATA_URL,
        },
        education: [],
        experience: [],
        projects: [],
        openSource: [],
        awards: [],
        selfEvaluation: '',
        skillContent: '',
        menuSections: [],
        globalSettings: {},
      } as any,
      'resume_photo_1',
    )

    expect((saved.data as any).basic.photo).toBe(SAMPLE_PNG_DATA_URL)

    // localStorage JSON must NOT contain the base64 portrait photo
    const rawJson = localStorage.getItem('resume_resumes') || ''
    expect(rawJson).not.toContain('data:image/png;base64')
    const parsedRaw = JSON.parse(rawJson)
    expect(parsedRaw[0].data.basic.photo).toBeUndefined()

    // getResume & getAllResumes hydrate basic.photo back from localPhotoStore
    const fetched = await adapter.getResume('resume_photo_1')
    expect((fetched?.data as any).basic.photo).toBe(SAMPLE_PNG_DATA_URL)

    const all = await adapter.getAllResumes()
    expect(all).toHaveLength(1)
    expect((all[0].data as any).basic.photo).toBe(SAMPLE_PNG_DATA_URL)

    // duplicateResume copies photo to the duplicated resume
    const duplicated = await adapter.duplicateResume('resume_photo_1')
    expect(duplicated).not.toBeNull()
    expect((duplicated!.data as any).basic.photo).toBe(SAMPLE_PNG_DATA_URL)

    // Clearing photo on save removes it from localPhotoStore without touching duplicate
    await adapter.saveResume(
      {
        ...(fetched!.data as any),
        basic: { ...(fetched!.data as any).basic, photo: '' },
      },
      'resume_photo_1',
    )
    const afterClear = await adapter.getResume('resume_photo_1')
    expect((afterClear?.data as any).basic.photo).toBeUndefined()
    const duplicatedFetched = await adapter.getResume(duplicated!.id)
    expect((duplicatedFetched?.data as any).basic.photo).toBe(SAMPLE_PNG_DATA_URL)

    // deleteResume deletes photo from localPhotoStore
    await adapter.deleteResume(duplicated!.id)
    expect(await getLocalPortraitPhoto(duplicated!.id)).toBeNull()
  })

  it('readAndCompressPortraitPhoto accepts valid PNG/JPEG/WEBP and rejects invalid or oversized files without canvas', async () => {
    const validFile = new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], 'avatar.png', {
      type: 'image/png',
    })
    const dataUrl = await readAndCompressPortraitPhoto(validFile)
    expect(dataUrl).toMatch(/^data:image\/png;base64,/)

    const badTypeFile = new File(['hello'], 'resume.pdf', { type: 'application/pdf' })
    await expect(readAndCompressPortraitPhoto(badTypeFile)).rejects.toThrow('仅支持 PNG、JPG、WEBP 格式图片')

    const oversized = new File([new Uint8Array(2 * 1024 * 1024 + 64)], 'huge.jpg', {
      type: 'image/jpeg',
    })
    await expect(readAndCompressPortraitPhoto(oversized)).rejects.toThrow('图片过大，最大支持 2MB')
  })

  it('readAndCompressPortraitPhoto compresses oversized images when canvas & Image are available', async () => {
    const bigBytes = new Uint8Array(2 * 1024 * 1024 + 256)
    const hugeJpeg = new File([bigBytes], 'big.jpg', { type: 'image/jpeg' })

    const fakeCtx = {
      clearRect: vi.fn(),
      drawImage: vi.fn(),
    }
    const fakeCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => fakeCtx),
      toDataURL: vi.fn(() => 'data:image/jpeg;base64,/9j/4AAQSkZJRg=='),
    }
    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') return fakeCanvas as unknown as HTMLCanvasElement
      return origCreateElement(tagName)
    })

    class MockImage {
      naturalWidth = 2400
      naturalHeight = 2400
      width = 2400
      height = 2400
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      set src(_val: string) {
        queueMicrotask(() => this.onload?.())
      }
    }
    vi.stubGlobal('Image', MockImage)

    const compressed = await readAndCompressPortraitPhoto(hugeJpeg)
    expect(compressed).toBe('data:image/jpeg;base64,/9j/4AAQSkZJRg==')
    expect(fakeCanvas.width).toBe(1200)
    expect(fakeCanvas.height).toBe(1200)
    expect(fakeCtx.drawImage).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
