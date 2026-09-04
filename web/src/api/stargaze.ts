import type { StargazeIndex } from '../types'

export interface StargazeOptions {
  /** 曲线跨度：1 = 未来 24h，7 = 未来 7 天 */
  days?: 1 | 7
  signal?: AbortSignal
}

/**
 * 拉取观星指数。失败（502 WEATHER_DOWN / 网络异常）抛 Error，
 * 由 store 统一映射为错误态文案。
 */
export async function fetchStargazeIndex(
  lat: number,
  lon: number,
  options: StargazeOptions = {},
): Promise<StargazeIndex> {
  const { days = 1, signal } = options
  const r = await fetch(
    `/api/index?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&days=${days}`,
    { signal },
  )
  if (!r.ok) throw new Error(`API /api/index HTTP ${r.status}`)
  return (await r.json()) as StargazeIndex
}