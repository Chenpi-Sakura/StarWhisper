/** Open-Meteo Geocoding 城市搜索结果。 */
export interface GeoResult {
  name: string
  admin1?: string
  country?: string
  latitude: number
  longitude: number
}

/** 任意城市模糊搜索（Open-Meteo Geocoding，免费 + CORS 开放）。 */
export async function searchCity(
  q: string,
  signal?: AbortSignal,
): Promise<GeoResult[]> {
  const url =
    `https://geocoding-api.open-meteo.com/v1/search?name=` +
    `${encodeURIComponent(q)}&count=6&language=zh&format=json`
  const r = await fetch(url, { signal })
  if (!r.ok) throw new Error(`Geocoding HTTP ${r.status}`)
  const data = (await r.json()) as { results?: GeoResult[] }
  return data.results ?? []
}