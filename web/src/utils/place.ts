/**
 * GPS → 区县级地名反查（喂给 AI 故事的唯一位置表述）。
 *
 * 设计约束：原始经纬度**不出浏览器**。故事 prompt 只拿到「四川省成都市锦江区」
 * 这一串地名，精度到区县（约数十公里），既够模型讲出季节与方位感，又不把用户
 * 的精确拍摄坐标送进第三方模型请求。
 *
 * 距离用等距柱面近似（不做 haversine）：3237 条、只比大小、误差对 150km 阈值无影响。
 */
import type { CityRow } from './cityTrie'

export interface PlaceHit {
  /** 区县级名称，如「锦江区」 */
  name: string
  /** 省 → 市 → 区 链（父级缺失时自动缩短），如 ['四川省', '成都市', '锦江区'] */
  chain: string[]
  /** chain 拼接结果，直接进 prompt 用 */
  label: string
  /** 距该条目中心的近似公里数 */
  km: number
}

const KM_PER_DEG = 111.32
/** 区县级条目 */
const LEVEL_DISTRICT = 0
/** 超过这个距离说明照片不在任何已收录区县附近（海上 / 境外 / 数据缺失），不猜地名。 */
export const DEFAULT_MAX_KM = 150
/** 父级链最大深度（省→市→区 已够，防数据环）。 */
const MAX_CHAIN = 4

function approxKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = lat2 - lat1
  const dLon = (lon2 - lon1) * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180))
  return Math.sqrt(dLat * dLat + dLon * dLon) * KM_PER_DEG
}

function chainOf(rows: CityRow[], index: number): string[] {
  const out: string[] = []
  const seen = new Set<number>()
  let cur: number | undefined = index
  while (cur !== undefined && cur >= 0 && cur < rows.length && out.length < MAX_CHAIN) {
    if (seen.has(cur)) break
    seen.add(cur)
    out.unshift(rows[cur][0])
    // 显式标注打断 TS 的循环推断：cur 的收窄依赖 parent，parent 又依赖 cur
    const parent: number = rows[cur][4]
    cur = parent === -1 ? undefined : parent
  }
  return out
}

/**
 * 返回距 (lat, lon) 最近的区县级条目；超出 `maxKm` 或数据为空时返回 null。
 * 调用方负责只在拿到 GPS 时才反查（见 stores/scan.ts）。
 */
export function nearestPlace(
  rows: CityRow[],
  lat: number,
  lon: number,
  maxKm: number = DEFAULT_MAX_KM,
): PlaceHit | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null

  let best = -1
  let bestKm = Infinity
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (row[3] !== LEVEL_DISTRICT) continue
    const km = approxKm(lat, lon, row[2], row[1])
    if (km < bestKm) {
      bestKm = km
      best = i
    }
  }
  if (best < 0 || bestKm > maxKm) return null

  const chain = chainOf(rows, best)
  return { name: rows[best][0], chain, label: chain.join(''), km: Math.round(bestKm) }
}
