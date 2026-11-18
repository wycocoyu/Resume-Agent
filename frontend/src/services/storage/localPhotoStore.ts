const DB_NAME = 'cococv_local_assets'
const DB_VERSION = 1
const STORE_NAME = 'portrait_photos'
export const MAX_PORTRAIT_PHOTO_BYTES = 2 * 1024 * 1024
const COMPRESS_TARGET_BYTES = 512 * 1024
const MAX_PORTRAIT_DIMENSION = 1200

const ALLOWED_IMAGE_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const ALLOWED_IMAGE_EXT_RE = /\.(png|jpe?g|webp)$/i

const memoryFallbackStore = new Map<string, string>()

function hasIndexedDB(): boolean {
  try {
    return typeof indexedDB !== 'undefined' && indexedDB !== null
  } catch {
    return false
  }
}

function openAssetsDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Failed to open IndexedDB'))
  })
}

async function withStore<T>(
  mode: IDBTransactionMode,
  runIdb: (store: IDBObjectStore) => IDBRequest<T>,
  runMemory: () => T,
): Promise<T> {
  if (!hasIndexedDB()) {
    return runMemory()
  }

  let db: IDBDatabase
  try {
    db = await openAssetsDB()
  } catch {
    return runMemory()
  }

  return new Promise<T>((resolve, reject) => {
    try {
      const tx = db.transaction(STORE_NAME, mode)
      const store = tx.objectStore(STORE_NAME)
      const req = runIdb(store)
      let settled = false
      let resultValue: T

      req.onsuccess = () => {
        resultValue = req.result
      }
      req.onerror = () => {
        if (!settled) {
          settled = true
          reject(req.error || new Error('IndexedDB request failed'))
        }
      }
      tx.oncomplete = () => {
        db.close()
        if (!settled) {
          settled = true
          resolve(resultValue)
        }
      }
      tx.onerror = () => {
        db.close()
        if (!settled) {
          settled = true
          reject(tx.error || new Error('IndexedDB transaction failed'))
        }
      }
      tx.onabort = () => {
        db.close()
        if (!settled) {
          settled = true
          reject(tx.error || new Error('IndexedDB transaction aborted'))
        }
      }
    } catch (err) {
      db.close()
      reject(err)
    }
  })
}

export async function saveLocalPortraitPhoto(resumeId: string, dataUrl: string): Promise<void> {
  if (!resumeId) return
  if (!dataUrl) {
    await deleteLocalPortraitPhoto(resumeId)
    return
  }
  await withStore(
    'readwrite',
    (store) => store.put(dataUrl, resumeId),
    () => {
      memoryFallbackStore.set(resumeId, dataUrl)
      return resumeId
    },
  )
}

export async function getLocalPortraitPhoto(resumeId: string): Promise<string | null> {
  if (!resumeId) return null
  const value = await withStore<string | undefined>(
    'readonly',
    (store) => store.get(resumeId) as IDBRequest<string | undefined>,
    () => memoryFallbackStore.get(resumeId),
  )
  return typeof value === 'string' && value.length > 0 ? value : null
}

export async function deleteLocalPortraitPhoto(resumeId: string): Promise<void> {
  if (!resumeId) return
  await withStore(
    'readwrite',
    (store) => store.delete(resumeId),
    () => {
      memoryFallbackStore.delete(resumeId)
      return undefined
    },
  )
}

export async function duplicateLocalPortraitPhoto(
  sourceResumeId: string,
  targetResumeId: string,
): Promise<void> {
  if (!sourceResumeId || !targetResumeId || sourceResumeId === targetResumeId) return
  const photo = await getLocalPortraitPhoto(sourceResumeId)
  if (photo) {
    await saveLocalPortraitPhoto(targetResumeId, photo)
  }
}

export async function clearLocalPortraitPhotos(): Promise<void> {
  await withStore(
    'readwrite',
    (store) => store.clear(),
    () => {
      memoryFallbackStore.clear()
      return undefined
    },
  )
}

export const localPhotoStore = {
  get: getLocalPortraitPhoto,
  set: saveLocalPortraitPhoto,
  delete: deleteLocalPortraitPhoto,
  duplicate: duplicateLocalPortraitPhoto,
  clear: clearLocalPortraitPhotos,
}

export function estimateDataUrlDecodedBytes(dataUrl: string): number {
  const marker = ';base64,'
  const idx = dataUrl.indexOf(marker)
  if (idx < 0) return dataUrl.length
  const base64 = dataUrl.slice(idx + marker.length).trim()
  if (!base64) return 0
  let padding = 0
  if (base64.endsWith('==')) padding = 2
  else if (base64.endsWith('=')) padding = 1
  return Math.max(0, Math.floor((base64.length * 3) / 4) - padding)
}

