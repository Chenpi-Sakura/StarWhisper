/**
 * EXIF → 故事 prompt 用的「拍摄信息」摘要。
 *
 * 只输出两件东西：归一化后的拍摄时刻、区县级地名。原始经纬度在这里就已经被
 * 换成地名（nearestPlace），不会出现在返回对象里，因此也不可能随故事请求外发。
 */
import type { ExifMeta } from './exif'
import type { CityRow } from './cityTrie'
import type { PhotoCapture } from '../types'
import { nearestPlace } from './place'

export type { PhotoCapture }

/**
 * EXIF ASCII 时间形如 `2025:03:14 22:40:11`（日期分隔符是冒号）。
 * 归一化成 ISO 风格并丢掉秒位——故事只需要「什么时候」，不需要秒级精度。
 * 任何解析失败都返回 undefined，绝不把原始串透传给模型。
 */
export function formatExifDateTime(raw: string | undefined): string | undefined {
  if (!raw) return undefined
  const m = /^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2})/.exec(raw.trim())
  if (!m) return undefined
  const [, y, mo, d, hh, mm] = m
  const month = Number(mo)
  const day = Number(d)
  const hour = Number(hh)
  const minute = Number(mm)
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) return undefined
  return `${y}-${mo}-${d} ${hh}:${mm}`
}

/**
 * 组装 capture。`rows` 传城市表条目；为空数组时只做时间，不做地名。
 * 无 GPS 时不去拉城市数据（调用方负责只在有坐标时才 await loadCityIndex）。
 */
export function buildCapture(meta: ExifMeta, rows: CityRow[]): PhotoCapture {
  const out: PhotoCapture = {}
  const capturedAt = formatExifDateTime(meta.dateTimeOriginal)
  if (capturedAt) out.captured_at = capturedAt
  if (meta.lat !== undefined && meta.lon !== undefined && rows.length) {
    const hit = nearestPlace(rows, meta.lat, meta.lon)
    if (hit) out.place = hit.label
  }
  return out
}
