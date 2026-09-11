import type { StargazeIndex } from '../types'

export interface StargazeOptions {
  /** 曲线跨度：1 = 未来 24h，7 = 未来 7 天（向后兼容，映射 startHour=0 + hours=24/168） */
  days?: 1 | 7
  /** 起始小时偏移 0-167 */
  startHour?: number
  /** 区间长度 1-168 */
  hours?: number
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
  const { days, startHour, hours, signal } = options
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
  })
  if (days !== undefined) params.set('days', String(days))
  if (startHour !== undefined) params.set('start_hour', String(startHour))
  if (hours !== undefined) params.set('hours', String(hours))
  const r = await fetch(`/api/index?${params.toString()}`, { signal })
  if (!r.ok) throw new Error(`API /api/index HTTP ${r.status}`)
  return (await r.json()) as StargazeIndex
}