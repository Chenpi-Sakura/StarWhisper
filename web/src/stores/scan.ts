import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { isAbortError, isTimeoutError, solveImage } from '../api/solve'
import { readExifMeta, type ExifMeta } from '../utils/exif'
import { buildCapture, type PhotoCapture } from '../utils/capture'
import { loadCityIndex } from '../utils/cityTrie'
import { useToastStore } from './toast'
import type { SolveResult, StoryStyle } from '../types'

export type ScanStatus =
  | 'idle'
  | 'ready'
  | 'uploading'
  | 'done'
  | 'empty'
  | 'error'

const MAX_SIZE = 20 * 1024 * 1024
const ALLOWED_TYPES = ['image/jpeg', 'image/png'] as const

/** 简单 UUID v4——避免引入 crypto.randomUUID（jsdom 中不可用）。
 *  每次 solve 成功生成新 id，写入 solveId 触发 StoryPanel watcher。 */
function _uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export const useScanStore = defineStore('scan', () => {
  const status = ref<ScanStatus>('idle')
  const imageFile = ref<File | null>(null)
  const previewUrl = ref<string | null>(null)
  const result = ref<SolveResult | null>(null)
  const activeAbbr = ref<string | null>(null)
  const errorCode = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  const selectedStyle = ref<StoryStyle>('myth')
  /** 前端展示过滤用的 tradition：'western' / 'chinese' / ''（不限）。
   *  不再传给后端——后端永远按"不限"全 tradition 反查，前端按此值过滤
   *  constellation 列表。理由：astrometry 与 tradition 无关，切 tradition
   *  不应触发 20s 重解。 */
  const lockedTradition = ref<string>('')
  /** photo-level 故事触发键——每次 solve 成功生成新 uuid，StoryPanel watch 它触发 fetchPhotoStory。
   *  切 chip / 切 style 都不刷新此键，故不触发新故事。 */
  const solveId = ref<string | null>(null)
  /** EXIF 摘要（拍摄时刻 + 区县级地名），随故事 context 一起发给后端。
   *  原始经纬度在 buildCapture 里就被换成地名了，这个对象不含坐标。 */
  const capture = ref<PhotoCapture>({})
  const loading = computed(() => status.value === 'uploading')

  let abortController: AbortController | null = null
  /** Distinguishes user-initiated cancellation (back to ready) from network aborts. */
  let cancelledByUser = false

  function setLockedTradition(t: string): void {
    lockedTradition.value = t
  }

  /** GPS → 区县级地名要拉城市表；任何失败都只降级成「没有地名」，绝不影响解算结果。 */
  async function resolveCapture(meta: ExifMeta): Promise<PhotoCapture> {
    const hasGps = meta.lat !== undefined && meta.lon !== undefined
    try {
      const rows = hasGps ? (await loadCityIndex()).rows : []
      return buildCapture(meta, rows)
    } catch {
      return buildCapture(meta, [])
    }
  }

  function selectImage(file: File): void {
    if (status.value === 'uploading') {
      // interrupt any in-flight solve; the catch branch will route back to ready
      // because the user just wanted to swap images, not cancel the whole flow.
      cancelledByUser = false
      abortController?.abort()
    }
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
    imageFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    status.value = 'ready'
    result.value = null
    activeAbbr.value = null
    errorCode.value = null
    errorMessage.value = null
    capture.value = {}
  }

  async function solve(mock = false): Promise<void> {
    if (!imageFile.value || status.value === 'uploading') return

    const toast = useToastStore()
    if (!ALLOWED_TYPES.includes(imageFile.value.type as typeof ALLOWED_TYPES[number])) {
      toast.show('仅支持 JPG、PNG 格式', 'error')
      return
    }
    if (imageFile.value.size > MAX_SIZE) {
      toast.show('图片超过 20MB 限制', 'error')
      return
    }

    status.value = 'uploading'
    cancelledByUser = false
    errorCode.value = null
    errorMessage.value = null
    abortController = new AbortController()

    // 公网上传 ≤ 4MB 约束（docs/API.md §1 关键约束 1）由服务端保障：
    // 服务端 PIL libjpeg 自适应重压 JPEG（默认 q90→q85→q80），PNG 透传。
    // 不在 web 端做压缩，因为：
    //   1. canvas Skia 与 mozjpeg-wasm 在像素细节上与 native libjpeg 有差异，
    //      相机长焦大图（test1 D610 MPO、test2 50MP）即便 EXIF 完整保留，
    //      astrometry.net source extractor 仍可能拒绝（实测 canvas 全失败）
    //   2. 服务端是 native libjpeg，与 astrometry.net 同源，最稳定
    // 详见 server/services/jpeg_recompress.py docstring。
    const uploadFile: File = imageFile.value

    try {
      const meta = await readExifMeta(uploadFile)
      const data = await solveImage(uploadFile, {
        mock,
        signal: abortController.signal,
        exifOrientation: meta.orientation,
      })
      result.value = data
      // 解算已返回，此处补 EXIF 摘要；必须在 solveId 之前就绪，故事才拿得到
      capture.value = await resolveCapture(meta)
      if (!data.ok || !data.solved) {
        status.value = 'error'
        errorCode.value = data.code ?? 'UNKNOWN'
        errorMessage.value = data.message ?? '识别失败'
      } else {
        const constellations = data.constellations ?? []
        status.value = constellations.length > 0 ? 'done' : 'empty'
        // 新 solveId 触发 StoryPanel watcher；旧 id 不复用（确保每次成功都是新触发）
        solveId.value = _uuid()
      }
    } catch (err: unknown) {
      if (cancelledByUser) {
        status.value = 'ready'
        return
      }
      if (isTimeoutError(err)) {
        status.value = 'error'
        errorCode.value = 'TIMEOUT'
        errorMessage.value = '解析超时'
      } else if (isAbortError(err)) {
        status.value = 'ready'
      } else {
        status.value = 'error'
        errorCode.value = 'FETCH_ERROR'
        errorMessage.value = '网络异常'
      }
    }
  }

  function cancel(): void {
    cancelledByUser = true
    abortController?.abort()
    // Keep preview/image intact — the user only meant to abort this attempt.
    status.value = 'ready'
  }

  function selectConstellation(abbr: string): void {
    activeAbbr.value = abbr
  }

  /** T8: toggle 行为 — 再点一次已 active 的 chip 回到全量（activeAbbr=null）。 */
  function toggleConstellation(abbr: string): void {
    activeAbbr.value = activeAbbr.value === abbr ? null : abbr
  }

  function setStyle(s: StoryStyle): void {
    selectedStyle.value = s
  }

  function reset(): void {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
    status.value = 'idle'
    imageFile.value = null
    previewUrl.value = null
    result.value = null
    activeAbbr.value = null
    errorCode.value = null
    errorMessage.value = null
    capture.value = {}
  }

  return {
    status,
    imageFile,
    previewUrl,
    result,
    activeAbbr,
    errorCode,
    errorMessage,
    selectedStyle,
    lockedTradition,
    solveId,
    capture,
    loading,
    selectImage,
    solve,
    cancel,
    selectConstellation,
    toggleConstellation,
    setStyle,
    setLockedTradition,
    reset,
  }
})