/** Open-Meteo 在线兜底搜索结果（仅用于本地城市表未命中时，限定中国）。 */
export interface GeoResult {
  name: string
  admin1?: string
  admin2?: string
  country?: string
  country_code?: string
  latitude: number
  longitude: number
  feature_code?: string
}

/**
 * 在线地名兜底搜索（Open-Meteo Geocoding，免费 + CORS 开放）。
 *
 * 只在本地前缀索引 0 命中时调用，用于覆盖行政区划表里没有的镇/景区
 * （实测「冷湖」「纳木错」可得）。`countryCode=CN` 把结果限定在中国。
 */
export async function searchCity(
  q: string,
  signal?: AbortSignal,
): Promise<GeoResult[]> {
  const url =
    `https://geocoding-api.open-meteo.com/v1/search?name=` +
    `${encodeURIComponent(q)}&count=6&language=zh&format=json&countryCode=CN`
  const r = await fetch(url, { signal })
  if (!r.ok) throw new Error(`Geocoding HTTP ${r.status}`)
  const data = (await r.json()) as { results?: GeoResult[] }
  return data.results ?? []
}