function inferImageMimeFromName(name: string): string | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.png')) return 'image/png'
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg'
  if (lower.endsWith('.webp')) return 'image/webp'
  return null
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (typeof FileReader === 'undefined') {
      reject(new Error('当前浏览器不支持读取本地图片'))
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
      } else {
        reject(new Error('读取图片数据失败'))
      }
    }
    reader.onerror = () => reject(reader.error || new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

function normalizeImageDataUrl(dataUrl: string, file: File): string {
  if (dataUrl.startsWith('data:image/') && dataUrl.includes(';base64,')) {
    return dataUrl
  }
  const mime = ALLOWED_IMAGE_MIME_TYPES.has(file.type.toLowerCase())
    ? file.type.toLowerCase()
    : inferImageMimeFromName(file.name || '')
  const markerIdx = dataUrl.indexOf(';base64,')
  if (mime && markerIdx >= 0) {
    return `data:${mime}${dataUrl.slice(markerIdx)}`
  }
  return dataUrl
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片解码失败'))
    img.src = src
  })
}

function get2DCanvas(): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } | null {
  if (typeof document === 'undefined') return null
  try {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    return { canvas, ctx }
  } catch {
    return null
  }
}

export async function readAndCompressPortraitPhoto(file: File): Promise<string> {
  const mime = (file.type || '').toLowerCase()
  if (mime) {
    if (!ALLOWED_IMAGE_MIME_TYPES.has(mime)) {
      throw new Error('仅支持 PNG、JPG、WEBP 格式图片')
    }
  } else if (!ALLOWED_IMAGE_EXT_RE.test(file.name || '')) {
    throw new Error('仅支持 PNG、JPG、WEBP 格式图片')
  }

  const rawDataUrl = normalizeImageDataUrl(await readFileAsDataUrl(file), file)
  const rawBytes = estimateDataUrlDecodedBytes(rawDataUrl)
  const effectiveMime =
    mime || inferImageMimeFromName(file.name || '') || ''
  const mustTranscodeWebp = effectiveMime === 'image/webp'

  const canvasContext =
    (mustTranscodeWebp || rawBytes > COMPRESS_TARGET_BYTES) && typeof Image !== 'undefined'
      ? get2DCanvas()
      : null

  if (!canvasContext) {
    if (rawBytes > MAX_PORTRAIT_PHOTO_BYTES || file.size > MAX_PORTRAIT_PHOTO_BYTES) {
      throw new Error('图片过大，最大支持 2MB')
    }
    return rawDataUrl
  }

  try {
    const img = await loadImageElement(rawDataUrl)
    const srcWidth = img.naturalWidth || img.width
    const srcHeight = img.naturalHeight || img.height
    if (!srcWidth || !srcHeight) {
      if (!mustTranscodeWebp && rawBytes <= MAX_PORTRAIT_PHOTO_BYTES) return rawDataUrl
      throw new Error('图片过大，最大支持 2MB')
    }

    if (
      !mustTranscodeWebp &&
      srcWidth <= MAX_PORTRAIT_DIMENSION &&
      srcHeight <= MAX_PORTRAIT_DIMENSION &&
      rawBytes <= COMPRESS_TARGET_BYTES
    ) {
      return rawDataUrl
    }

    const { canvas, ctx } = canvasContext
    let scale = Math.min(1, MAX_PORTRAIT_DIMENSION / Math.max(srcWidth, srcHeight))
    const qualities = [0.86, 0.72, 0.58, 0.44]

    for (let round = 0; round < 3; round++) {
      canvas.width = Math.max(1, Math.round(srcWidth * scale))
      canvas.height = Math.max(1, Math.round(srcHeight * scale))
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

      if (mustTranscodeWebp && round === 0 && rawBytes <= COMPRESS_TARGET_BYTES) {
        const pngCandidate = canvas.toDataURL('image/png')
        if (
          pngCandidate.startsWith('data:image/png;base64,') &&
          estimateDataUrlDecodedBytes(pngCandidate) <= MAX_PORTRAIT_PHOTO_BYTES
        ) {
          return pngCandidate
        }
      }

      for (const quality of qualities) {
        const candidate = canvas.toDataURL('image/jpeg', quality)
        if (
          candidate.startsWith('data:image/') &&
          candidate.includes(';base64,') &&
          estimateDataUrlDecodedBytes(candidate) <= MAX_PORTRAIT_PHOTO_BYTES
        ) {
          return candidate
        }
      }
      scale *= 0.7
    }
  } catch (err) {
    if (rawBytes <= MAX_PORTRAIT_PHOTO_BYTES) {
      return rawDataUrl
    }
    if (err instanceof Error && err.message === '图片过大，最大支持 2MB') {
      throw err
    }
  }

  if (rawBytes <= MAX_PORTRAIT_PHOTO_BYTES) {
    return rawDataUrl
  }
  throw new Error('图片过大，最大支持 2MB')
}
