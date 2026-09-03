import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../src/api/atlas', () => ({
  listTraditions: vi.fn(),
  listConstellations: vi.fn(),
  getConstellation: vi.fn(),
}))

import * as api from '../src/api/atlas'
import { useAtlasStore } from '../src/stores/atlas'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('atlas store tradition 维度', () => {
  it('loadTraditions 缓存后不再调 API', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [{ key: 'western', label: '西方星座', count: 5 }],
    })
    const store = useAtlasStore()
    await store.loadTraditions()
    await store.loadTraditions()
    expect(api.listTraditions).toHaveBeenCalledTimes(1)
  })

  it('setTradition 触发 list', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [
        { key: 'western', label: '西方星座', count: 5 },
        { key: 'chinese', label: '中国古代星空', count: 0 },
      ],
    })
    vi.mocked(api.listConstellations).mockResolvedValue({
      tradition: 'chinese', items: [],
    })
    const store = useAtlasStore()
    await store.loadTraditions()
    await store.setTradition('chinese')
    expect(store.currentTradition).toBe('chinese')
    expect(api.listConstellations).toHaveBeenCalledWith('chinese')
  })

  it('setTradition 相同值不重新 list', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [{ key: 'western', label: '西方星座', count: 5 }],
    })
    vi.mocked(api.listConstellations).mockResolvedValue({
      tradition: 'western', items: [],
    })
    const store = useAtlasStore()
    await store.loadTraditions()
    await store.setTradition('western')
    await store.setTradition('western')
    expect(api.listConstellations).toHaveBeenCalledTimes(1)
  })

  it('getAtlas 缓存命中不调 API', async () => {
    vi.mocked(api.getConstellation).mockResolvedValue({
      ok: true, abbr: 'ori', stars: {},
    } as any)
    const store = useAtlasStore()
    await store.getAtlas('western', 'ori')
    await store.getAtlas('western', 'ori')
    expect(api.getConstellation).toHaveBeenCalledTimes(1)
  })

  it('currentItems 返回当前 tradition 的列表', async () => {
    vi.mocked(api.listTraditions).mockResolvedValue({
      items: [
        { key: 'western', label: '西方星座', count: 5 },
        { key: 'chinese', label: '中国古代星空', count: 0 },
      ],
    })
    vi.mocked(api.listConstellations)
      .mockResolvedValueOnce({ tradition: 'western', items: [{ abbr: 'ori' } as any] })
      .mockResolvedValueOnce({ tradition: 'chinese', items: [{ abbr: 'shen' } as any] })
    const store = useAtlasStore()
    await store.setTradition('western')
    await store.setTradition('chinese')
    expect(store.currentItems[0].abbr).toBe('shen')
  })
})
