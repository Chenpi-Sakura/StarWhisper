import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listTraditions, listConstellations, getConstellation } from '../src/api/atlas'

describe('atlas api', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('listTraditions 命中', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => [{ key: 'western', label: '西方星座', count: 5 }],
    } as Response)
    const r = await listTraditions()
    expect(r.items[0].key).toBe('western')
    expect(r.items[0].label).toBe('西方星座')
  })

  it('listConstellations 传 tradition', async () => {
    const mock = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ tradition: 'western', items: [{ abbr: 'ori', name: '猎户座' }] }),
    } as Response)
    await listConstellations('western')
    const url = mock.mock.calls[0][0] as string
    expect(url).toContain('tradition=western')
  })

  it('getConstellation 路径含 tradition 和 abbr', async () => {
    const mock = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ ok: true, abbr: 'ori', stars: {} }),
    } as Response)
    await getConstellation('western', 'ori')
    const url = mock.mock.calls[0][0] as string
    expect(url).toBe('/api/constellation/western/ori')
  })

  it('getConstellation 404 抛 CONSTELLATION_NOT_FOUND', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false, status: 404, json: async () => ({ ok: false, code: 'CONSTELLATION_NOT_FOUND' }),
    } as Response)
    await expect(getConstellation('western', 'xxx')).rejects.toThrow('CONSTELLATION_NOT_FOUND')
  })
})
