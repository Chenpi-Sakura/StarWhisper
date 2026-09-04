import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import type { StargazeIndex } from '../src/types'

const fetchMock = vi.fn()
vi.mock('../src/api/stargaze', () => ({
  fetchStargazeIndex: (...a: unknown[]) => fetchMock(...a),
}))

import { useStargazeStore, DEFAULT_LOCATION } from '../src/stores/stargaze'

function sampleIndex(over: Partial<StargazeIndex> = {}): StargazeIndex {
  return {
    ok: true,
    city: '北京',
    province: '北京',
    lat: 39.9,
    lon: 116.4,
    timezone: 'Asia/Shanghai',
    bortle: 8,
    bortle_label: '城市',
    score: 72,
    grade: '良',
    moon: { phase: 13.4, illumination: 0.99, label: '满月' },
    now: { time: '2026-08-27T00:00', cloud: 10, precip: 0, wind: 5, temp: 20 },
    components: { cloud: 90, precip: 100, windtemp: 80, moon: 1, bortle: 5 },
    hourly: [{ time: '2026-08-27T00:00', score: 72, grade: '良', cloud: 10, precip: 0 }],
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  fetchMock.mockReset()
  // @ts-expect-error 清理可能的 geolocation 桩
  delete navigator.geolocation
})

describe('stargaze store', () => {
  it('load 成功写入 data 并更新 location', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    expect(store.status).toBe('ready')
    expect(store.data?.score).toBe(72)
    expect(store.location.label).toBe('北京')
  })

  it('load 失败进入 error 态并给出文案', async () => {
    fetchMock.mockRejectedValue(new Error('HTTP 502'))
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('天气服务暂不可用，请稍后重试')
  })

  it('setRange 切换天数并重新拉取', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    await store.load(39.9, 116.4)
    fetchMock.mockClear()
    await store.setRange(7)
    expect(store.rangeDays).toBe(7)
    expect(fetchMock).toHaveBeenCalledWith(39.9, 116.4, { days: 7 })
  })

  it('locate 无 geolocation 时回退默认城市', async () => {
    fetchMock.mockResolvedValue(sampleIndex())
    const store = useStargazeStore()
    store.locate()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon, { days: 1 })
  })

  it('locate geolocation 成功时用真实坐标', async () => {
    // @ts-expect-error 注入 geolocation 成功回调
    navigator.geolocation = {
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 25.0, longitude: 121.0 } } as GeolocationPosition),
    }
    fetchMock.mockResolvedValue(sampleIndex({ city: '台北', lat: 25.0, lon: 121.0 }))
    const store = useStargazeStore()
    store.locate()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(25.0, 121.0, { days: 1 })
    expect(store.location.label).toBe('台北')
  })
})