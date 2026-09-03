import type {
  AtlasListResponse,
  AtlasListItem,
  ConstellationAtlas,
  TraditionListItem,
  TraditionListResponse,
} from '../types'

export interface AtlasListResponseV2 {
  tradition: string
  items: AtlasListItem[]
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (r.status === 404) {
    const body = await r.json().catch(() => ({})) as { code?: string }
    throw new Error(body.code || 'HTTP 404')
  }
  if (!r.ok) throw new Error(`API ${path} HTTP ${r.status}`)
  return (await r.json()) as T
}

export async function listTraditions(): Promise<TraditionListResponse> {
  const items = await get<TraditionListItem[]>('/api/traditions')
  return { items }
}

export async function listConstellations(tradition: string): Promise<AtlasListResponseV2> {
  return get<AtlasListResponseV2>(
    `/api/constellations?tradition=${encodeURIComponent(tradition)}`,
  )
}

export async function getConstellation(
  tradition: string,
  abbr: string,
): Promise<ConstellationAtlas> {
  return get<ConstellationAtlas>(
    `/api/constellation/${encodeURIComponent(tradition)}/${encodeURIComponent(abbr)}`,
  )
}