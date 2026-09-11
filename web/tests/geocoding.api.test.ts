import { afterEach, describe, expect, it, vi } from 'vitest'

import { searchCity } from '../src/api/geocoding'

describe('geocoding api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('拼接查询参数并解析 results', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          results: [
            { name: '冷湖', admin1: '青海', latitude: 38.0, longitude: 93.4 },
          ],
        }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const got = await searchCity('冷湖')
    expect(got).toHaveLength(1)
    expect(got[0].name).toBe('冷湖')
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('geocoding-api.open-meteo.com/v1/search')
    expect(url).toContain('name=')
    expect(url).toContain('language=zh')
  })

  it('无结果返回空数组', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
    )
    expect(await searchCity('不存在的城')).toEqual([])
  })

  it('HTTP 非 200 抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    )
    await expect(searchCity('x')).rejects.toThrow()
  })
})